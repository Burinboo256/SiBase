#!/usr/bin/env python3
"""Isolated Phase 2 local runtime. No volume deletion, commit, push or deployment."""

import argparse
import base64
import hashlib
import json
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STACK = "sibase-control"
LOCAL = ROOT / ".local" / STACK
IMAGES = json.loads((ROOT / "poc/phase0/images.lock.json").read_text())["images"]
IMAGES["postgres_base"] = json.loads((ROOT / "poc/phase0/images.lock.json").read_text())[
    "postgres_base"
]


def write(path: Path, value: str, mounted: bool = False) -> None:
    path.write_text(value)
    path.chmod(0o644 if mounted else 0o600)


def write_json(path: Path, value: object, mounted: bool = False) -> None:
    write(path, json.dumps(value, indent=4) + "\n", mounted)


def prepare() -> None:
    LOCAL.mkdir(parents=True, exist_ok=True)
    LOCAL.chmod(0o700)
    secret_file = LOCAL / "secrets.json"
    if secret_file.exists():
        secret = json.loads(secret_file.read_text())
    else:
        secret = {
            name: secrets.token_hex(32)
            for name in (
                "admin",
                "owner",
                "api",
                "worker",
                "gateway",
                "auth",
                "data",
                "jwt",
                "session",
            )
        }
        secret.update(
            {
                name: base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
                for name in ("vault", "route")
            }
        )
        write_json(secret_file, secret)
    if not (LOCAL / "initial-owner.json").exists():
        write_json(
            LOCAL / "initial-owner.json",
            {"email": "owner@sibase.local", "password": secrets.token_urlsafe(24)},
            True,
        )
    init = [
        "REVOKE ALL ON DATABASE control FROM PUBLIC;",
        "REVOKE CREATE ON SCHEMA public FROM PUBLIC;",
        "REVOKE CONNECT ON DATABASE postgres FROM PUBLIC;",
    ]
    for role in ("owner", "api", "worker", "gateway", "auth"):
        init += [
            f"CREATE ROLE control_{role} LOGIN PASSWORD '{secret[role]}';",
            f"GRANT CONNECT ON DATABASE control TO control_{role};",
            f"GRANT USAGE ON SCHEMA public TO control_{role};",
        ]
    init += [
        "GRANT CREATE ON SCHEMA public TO control_owner;",
        "CREATE SCHEMA auth AUTHORIZATION control_auth;",
        "ALTER ROLE control_auth IN DATABASE control SET search_path = auth, public;",
        "CREATE EXTENSION IF NOT EXISTS pgcrypto;",
        'CREATE EXTENSION IF NOT EXISTS "uuid-ossp";',
    ]
    write(LOCAL / "control-init.sql", "\n".join(init), True)
    write(
        LOCAL / "data-init.sql",
        "CREATE ROLE anon NOLOGIN; CREATE ROLE authenticated NOLOGIN; CREATE ROLE service_role NOLOGIN BYPASSRLS; CREATE ROLE supabase_realtime_admin NOLOGIN NOINHERIT; CREATE ROLE dashboard_user NOLOGIN; REVOKE CONNECT ON DATABASE postgres FROM PUBLIC; REVOKE CONNECT ON DATABASE template1 FROM PUBLIC;",
        True,
    )
    for role in ("admin", "data"):
        write(LOCAL / (role + "-password"), secret[role], True)
    common = {
        "stack": STACK,
        "gateway_url": "http://127.0.0.1:58420",
        "origins": ["http://127.0.0.1:58400", "http://localhost:58400"],
    }
    for role in ("owner", "api", "worker", "gateway"):
        config = {
            **common,
            "database_url": f"postgresql+psycopg://control_{role}:{secret[role]}@control-db:5432/control",
        }
        if role in {"owner", "api"}:
            config.update(auth_jwt_secret=secret["jwt"], session_key=secret["session"])
        if role == "worker":
            config.update(
                vault_key=secret["vault"],
                data_password=secret["data"],
                images={k: IMAGES[k] for k in ("auth", "rest", "storage", "realtime", "s3")},
            )
            smtp_file = LOCAL / "smtp.json"
            if smtp_file.exists():
                smtp = json.loads(smtp_file.read_text())
                if not isinstance(smtp, dict) or set(smtp) - {
                    "smtp_host",
                    "smtp_port",
                    "smtp_user",
                    "smtp_password",
                    "smtp_sender",
                }:
                    raise ValueError("Unsupported SMTP configuration keys")
                config.update(smtp)
        if role in {"worker", "gateway"}:
            config["gateway_key"] = secret["route"]
        write_json(LOCAL / (role + ".json"), config, True)

    def mount(name: str, target: str) -> str:
        return f"{LOCAL / name}:{target}:ro"

    def service(role: str, module: str) -> dict:
        return {
            "image": "sibase-control-api:local",
            "working_dir": "/app",
            "environment": {
                "SIBASE_CONTROL_SETTINGS": "/run/settings.json",
                "PYTHONPATH": "/app/src",
            },
            "volumes": [
                mount(role + ".json", "/run/settings.json"),
                f"{ROOT / 'src/sibase'}:/app/src/sibase:ro",
                f"{ROOT / 'migrations'}:/app/migrations:ro",
            ],
            "command": [
                "uvicorn",
                f"sibase.control.{module}:create_app",
                "--factory",
                "--host",
                "0.0.0.0",
                "--port",
                "8000",
                "--no-access-log",
            ],
            "networks": ["control"] if role == "api" else ["control", "data"],
            "restart": "on-failure:5",
            "init": True,
        }

    services = {
        "control-db": {
            "image": IMAGES["postgres_base"],
            "environment": {"POSTGRES_DB": "control", "POSTGRES_PASSWORD_FILE": "/run/password"},
            "volumes": [
                "control_pg:/var/lib/postgresql/data",
                mount("admin-password", "/run/password"),
                mount("control-init.sql", "/docker-entrypoint-initdb.d/00.sql"),
            ],
            "networks": ["control"],
            "healthcheck": {
                "test": ["CMD-SHELL", "pg_isready -U postgres -d control"],
                "interval": "2s",
                "timeout": "3s",
                "retries": 40,
            },
        },
        "data-db": {
            "image": "sibase-phase0-postgres:17.6-wal2json",
            "build": {"context": str(ROOT / "poc/phase0"), "dockerfile": "postgres.Dockerfile"},
            "environment": {"POSTGRES_PASSWORD_FILE": "/run/password"},
            "command": [
                "postgres",
                "-c",
                "wal_level=logical",
                "-c",
                "max_replication_slots=30",
                "-c",
                "max_wal_senders=30",
                "-c",
                "max_connections=250",
            ],
            "volumes": [
                "data_pg:/var/lib/postgresql/data",
                mount("data-password", "/run/password"),
                mount("data-init.sql", "/docker-entrypoint-initdb.d/00.sql"),
            ],
            "networks": ["data"],
            "healthcheck": {
                "test": ["CMD-SHELL", "pg_isready -U postgres"],
                "interval": "2s",
                "timeout": "3s",
                "retries": 40,
            },
        },
        "platform-auth": {
            "image": IMAGES["auth"],
            "networks": ["control"],
            "environment": {
                "GOTRUE_API_HOST": "0.0.0.0",
                "GOTRUE_API_PORT": "9999",
                "API_EXTERNAL_URL": "http://platform-auth:9999",
                "GOTRUE_DB_DRIVER": "postgres",
                "GOTRUE_DB_DATABASE_URL": f"postgres://control_auth:{secret['auth']}@control-db:5432/control",
                "GOTRUE_DB_NAMESPACE": "auth",
                "GOTRUE_SITE_URL": "http://127.0.0.1:58400",
                "GOTRUE_JWT_SECRET": secret["jwt"],
                "GOTRUE_JWT_ISSUER": "http://platform-auth:9999",
                "GOTRUE_JWT_AUD": "authenticated",
                "GOTRUE_JWT_DEFAULT_GROUP_NAME": "authenticated",
                "GOTRUE_JWT_ADMIN_ROLES": "service_role",
                "GOTRUE_JWT_EXP": "3600",
                "GOTRUE_DISABLE_SIGNUP": "true",
                "GOTRUE_EXTERNAL_EMAIL_ENABLED": "true",
                "GOTRUE_MAILER_AUTOCONFIRM": "true",
                "GOTRUE_RATE_LIMIT_TOKEN_REFRESH": "60",
            },
            "depends_on": {"control-db": {"condition": "service_healthy"}},
            "restart": "on-failure:5",
        },
        "api": service("api", "api"),
        "gateway": service("gateway", "gateway"),
        "worker": service("worker", "worker"),
        "tools": service("owner", "api"),
        "dashboard": {
            "image": IMAGES["test"],
            "working_dir": "/work",
            "volumes": [f"{ROOT / 'src/dashboard'}:/work", "node_modules:/work/node_modules"],
            "environment": {"SIBASE_API_PROXY": "http://api:8000", "VITE_SIBASE_PHASE": "2"},
            "command": ["sh", "-ec", "npm ci --ignore-scripts --no-audit --no-fund && npm run dev"],
            "ports": ["127.0.0.1:58400:5173"],
            "networks": ["control"],
            "init": True,
        },
    }
    services["api"]["ports"] = ["127.0.0.1:58410:8000"]
    services["gateway"]["ports"] = ["127.0.0.1:58420:8000"]
    services["worker"].update(command=["python", "-m", "sibase.control.worker"], user="0")
    services["worker"]["volumes"].append("/var/run/docker.sock:/var/run/docker.sock")
    services["tools"].update(
        profiles=["tools"],
        user="0",
        working_dir="/workspace",
        restart="no",
        environment={
            "SIBASE_CONTROL_SETTINGS": "/run/settings.json",
            "PYTHONPATH": "/workspace/src",
        },
    )
    services["tools"]["volumes"] += [
        f"{ROOT}:/workspace",
        mount("initial-owner.json", "/run/account.json"),
    ]
    services["tools"]["build"] = {
        "context": str(ROOT),
        "dockerfile": "infra/api.Dockerfile",
        "target": "development",
    }
    services["sdk"] = {
        "image": IMAGES["test"],
        "profiles": ["tools"],
        "working_dir": "/workspace/poc/phase0",
        "networks": ["control", "data"],
        "volumes": [f"{ROOT}:/workspace", "sdk_modules:/workspace/poc/phase0/node_modules"],
        "command": [
            "sh",
            "-ec",
            "npm ci --ignore-scripts --no-audit --no-fund && node /workspace/tests/integration/control-sdk.mjs",
        ],
    }
    services["mailpit"] = {
        "image": "axllent/mailpit:v1.31.1@sha256:98b916bd3c8d61f7633a52d3ea2f58d00620cb01ca57ab59edde68c347a95365",
        "networks": ["data"],
        "ports": ["127.0.0.1:58425:8025"],
        "environment": {"MP_DATABASE": "/data/mailpit.db", "MP_MAX_MESSAGES": "500"},
        "volumes": ["mailpit_data:/data"],
        "restart": "on-failure:5",
    }
    for svc in services.values():
        svc["logging"] = {"driver": "json-file", "options": {"max-size": "5m", "max-file": "2"}}
    write_json(
        LOCAL / "compose.json",
        {
            "name": STACK,
            "services": services,
            "networks": {"control": {}, "data": {}},
            "volumes": {
                v: {}
                for v in ("control_pg", "data_pg", "node_modules", "sdk_modules", "mailpit_data")
            },
        },
    )


