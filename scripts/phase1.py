#!/usr/bin/env python3
"""Local Phase 1 workflow. Never deletes volumes or changes the Phase 0 stack."""

import argparse
import json
import os
import re
import secrets
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import phase0

ROOT = Path(__file__).resolve().parents[1]
PYTHON_IMAGE = "python:3.13.7-slim-bookworm@sha256:adafcc17694d715c905b4c7bebd96907a1fd5cf183395f0ebc4d3428bd22d92d"


def configuration(saved: dict[str, int] | None = None) -> dict[str, int]:
    values = {
        "SIBASE_DASHBOARD_PORT": "58200",
        "SIBASE_API_PORT": "58210",
        "SIBASE_PROJECT_PORT_BASE": "58201",
    }
    if saved:
        values.update({key: str(value) for key, value in saved.items()})
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, separator, value = line.partition("=")
            if not separator or key not in values:
                raise ValueError("Only documented non-secret port settings are accepted in .env")
            values[key] = value.strip()
    result = {key: int(os.environ.get(key, value)) for key, value in values.items()}
    ports = [*result.values(), result["SIBASE_PROJECT_PORT_BASE"] + 1]
    if any(not 1024 <= port <= 65535 for port in ports) or len(set(ports)) != 4:
        raise ValueError("Four unique unprivileged ports are required")
    return result


def runtime_configuration(stack: str, local: Path) -> dict[str, int]:
    """Read the selected stack's persisted bindings, never another shell's defaults."""
    compose = json.loads((local / "compose.json").read_text())
    if compose.get("name") != stack:
        raise ValueError("Runtime configuration does not match the selected stack")

    def published(service: str, container_port: int) -> int:
        for binding in compose["services"][service]["ports"]:
            match = re.fullmatch(r"127\.0\.0\.1:(\d+):" + str(container_port), binding)
            if match:
                return int(match[1])
        raise ValueError("Expected a loopback binding in the selected stack")

    result = {
        "SIBASE_DASHBOARD_PORT": published("dashboard", 5173),
        "SIBASE_API_PORT": published("api", 8000),
        "SIBASE_PROJECT_PORT_BASE": published("gateway", 8001),
    }
    beta_port = published("gateway", 8002)
    ports = [*result.values(), beta_port]
    if (
        beta_port != result["SIBASE_PROJECT_PORT_BASE"] + 1
        or len(set(ports)) != 4
        or any(not 1024 <= port <= 65535 for port in ports)
    ):
        raise ValueError("Invalid port bindings in the selected stack")
    return result


def write_json(path: Path, value: object, *, mounted: bool = False) -> None:
    phase0.write_generated(path, json.dumps(value, indent=4) + "\n")
    if mounted:
        # Parent directory remains 0700; individually mounted config files must be
        # readable by non-root container users (Compose file-secret uid is not portable).
        path.chmod(0o644)


