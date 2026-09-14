"""Idempotent local Docker driver. Only the worker receives these privileges."""

import json
import re
import secrets
import socket
import time
from pathlib import Path
from typing import Any

import boto3
import docker
import httpx
import jwt
import psycopg
from botocore.config import Config
from botocore.exceptions import ClientError
from docker.errors import NotFound
from psycopg import sql

from sibase.control.config import Settings
from sibase.control.models import now


def credentials() -> dict[str, Any]:
    return {
        "jwt_secret": secrets.token_hex(32),
        "secret_key_base": secrets.token_hex(32),
        "db_enc_key": secrets.token_hex(8),
        "s3_key": secrets.token_hex(12),
        "s3_secret": secrets.token_hex(24),
        "passwords": {
            role: secrets.token_hex(24)
            for role in ("auth", "rest", "storage", "realtime", "owner", "monitor")
        },
    }


def tokens(secret: str) -> dict[str, str]:
    return {
        role: jwt.encode(
            {
                "role": role,
                "iss": "sibase-internal",
                "aud": "authenticated",
                "iat": now(),
                "exp": now() + 365 * 86400,
            },
            secret,
            algorithm="HS256",
        )
        for role in ("anon", "service_role")
    }


class Driver:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = docker.from_env()

    def name(self, ref: str, kind: str) -> str:
        if not re.fullmatch(r"p_[0-9a-f]{16}", ref):
            raise ValueError("Invalid immutable project reference")
        return f"{self.settings.stack}-{kind}-{ref}"

    def connect(self, dbname: str = "postgres", **kwargs: Any) -> psycopg.Connection[Any]:
        return psycopg.connect(
            host="data-db",
            dbname=dbname,
            user="postgres",
            password=self.settings.data_password,
            connect_timeout=5,
            **kwargs,
        )

    def bootstrap(self, ref: str, project_id: str, secret: dict[str, Any]) -> None:
        self.name(ref, "db")
        with self.connect(autocommit=True) as conn:
            exists = conn.execute("SELECT 1 FROM pg_database WHERE datname=%s", (ref,)).fetchone()
            if not exists:
                conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(ref)))
            conn.execute(
                sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(ref))
            )
        with self.connect(ref) as conn:
            marker = conn.execute("SELECT to_regclass('public.sibase_project_identity')").fetchone()
            if marker and marker[0]:
                row = conn.execute(
                    "SELECT project_id FROM public.sibase_project_identity"
                ).fetchone()
                if row != (project_id,):
                    raise RuntimeError("Project identity collision")
                return
            template = (
                Path("migrations/projects/bootstrap.sql").read_text().replace("@PROJECT@", ref)
            )
            for role, password in secret["passwords"].items():
                if not re.fullmatch("[0-9a-f]{48}", password):
                    raise ValueError("Invalid generated credential")
                template = template.replace(f"@{role.upper()}_PASSWORD@", password)
            conn.execute(template)
            conn.execute(
                "CREATE TABLE public.sibase_project_identity (project_id text PRIMARY KEY)"
            )
            conn.execute("REVOKE ALL ON public.sibase_project_identity FROM PUBLIC")
            conn.execute("INSERT INTO public.sibase_project_identity VALUES (%s)", (project_id,))

    def ensure_container(self, ref: str, kind: str, env: dict[str, str], **kwargs: Any) -> None:
        name = self.name(ref, kind)
        labels = {"sibase.stack": self.settings.stack, "sibase.project": ref}
        try:
            container = self.client.containers.get(name)
            if any(container.labels.get(k) != v for k, v in labels.items()):
                raise RuntimeError("Resource ownership mismatch")
            actual = dict(item.split("=", 1) for item in container.attrs["Config"]["Env"])
            if any(actual.get(k) != v for k, v in env.items()):
                container.stop(timeout=60)
                container.remove(v=False)
                raise NotFound("Recreate owned service with updated configuration")
        except NotFound:
            container = self.client.containers.create(
                self.settings.images[kind],
                name=name,
                environment=env,
                network=f"{self.settings.stack}_data",
                labels=labels,
                detach=True,
                restart_policy={"Name": "on-failure", "MaximumRetryCount": 5},
                init=True,
                log_config=docker.types.LogConfig(
                    type="json-file", config={"max-size": "5m", "max-file": "2"}
                ),
                **kwargs,
            )
        if container.status != "running":
            container.start()

    def start(self, ref: str, secret: dict[str, Any], internal: dict[str, str]) -> None:
        settings = self.settings
        endpoint = f"{settings.gateway_url}/p/{ref}"
        passwords, signing = secret["passwords"], secret["jwt_secret"]
        auth, rest, storage, realtime, s3 = (
            self.name(ref, k) for k in ("auth", "rest", "storage", "realtime", "s3")
        )
        volume_name = self.name(ref, "objects")
        labels = {"sibase.stack": settings.stack, "sibase.project": ref}
        try:
            volume = self.client.volumes.get(volume_name)
            if any((volume.attrs.get("Labels") or {}).get(k) != v for k, v in labels.items()):
                raise RuntimeError("Volume ownership mismatch")
        except NotFound:
            self.client.volumes.create(volume_name, labels=labels)
        identities = {
            "identities": [
                {
                    "name": ref,
                    "credentials": [
                        {"accessKey": secret["s3_key"], "secretKey": secret["s3_secret"]}
                    ],
                    "actions": ["Admin", "Read", "Write", "List", "Tagging"],
                }
            ]
        }
        self.ensure_container(
            ref,
            "s3",
            {"S3_CONFIG": json.dumps(identities)},
            entrypoint=["/bin/sh", "-ec"],
            command=[
                'printf "%s" "$S3_CONFIG" > /run/s3.json; exec weed server -dir=/data -s3 -s3.config=/run/s3.json -s3.iam=false -s3.port.iceberg=0 -s3.port.lance=0 -master.telemetry=false -volume.max=32 -master.volumeSizeLimitMB=64 -ip='
                + s3
            ],
            tmpfs={"/run": "rw,noexec,nosuid,size=1m"},
            volumes={volume_name: {"bind": "/data", "mode": "rw"}},
        )

        def url(role: str) -> str:
            return f"postgres://{ref}_{role}:{passwords[role]}@data-db:5432/{ref}"

        auth_config = secret.get("app_auth")
        auth_env = (
            {}
            if not auth_config
            else {
                "API_EXTERNAL_URL": settings.gateway_url,
                **{
                    f"GOTRUE_MAILER_URLPATHS_{kind}": f"/p/{ref}/auth/v1/verify"
                    for kind in ("CONFIRMATION", "RECOVERY", "INVITE", "EMAIL_CHANGE")
                },
                "GOTRUE_SITE_URL": auth_config["site_url"],
                "GOTRUE_URI_ALLOW_LIST": auth_config["site_url"],
                "GOTRUE_JWT_EXP": str(auth_config["jwt_exp"]),
                "GOTRUE_MAILER_AUTOCONFIRM": "false",
                "GOTRUE_SMTP_HOST": settings.smtp_host,
                "GOTRUE_SMTP_PORT": str(settings.smtp_port),
                "GOTRUE_SMTP_USER": settings.smtp_user,
                "GOTRUE_SMTP_PASS": settings.smtp_password,
                "GOTRUE_SMTP_ADMIN_EMAIL": settings.smtp_sender,
                "GOTRUE_SMTP_SENDER_NAME": "SiBase Local Auth",
                "GOTRUE_SMTP_MAX_FREQUENCY": "1s",
                "GOTRUE_MAILER_OTP_EXP": "600",
                "GOTRUE_PASSWORD_MIN_LENGTH": "12",
                "GOTRUE_SECURITY_REFRESH_TOKEN_ROTATION_ENABLED": "true",
                "GOTRUE_SECURITY_REFRESH_TOKEN_REUSE_INTERVAL": "0",
                "GOTRUE_SECURITY_REFRESH_TOKEN_ALLOW_REUSE": "false",
                "GOTRUE_SECURITY_UPDATE_PASSWORD_REQUIRE_REAUTHENTICATION": "true",
            }
        )

        self.ensure_container(
            ref,
            "auth",
            {
                "GOTRUE_API_HOST": "0.0.0.0",
                "GOTRUE_API_PORT": "9999",
                "API_EXTERNAL_URL": endpoint + "/auth/v1",
                "GOTRUE_DB_DRIVER": "postgres",
                "GOTRUE_DB_DATABASE_URL": url("auth"),
                "GOTRUE_SITE_URL": settings.origins[0],
                "GOTRUE_JWT_SECRET": signing,
                "GOTRUE_JWT_ISSUER": endpoint + "/auth/v1",
                "GOTRUE_JWT_AUD": "authenticated",
                "GOTRUE_JWT_DEFAULT_GROUP_NAME": "authenticated",
                "GOTRUE_JWT_ADMIN_ROLES": "service_role",
                "GOTRUE_JWT_EXP": "900",
                "GOTRUE_EXTERNAL_EMAIL_ENABLED": "true",
                "GOTRUE_MAILER_AUTOCONFIRM": "true",
                "GOTRUE_RATE_LIMIT_EMAIL_SENT": "1000",
                **auth_env,
            },
        )
        self.ensure_container(
            ref,
            "rest",
            {
                "PGRST_DB_URI": url("rest"),
                "PGRST_DB_SCHEMAS": "public",
                "PGRST_DB_ANON_ROLE": "anon",
                "PGRST_JWT_SECRET": signing,
                "PGRST_DB_MAX_ROWS": "1000",
                "PGRST_DB_POOL": "5",
                **({"PGRST_JWT_AUD": "authenticated"} if auth_config else {}),
            },
        )
        self.ensure_container(
            ref,
            "storage",
            {
                "DATABASE_URL": url("storage"),
                "DB_INSTALL_ROLES": "false",
                "DB_SUPER_USER": f"{ref}_storage",
                "ANON_KEY": internal["anon"],
                "SERVICE_KEY": internal["service_role"],
                "AUTH_JWT_SECRET": signing,
                "POSTGREST_URL": f"http://{rest}:3000",
                "TENANT_ID": ref,
                "REGION": "us-east-1",
                "STORAGE_BACKEND": "s3",
                "GLOBAL_S3_BUCKET": "sibase-" + ref.replace("_", "-"),
                "GLOBAL_S3_ENDPOINT": f"http://{s3}:8333",
                "GLOBAL_S3_PROTOCOL": "http",
                "GLOBAL_S3_FORCE_PATH_STYLE": "true",
                "AWS_ACCESS_KEY_ID": secret["s3_key"],
                "AWS_SECRET_ACCESS_KEY": secret["s3_secret"],
                "FILE_SIZE_LIMIT": "10485760",
                "ENABLE_IMAGE_TRANSFORMATION": "false",
                "S3_PROTOCOL_ENABLED": "false",
                "DATABASE_MAX_CONNECTIONS": "5",
                "STORAGE_PUBLIC_URL": endpoint,
                "REQUEST_ALLOW_X_FORWARDED_PATH": "true",
            },
        )
        self.ensure_container(
            ref,
            "realtime",
            {
                "PORT": "4000",
                "DB_HOST": "data-db",
                "DB_PORT": "5432",
                "DB_NAME": ref,
                "DB_USER": f"{ref}_realtime",
                "DB_PASSWORD": passwords["realtime"],
                "DB_AFTER_CONNECT_QUERY": "SET search_path TO _realtime",
                "DB_ENC_KEY": secret["db_enc_key"],
                "API_JWT_SECRET": signing,
                "METRICS_JWT_SECRET": signing,
                "SECRET_KEY_BASE": secret["secret_key_base"],
                "ERL_AFLAGS": "+S 2:2 -proto_dist inet_tcp",
                "DNS_NODES": "''",
                "APP_NAME": realtime,
                "SELF_HOST_TENANT_NAME": realtime,
                "SLOT_NAME_SUFFIX": ref,
                "SEED_SELF_HOST": "true",
                "RUN_JANITOR": "true",
                "DB_IP_VERSION": "ipv4",
                "DB_SSL": "false",
            },
        )

    def health(self, ref: str, secret: dict[str, Any], internal: dict[str, str]) -> None:
        # Bounded readiness: transient failures are retried by the durable job.
        with httpx.Client(timeout=5) as client:
            client.get(f"http://{self.name(ref, 'auth')}:9999/health").raise_for_status()
        with psycopg.connect(
            host="data-db",
            dbname=ref,
            user=f"{ref}_auth",
            password=secret["passwords"]["auth"],
            connect_timeout=5,
        ) as conn:
            conn.execute(Path("migrations/projects/0001_auth_claims.sql").read_text())
        s3 = boto3.client(
            "s3",
            # Immutable SQL references contain underscores; botocore requires
            # RFC-compliant endpoint hosts. Resolve our fixed Docker service only.
            endpoint_url=f"http://{socket.gethostbyname(self.name(ref, 's3'))}:8333",
            region_name="us-east-1",
            aws_access_key_id=secret["s3_key"],
            aws_secret_access_key=secret["s3_secret"],
            config=Config(connect_timeout=3, read_timeout=5, retries={"max_attempts": 1}),
        )
        bucket = "sibase-" + ref.replace("_", "-")
        try:
            s3.create_bucket(Bucket=bucket)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "BucketAlreadyOwnedByYou":
                raise
            s3.head_bucket(Bucket=bucket)
        with httpx.Client(timeout=5) as client:
            if secret.get("app_auth") and secret.get("signing_epoch", 1) > 1:
                realtime = self.name(ref, "realtime")
                client.put(
                    f"http://{realtime}:4000/api/tenants/{realtime}",
                    headers={"Authorization": "Bearer " + internal["service_role"]},
                    json={"tenant": {"jwt_secret": secret["jwt_secret"]}},
                ).raise_for_status()
            for kind, port, path in [
                ("rest", 3000, "/"),
                ("storage", 5000, "/status"),
                ("realtime", 4000, f"/api/tenants/{self.name(ref, 'realtime')}/health"),
            ]:
                response = client.get(
                    f"http://{self.name(ref, kind)}:{port}{path}",
                    headers={"Authorization": "Bearer " + internal["anon"]},
                )
                response.raise_for_status()
                if (
                    kind == "realtime"
                    and response.json().get("data", {}).get("healthy") is not True
                ):
                    raise RuntimeError("Realtime not healthy")
            topology = client.get(f"http://{self.name(ref, 's3')}:9333/dir/status").json()
            if not topology.get("Topology", {}).get("DataCenters"):
                raise RuntimeError("Object volume not registered")

    def stop(self, ref: str) -> None:
        for kind in ("realtime", "storage", "rest", "auth", "s3"):
            try:
                container = self.client.containers.get(self.name(ref, kind))
            except NotFound:
                continue
            if (
                container.labels.get("sibase.project") != ref
                or container.labels.get("sibase.stack") != self.settings.stack
            ):
                raise RuntimeError("Resource ownership mismatch")
            if container.status == "running":
                container.stop(timeout=60)

    def await_health(self, ref: str, secret: dict[str, Any], internal: dict[str, str]) -> None:
        for _ in range(45):
            try:
                self.health(ref, secret, internal)
                return
            except Exception:
                time.sleep(2)
        raise RuntimeError("Services did not become healthy within readiness deadline")