def compose(*args: str, capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "compose", "-f", str(LOCAL / "compose.json"), *args],
        check=True,
        capture_output=capture,
        text=True,
    )


def wait_auth() -> None:
    for _ in range(40):
        result = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(LOCAL / "compose.json"),
                "exec",
                "-T",
                "api",
                "python",
                "-c",
                "import httpx; httpx.get('http://platform-auth:9999/health', timeout=3).raise_for_status()",
            ],
            capture_output=True,
        )
        if result.returncode == 0:
            return
        time.sleep(2)
    raise RuntimeError("Platform Auth did not become ready")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=[
            "setup",
            "dev",
            "stop",
            "status",
            "test",
            "check",
            "user",
            "integration",
            "recovery",
        ],
    )
    parser.add_argument("--email")
    args = parser.parse_args()
    if args.command in {"setup", "dev"}:
        prepare()
        compose("build", "tools", "data-db")
    if args.command == "dev":
        compose("up", "-d", "--wait", "control-db", "data-db")
        compose("run", "--rm", "tools", "alembic", "-c", "alembic-control.ini", "upgrade", "head")
        compose("up", "-d", "platform-auth", "api", "gateway", "dashboard", "mailpit")
        wait_auth()
        compose(
            "run", "--rm", "tools", "python", "-m", "sibase.control.operator", "/run/account.json"
        )
        compose("up", "-d", "worker")
        print(
            "Phase 2 dashboard: http://127.0.0.1:58400 (credentials: .local/sibase-control/initial-owner.json)"
        )
    elif args.command == "status":
        compose("ps")
        subprocess.run(
            [
                "docker",
                "ps",
                "-a",
                "--filter",
                f"label=sibase.stack={STACK}",
                "--format",
                "{{.Names}} {{.Status}}",
            ],
            check=True,
        )
    elif args.command == "stop":
        compose("stop", "api", "gateway", "worker")
        # Stop managed project services through their owner-checked worker driver.
        compose(
            "run",
            "--rm",
            "worker",
            "python",
            "-c",
            "from sibase.control.config import Settings,database; from sibase.control.models import Project; from sibase.control.provision import Driver; from sqlalchemy import select; s=Settings.read(); _,db=database(s); d=Driver(s); [d.stop(p.ref) for p in db().scalars(select(Project))]",
        )
        compose("stop")
    elif args.command in {"test", "check"}:
        if args.command == "check":
            compose("run", "--rm", "tools", "ruff", "check", ".")
            compose("run", "--rm", "tools", "mypy")
        compose("run", "--rm", "tools", "pytest")
        if args.command == "check":
            for command in ("lint", "format:check", "test", "build"):
                compose("exec", "-T", "dashboard", "npm", "run", command)
    elif args.command == "integration":
        compose("run", "--rm", "tools", "python", "tests/integration/control.py")
        compose("run", "--rm", "tools", "python", "tests/integration/control_rbac.py")
        compose("run", "--rm", "sdk")
    elif args.command == "recovery":
        subprocess.run(
            [sys.executable, str(ROOT / "tests/integration/control_recovery.py")], check=True
        )
    elif args.command == "user":
        if not args.email or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", args.email):
            parser.error("--email is required")
        email = args.email.lower()
        path = LOCAL / ("account-" + hashlib.sha256(email.encode()).hexdigest()[:16] + ".json")
        if not path.exists():
            write_json(path, {"email": email, "password": secrets.token_urlsafe(24)}, True)
        compose(
            "run",
            "--rm",
            "tools",
            "python",
            "-m",
            "sibase.control.operator",
            "/workspace/" + str(path.relative_to(ROOT)),
        )
        print(f"Private credentials: {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