def prepare(stack: str, local: Path, ports: dict[str, int]) -> None:
    phase0.prepare(
        local=local,
        stack_name=stack,
        port_base=ports["SIBASE_PROJECT_PORT_BASE"],
        isolated_roles=True,
        project_template=ROOT / "migrations/projects/bootstrap.sql",
    )
    state = json.loads((local / "secrets.json").read_text())
    platform_file = local / "platform-secrets.json"
    if platform_file.exists():
        platform = json.loads(platform_file.read_text())
    else:
        platform = {role: secrets.token_hex(24) for role in ("admin", "owner", "reader")}
        write_json(platform_file, platform)
    phase0.write_generated(
        local / "platform-init.sql",
        f"""
CREATE ROLE platform_owner LOGIN PASSWORD '{platform["owner"]}';
CREATE ROLE platform_reader LOGIN PASSWORD '{platform["reader"]}';
REVOKE ALL ON DATABASE platform FROM PUBLIC;
REVOKE CONNECT ON DATABASE postgres FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE platform TO platform_owner, platform_reader;
GRANT USAGE, CREATE ON SCHEMA public TO platform_owner;
GRANT USAGE ON SCHEMA public TO platform_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE platform_owner IN SCHEMA public GRANT SELECT ON TABLES TO platform_reader;
""",
    )
    phase0.write_generated(local / "platform-password", platform["admin"])
    api_config = {
        "environment": "local",
        "platform_url": f"postgresql://platform_reader:{platform['reader']}@platform-db:5432/platform",
        "projects": [],
    }
    project_migrations = []
    for index, (name, project) in enumerate(state["projects"].items()):
        project_migrations.append(
            {
                "health": f"http://auth-{name}:9999/health",
                "url": f"postgresql://{name}_auth:{project['passwords']['auth']}@db:5432/{name}",
            }
        )
        api_config["projects"].append(
            {
                "ref": name,
                "name": name.capitalize(),
                "endpoint": f"http://127.0.0.1:{ports['SIBASE_PROJECT_PORT_BASE'] + index}",
                "probes": [
                    {
                        "id": "database",
                        "name": "PostgreSQL",
                        "kind": "postgres",
                        "url": f"postgresql://{name}_monitor:{project['passwords']['monitor']}@db:5432/{name}",
                    },
                    {
                        "id": "auth",
                        "name": "Authentication",
                        "kind": "http",
                        "url": f"http://auth-{name}:9999/health",
                    },
                    {
                        "id": "rest",
                        "name": "REST API",
                        "kind": "http",
                        "url": f"http://rest-{name}:3000/",
                    },
                    {
                        "id": "storage",
                        "name": "Storage",
                        "kind": "http",
                        "url": f"http://storage-{name}:5000/status",
                        "storage_topology_url": "http://s3:9333/dir/status",
                    },
                    {
                        "id": "realtime",
                        "name": "Realtime",
                        "kind": "http",
                        "url": f"http://realtime-{name}:4000/api/tenants/realtime-{name}/health",
                        "headers": {"Authorization": f"Bearer {project['anon_key']}"},
                        "healthy_json_path": ["data", "healthy"],
                    },
                ],
            }
        )
    write_json(local / "api.json", api_config, mounted=True)
    write_json(
        local / "platform-migrations.json",
        {
            "url": f"postgresql+psycopg://platform_owner:{platform['owner']}@platform-db:5432/platform",
        },
        mounted=True,
    )
    write_json(local / "project-migrations.json", project_migrations, mounted=True)
    for name in ("init.sql", "s3.json", "nginx.conf", "platform-init.sql", "platform-password"):
        (local / name).chmod(0o644)

    compose = json.loads((local / "compose.json").read_text())
    services = compose["services"]
    for name, service in services.items():
        service["stop_grace_period"] = "60s"
        service["logging"] = {"driver": "json-file", "options": {"max-size": "5m", "max-file": "2"}}
        if name.startswith(("auth-", "rest-", "storage-", "realtime-")):
            service["restart"] = "on-failure:5"
        env = service.pop("environment", None)
        if env:
            # Upstream services lack a common _FILE contract. Keep values outside
            # the generated compose file, but Docker admins can still inspect env.
            env_file = local / f"{name}.env"
            phase0.write_generated(env_file, "\n".join(f"{k}={v}" for k, v in env.items()) + "\n")
            service["env_file"] = [str(env_file)]
    services["s3"]["init"] = True
    services["s3"]["entrypoint"] = ["weed"]
    services["db"]["image"] = f"{stack}-postgres:17.6-wal2json"
    api_base = {
        "image": f"{stack}-api:dev",
        "stop_grace_period": "30s",
        "pull_policy": "never",
    }
    services["platform-db"] = {
        "image": json.loads((ROOT / "poc/phase0/images.lock.json").read_text())["postgres_base"],
        "environment": {
            "POSTGRES_DB": "platform",
            "POSTGRES_PASSWORD_FILE": "/run/secrets/password",
        },
        "volumes": [
            "platform_data:/var/lib/postgresql/data",
            f"{local}/platform-init.sql:/docker-entrypoint-initdb.d/00-init.sql:ro",
            f"{local}/platform-password:/run/secrets/password:ro",
        ],
        "healthcheck": {
            "test": ["CMD-SHELL", "pg_isready -U postgres -d platform"],
            "interval": "3s",
            "timeout": "3s",
            "retries": 40,
        },
        "stop_grace_period": "30s",
    }
    services["platform-migrate"] = {
        **api_base,
        "command": ["alembic", "upgrade", "head"],
        "environment": {"SIBASE_MIGRATION_SETTINGS": "/run/secrets/migrations.json"},
        "volumes": [f"{local}/platform-migrations.json:/run/secrets/migrations.json:ro"],
        "depends_on": {"platform-db": {"condition": "service_healthy"}},
    }
    services["project-migrate"] = {
        **api_base,
        "command": ["python", "migrations/projects/apply.py"],
        "environment": {"SIBASE_MIGRATION_SETTINGS": "/run/secrets/migrations.json"},
        "volumes": [f"{local}/project-migrations.json:/run/secrets/migrations.json:ro"],
        "depends_on": {
            f"auth-{name}": {"condition": "service_started"} for name in state["projects"]
        },
    }
    services["api"] = {
        **api_base,
        "build": {
            "context": str(ROOT),
            "dockerfile": "infra/api.Dockerfile",
            "target": "development",
            "args": {"PYTHON_IMAGE": PYTHON_IMAGE},
        },
        "ports": [f"127.0.0.1:{ports['SIBASE_API_PORT']}:8000"],
        "volumes": [
            f"{local}/api.json:/run/secrets/api.json:ro",
            f"{ROOT}/src/sibase:/app/src/sibase:ro",
        ],
        "command": [
            "uvicorn",
            "sibase.main:create_app",
            "--factory",
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
            "--no-access-log",
            "--reload",
            "--reload-dir",
            "/app/src",
        ],
        "depends_on": {
            name: {"condition": "service_completed_successfully"}
            for name in ("platform-migrate", "project-migrate")
        },
        "healthcheck": {
            "test": [
                "CMD",
                "python",
                "-c",
                "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=3)",
            ],
            "interval": "5s",
            "timeout": "4s",
            "retries": 20,
        },
    }
    services["dashboard"] = {
        "image": phase0.IMAGES["test"],
        "working_dir": "/app",
        "volumes": [f"{ROOT}/src/dashboard:/app", "dashboard_modules:/app/node_modules"],
        "environment": {"SIBASE_API_PROXY": "http://api:8000"},
        "ports": [f"127.0.0.1:{ports['SIBASE_DASHBOARD_PORT']}:5173"],
        "command": ["sh", "-c", "npm ci --ignore-scripts --no-audit --no-fund && exec npm run dev"],
        "depends_on": {"api": {"condition": "service_healthy"}},
        "healthcheck": {
            "test": [
                "CMD",
                "node",
                "-e",
                "fetch('http://127.0.0.1:5173').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))",
            ],
            "interval": "5s",
            "timeout": "4s",
            "retries": 30,
        },
        "init": True,
        "stop_grace_period": "20s",
    }
    services["api-tools"] = {
        **api_base,
        "profiles": ["tools"],
        "user": "0:0",
        "working_dir": "/workspace",
        "environment": {"PYTHONPATH": "/workspace/src"},
        "volumes": [f"{ROOT}:/workspace"],
        "command": ["pytest"],
    }
    services["web-tools"] = {
        "image": phase0.IMAGES["test"],
        "profiles": ["tools"],
        "working_dir": "/app",
        "volumes": [f"{ROOT}/src/dashboard:/app", "web_test_modules:/app/node_modules"],
        "command": ["sh", "-c", "npm ci --ignore-scripts --no-audit --no-fund && npm test"],
    }
    for name in ("platform_data", "dashboard_modules", "web_test_modules"):
        compose["volumes"][name] = {}
    write_json(local / "compose.json", compose)
    print(f"Phase 1 configured: Dashboard http://127.0.0.1:{ports['SIBASE_DASHBOARD_PORT']}")


