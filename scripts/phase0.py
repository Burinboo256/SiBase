#!/usr/bin/env python3
"""Reproducible, local-only Phase 0 stack. Requires Python 3.11+ and Docker.

Generated secrets/configuration stay in .local/phase0; source files are immutable.
The CLI never removes volumes or other projects' resources.
"""

import argparse
import base64
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "poc" / "phase0"
LOCAL = ROOT / ".local" / "phase0"
COMPOSE = LOCAL / "compose.json"
IMAGES = json.loads((SOURCE / "images.lock.json").read_text())["images"]


def write_generated(path, value):
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)


def jwt(secret, role):
    def encode(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=")
    message = encode({"alg": "HS256", "typ": "JWT"}) + b"." + encode({
        "role": role, "iss": "sibase-local-poc", "iat": int(time.time()),
        "exp": int(time.time()) + 30 * 86400,
    })
    signature = base64.urlsafe_b64encode(hmac.new(secret.encode(), message, hashlib.sha256).digest()).rstrip(b"=")
    return (message + b"." + signature).decode()


def prepare(*, local=LOCAL, stack_name="sibase-phase0", port_base=58101,
            isolated_roles=False, project_template=None):
    """Generate the legacy PoC or a separate, hardened development data plane."""
    LOCAL = local
    COMPOSE = LOCAL / "compose.json"
    LOCAL.mkdir(parents=True, exist_ok=True)
    LOCAL.chmod(0o700)
    secret_file = LOCAL / "secrets.json"
    if secret_file.exists():
        state = json.loads(secret_file.read_text())
    else:
        state = {"admin_password": secrets.token_hex(24), "s3_admin": secrets.token_hex(24), "projects": {}}
        for name in ("alpha", "beta"):
            key = secrets.token_hex(32)
            state["projects"][name] = {
                "password": secrets.token_hex(24), "jwt_secret": key,
                "anon_key": jwt(key, "anon"), "service_key": jwt(key, "service_role"),
                "secret_key_base": secrets.token_hex(32), "db_enc_key": secrets.token_hex(8),
                "s3_key": secrets.token_hex(12), "s3_secret": secrets.token_hex(24),
            }
        if isolated_roles:
            for config in state["projects"].values():
                config.pop("password")
                config["passwords"] = {role: secrets.token_hex(24) for role in
                                       ("auth", "rest", "storage", "realtime", "owner", "monitor")}
        write_generated(secret_file, json.dumps(state, indent=4) + "\n")
    sql = [
        "CREATE ROLE anon NOLOGIN; CREATE ROLE authenticated NOLOGIN;",
        "CREATE ROLE service_role NOLOGIN BYPASSRLS;",
        "CREATE ROLE supabase_realtime_admin NOLOGIN NOINHERIT;",
        "CREATE ROLE dashboard_user NOLOGIN;",
        "REVOKE CONNECT ON DATABASE postgres FROM PUBLIC;",
        "REVOKE CONNECT ON DATABASE template1 FROM PUBLIC;",
    ]
    template = (project_template or SOURCE / "project.sql").read_text()
    for name, config in state["projects"].items():
        project_sql = template.replace("@PROJECT@", name)
        if isolated_roles:
            for role, password in config["passwords"].items():
                project_sql = project_sql.replace(f"@{role.upper()}_PASSWORD@", password)
        else:
            project_sql = project_sql.replace("@PASSWORD@", config["password"])
        sql += [f"CREATE DATABASE {name};", f"REVOKE ALL ON DATABASE {name} FROM PUBLIC;", f"\\connect {name}",
                project_sql]
    write_generated(LOCAL / "init.sql", "\n".join(sql) + "\n")

    identities = [{"name": "bootstrap", "credentials": [{"accessKey": "poc-admin", "secretKey": state["s3_admin"]}], "actions": ["Admin", "Read", "Write", "List", "Tagging"]}]
    for name, config in state["projects"].items():
        identities.append({"name": name, "credentials": [{"accessKey": config["s3_key"], "secretKey": config["s3_secret"]}], "actions": [f"{action}:sibase-{name}" for action in ["Read", "Write", "List", "Tagging"]]})
    write_generated(LOCAL / "s3.json", json.dumps({"identities": identities}, indent=4))

    services = {
        "db": {
            "build": {"context": str(SOURCE), "dockerfile": "postgres.Dockerfile"},
            "image": "sibase-phase0-postgres:17.6-wal2json",
            "environment": {"POSTGRES_PASSWORD": state["admin_password"]},
            "command": ["postgres", "-c", "wal_level=logical", "-c", "max_replication_slots=20", "-c", "max_wal_senders=20", "-c", "max_connections=250"],
            "volumes": ["pgdata:/var/lib/postgresql/data", f"{LOCAL}/init.sql:/docker-entrypoint-initdb.d/00-init.sql:ro"],
            "healthcheck": {"test": ["CMD-SHELL", "pg_isready -U postgres -d postgres"], "interval": "3s", "timeout": "3s", "retries": 40},
        },
        "s3": {"image": IMAGES["s3"], "command": ["server", "-dir=/data", "-s3", "-s3.config=/etc/seaweedfs/s3.json", "-s3.iam=false", "-s3.port.iceberg=0", "-s3.port.lance=0", "-master.telemetry=false", "-volume.max=32", "-master.volumeSizeLimitMB=64", "-ip=s3"],
               "volumes": ["objects:/data", f"{LOCAL}/s3.json:/etc/seaweedfs/s3.json:ro"]},
    }
    nginx = ["events {}", "http {", "    access_log off;", "    map_hash_bucket_size 512;", "    client_max_body_size 10m;", "    resolver 127.0.0.11 valid=5s ipv6=off;", "    map $http_upgrade $connection_upgrade { default upgrade; '' close; }"]
    db_dependency = {"db": {"condition": "service_healthy"}}
    for index, (name, config) in enumerate(state["projects"].items()):
        passwords = config.get("passwords", {role: config.get("password") for role in ("auth", "rest", "storage", "realtime")})
        key = config["jwt_secret"]
        url = f"http://127.0.0.1:{port_base + index}"
        for kind, port in [("auth", 9999), ("rest", 3000), ("storage", 5000), ("realtime", 4000)]:
            nginx.append(f"    upstream {kind}_{name} {{ zone {kind}_{name} 64k; server {kind}-{name}:{port} resolve; }}")
        services[f"auth-{name}"] = {
            "image": IMAGES["auth"], "depends_on": db_dependency,
            "environment": {
                "GOTRUE_API_HOST": "0.0.0.0", "GOTRUE_API_PORT": "9999", "API_EXTERNAL_URL": url + "/auth/v1",
                "GOTRUE_DB_DRIVER": "postgres", "GOTRUE_DB_DATABASE_URL": f"postgres://{name}_auth:{passwords['auth']}@db:5432/{name}",
                "GOTRUE_SITE_URL": "http://localhost:58100", "GOTRUE_JWT_SECRET": key,
                "GOTRUE_JWT_ISSUER": url + "/auth/v1", "GOTRUE_JWT_AUD": "authenticated",
                "GOTRUE_JWT_DEFAULT_GROUP_NAME": "authenticated", "GOTRUE_JWT_ADMIN_ROLES": "service_role", "GOTRUE_JWT_EXP": "900",
                "GOTRUE_EXTERNAL_EMAIL_ENABLED": "true", "GOTRUE_MAILER_AUTOCONFIRM": "true", "GOTRUE_RATE_LIMIT_EMAIL_SENT": "1000",
            },
        }
        services[f"rest-{name}"] = {
            "image": IMAGES["rest"], "depends_on": db_dependency,
            "environment": {"PGRST_DB_URI": f"postgres://{name}_rest:{passwords['rest']}@db:5432/{name}", "PGRST_DB_SCHEMAS": "public", "PGRST_DB_ANON_ROLE": "anon", "PGRST_JWT_SECRET": key, "PGRST_DB_MAX_ROWS": "1000"},
        }
        services[f"storage-{name}"] = {
            "image": IMAGES["storage"], "depends_on": db_dependency,
            "environment": {
                "DATABASE_URL": f"postgres://{name}_storage:{passwords['storage']}@db:5432/{name}", "DB_INSTALL_ROLES": "false", "DB_SUPER_USER": f"{name}_storage",
                "ANON_KEY": config["anon_key"], "SERVICE_KEY": config["service_key"], "AUTH_JWT_SECRET": key,
                "POSTGREST_URL": f"http://rest-{name}:3000", "TENANT_ID": name, "REGION": "us-east-1",
                "STORAGE_BACKEND": "s3", "GLOBAL_S3_BUCKET": f"sibase-{name}", "GLOBAL_S3_ENDPOINT": "http://s3:8333",
                "GLOBAL_S3_PROTOCOL": "http", "GLOBAL_S3_FORCE_PATH_STYLE": "true",
                "AWS_ACCESS_KEY_ID": config["s3_key"], "AWS_SECRET_ACCESS_KEY": config["s3_secret"],
                "FILE_SIZE_LIMIT": "10485760", "ENABLE_IMAGE_TRANSFORMATION": "false", "S3_PROTOCOL_ENABLED": "false",
                "DATABASE_MAX_CONNECTIONS": "5", "STORAGE_PUBLIC_URL": url, "REQUEST_ALLOW_X_FORWARDED_PATH": "true",
            },
        }
        services[f"realtime-{name}"] = {
            "image": IMAGES["realtime"], "depends_on": db_dependency,
            "environment": {
                "PORT": "4000", "DB_HOST": "db", "DB_PORT": "5432", "DB_NAME": name,
                "DB_USER": f"{name}_realtime", "DB_PASSWORD": passwords["realtime"], "DB_AFTER_CONNECT_QUERY": "SET search_path TO _realtime",
                "DB_ENC_KEY": config["db_enc_key"], "API_JWT_SECRET": key, "METRICS_JWT_SECRET": key,
                "SECRET_KEY_BASE": config["secret_key_base"], "ERL_AFLAGS": "+S 2:2 -proto_dist inet_tcp", "DNS_NODES": "''",
                "APP_NAME": f"realtime-{name}", "SELF_HOST_TENANT_NAME": f"realtime-{name}",
                "SLOT_NAME_SUFFIX": name,
                "SEED_SELF_HOST": "true", "RUN_JANITOR": "true", "DB_IP_VERSION": "ipv4", "DB_SSL": "false",
            },
        }
        nginx += [f"    map $arg_apikey $query_key_{name} {{ default 0; '{config['anon_key']}' 1; }}",
                  f"    map $http_apikey $key_{name} {{ default 0; '' $query_key_{name}; '{config['anon_key']}' 1; '{config['service_key']}' 1; }}", f"    server {{ listen {8001 + index};"]
        nginx += [f"        location /storage/v1/object/{kind}/ {{ proxy_pass http://storage_{name}/object/{kind}/; }}" for kind in ["sign", "public"]]
        for route, upstream in [("auth/v1", f"auth_{name}/"), ("rest/v1", f"rest_{name}/"), ("storage/v1", f"storage_{name}/")]:
            nginx += [f"        location /{route}/ {{ if ($key_{name} = 0) {{ return 401; }} proxy_pass http://{upstream}; proxy_set_header Host $host; }}"]
        nginx += [f"        location /realtime/v1/ {{ if ($key_{name} = 0) {{ return 401; }} proxy_pass http://realtime_{name}/socket/; proxy_http_version 1.1; proxy_set_header Host realtime-{name}.localhost; proxy_set_header Upgrade $http_upgrade; proxy_set_header Connection $connection_upgrade; proxy_read_timeout 90s; }}", "        location / { return 404; }", "    }"]
    nginx.append("}")
    write_generated(LOCAL / "nginx.conf", "\n".join(nginx) + "\n")
    services["gateway"] = {"image": IMAGES["gateway"], "ports": [f"127.0.0.1:{port_base}:8001", f"127.0.0.1:{port_base + 1}:8002"],
                           "volumes": [f"{LOCAL}/nginx.conf:/etc/nginx/nginx.conf:ro"],
                           "depends_on": [f"{kind}-{name}" for name in state["projects"] for kind in ["auth", "rest", "storage", "realtime"]]}
    services["test"] = {"image": IMAGES["test"], "profiles": ["tools"], "working_dir": "/work",
                        "volumes": [f"{SOURCE}:/work", f"{LOCAL}:/state", "test_modules:/work/node_modules"],
                        "command": ["node", "verify.mjs"]}
    write_generated(COMPOSE, json.dumps({"name": stack_name, "services": services, "volumes": {name: {} for name in ["pgdata", "objects", "test_modules"]}}, indent=4) + "\n")
    print(f"Prepared {stack_name}; generated secrets stay in local runtime directory {LOCAL.name}.")


def compose(*args):
    return subprocess.run(["docker", "compose", "-p", "sibase-phase0", "-f", str(COMPOSE), *args], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "up", "test", "status", "stop", "logs"])
    parser.add_argument("--service", choices=["db", "s3", "gateway", "auth-alpha", "auth-beta", "rest-alpha", "rest-beta", "storage-alpha", "storage-beta", "realtime-alpha", "realtime-beta"])
    parser.add_argument("--tail", type=int, default=35)
    parser.add_argument("--match", help="Filter sanitized log lines using a regular expression")
    args = parser.parse_args()
    if args.command in ("prepare", "up"):
        prepare()
    if args.command == "up":
        compose("up", "-d", "--build")
        compose("exec", "-T", "gateway", "nginx", "-s", "reload")
    elif args.command == "test":
        compose("run", "--rm", "test", "sh", "-c", "npm ci --ignore-scripts --no-audit --no-fund && node verify.mjs")
    elif args.command == "status":
        compose("ps")
    elif args.command == "stop":
        compose("stop")
    elif args.command == "logs":
        output = subprocess.run(["docker", "compose", "-p", "sibase-phase0", "-f", str(COMPOSE), "logs", "--no-color", "--tail", str(args.tail), *([args.service] if args.service else [])], capture_output=True, text=True, check=True).stdout
        def redact(value):
            nonlocal output
            if isinstance(value, dict):
                for child in value.values():
                    redact(child)
            elif isinstance(value, str):
                output = output.replace(value, "[REDACTED]")
        redact(json.loads((LOCAL / "secrets.json").read_text()))
        if args.match:
            output = "\n".join(line for line in output.splitlines() if re.search(args.match, line, re.IGNORECASE))
        print(output)


if __name__ == "__main__":
    main()