def docker(
    stack: str, local: Path, *args: str, capture: bool = False
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "compose", "-p", stack, "-f", str(local / "compose.json"), *args],
        check=True,
        text=True,
        capture_output=capture,
    )


def dashboard_ready(port: int) -> bool:
    base = f"http://127.0.0.1:{port}"
    with urllib.request.urlopen(base + "/", timeout=5) as response:
        if "SiBase" not in response.read().decode():
            return False
    for module in ("main.tsx", "App.tsx", "api.ts"):
        with urllib.request.urlopen(base + "/" + module, timeout=5) as response:
            if "javascript" not in response.headers.get("Content-Type", ""):
                return False
    with urllib.request.urlopen(base + "/api/v1/health", timeout=5) as response:
        return json.load(response)["status"] == "ready"


def wait_ready(api_port: int, dashboard_port: int) -> None:
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{api_port}/api/v1/overview", timeout=10
            ) as response:
                overview = json.load(response)
            if (
                overview["platform"]["status"] == "up"
                and overview["projects"]
                and all(p["status"] == "healthy" for p in overview["projects"])
                and dashboard_ready(dashboard_port)
            ):
                print("Dashboard, Control API and all project probes are ready.")
                return
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, TypeError):
            pass
        time.sleep(2)
    raise RuntimeError("Readiness timed out; use the sanitized logs command")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=[
            "prepare",
            "setup",
            "dev",
            "status",
            "stop",
            "test",
            "integration",
            "lint",
            "format",
            "typecheck",
            "build",
            "logs",
            "smoke",
            "lifecycle",
        ],
    )
    parser.add_argument("--stack", default="sibase-dev")
    args = parser.parse_args()
    if not re.fullmatch(r"sibase-[a-z0-9-]{1,32}", args.stack) or args.stack.startswith(
        "sibase-phase0"
    ):
        parser.error("Use a sibase-<name> stack other than the preserved Phase 0 namespace")
    local = ROOT / ".local" / args.stack
    if args.command in {"prepare", "setup", "dev"}:
        saved = (
            runtime_configuration(args.stack, local) if (local / "compose.json").exists() else None
        )
        ports = configuration(saved)
        prepare(args.stack, local, ports)
    elif not (local / "compose.json").exists():
        parser.error("Run setup first")
    else:
        ports = runtime_configuration(args.stack, local)
    command = args.command
    if command in {"setup", "build"}:
        docker(args.stack, local, "build", "api")
    if command == "dev":
        docker(args.stack, local, "up", "-d", "--build")
        wait_ready(ports["SIBASE_API_PORT"], ports["SIBASE_DASHBOARD_PORT"])
    elif command in {"status", "stop"}:
        docker(args.stack, local, "ps" if command == "status" else "stop")
    elif command == "lifecycle":
        docker(
            args.stack, local, "run", "--rm", "--no-deps", "test", "node", "lifecycle.mjs", "seed"
        )
        stopped = []
        try:
            docker(args.stack, local, "stop")
            output = docker(
                args.stack, local, "ps", "--all", "--format", "json", capture=True
            ).stdout
            stopped = [json.loads(line) for line in output.splitlines() if line.strip()]
            write_json(
                local / "shutdown-observation.json",
                [
                    {"service": item["Service"], "exit_code": item.get("ExitCode")}
                    for item in stopped
                ],
            )
        finally:
            docker(args.stack, local, "up", "-d")
            wait_ready(ports["SIBASE_API_PORT"], ports["SIBASE_DASHBOARD_PORT"])
        docker(
            args.stack, local, "run", "--rm", "--no-deps", "test", "node", "lifecycle.mjs", "verify"
        )
        summary = [
            {"service": item["Service"], "exit_code": item.get("ExitCode")}
            for item in stopped
            if item["Service"] not in {"platform-migrate", "project-migrate"}
        ]
        forced = [item["service"] for item in summary if item["exit_code"] == 137]
        write_json(
            local / "lifecycle-report.json",
            {
                "persistence": "passed",
                "shutdown": "passed" if not forced else "forced",
                "services": summary,
            },
        )
        if forced:
            raise RuntimeError("Forced shutdown observed: " + ", ".join(forced))
        print("Lifecycle passed: no forced kills, database rows and objects retained.")
    elif command == "integration":
        docker(
            args.stack,
            local,
            "run",
            "--rm",
            "--no-deps",
            "-e",
            "POC_RUN_LABEL=phase1",
            "test",
            "sh",
            "-c",
            "npm ci --ignore-scripts --no-audit --no-fund && node verify.mjs",
        )
    elif command in {"test", "lint", "format", "typecheck", "build"}:
        py_commands = {
            "test": "pytest",
            "lint": "ruff check src/sibase tests scripts/phase1.py migrations && ruff format --check src/sibase tests scripts/phase1.py migrations",
            "format": "ruff check --fix src/sibase tests scripts/phase1.py migrations && ruff format src/sibase tests scripts/phase1.py migrations",
            "typecheck": "mypy",
        }
        if command in py_commands:
            docker(
                args.stack,
                local,
                "run",
                "--rm",
                "--no-deps",
                "api-tools",
                "sh",
                "-c",
                py_commands[command],
            )
        web_command = {
            "lint": "lint && npm run format:check",
            "test": "test",
            "typecheck": "typecheck",
            "format": "format",
            "build": "build",
        }[command]
        docker(
            args.stack,
            local,
            "run",
            "--rm",
            "--no-deps",
            "web-tools",
            "sh",
            "-c",
            f"npm ci --ignore-scripts --no-audit --no-fund && npm run {web_command}",
        )
    elif command == "smoke":
        subprocess.run(
            [
                "python3",
                str(ROOT / "tests/integration/smoke.py"),
                "--url",
                f"http://127.0.0.1:{ports['SIBASE_DASHBOARD_PORT']}",
            ],
            check=True,
        )
    elif command == "logs":
        output = docker(
            args.stack, local, "logs", "--no-color", "--tail", "40", capture=True
        ).stdout

        def redact(value: object) -> None:
            nonlocal output
            if isinstance(value, dict):
                for child in value.values():
                    redact(child)
            elif isinstance(value, str):
                output = output.replace(value, "[REDACTED]")

        for name in ("secrets.json", "platform-secrets.json"):
            redact(json.loads((local / name).read_text()))
        output = re.sub(
            r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "[JWT REDACTED]", output
        )
        print(output)


if __name__ == "__main__":
    main()
