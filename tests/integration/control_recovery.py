"""Crash the local worker after an external DB step, then verify convergence.

Run on the host. Uses the existing Operations pilot; never deletes volumes.
"""

import http.cookiejar
import json
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / ".local/sibase-control"
COMPOSE = ["docker", "compose", "-f", str(LOCAL / "compose.json")]


def run(*args, check=True):
    return subprocess.run([*COMPOSE, *args], check=check, capture_output=True, text=True)


def main():
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )
    csrf = ""

    def api(path, body=None):
        request = urllib.request.Request(
            "http://127.0.0.1:58410/api/v2" + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={
                "Origin": "http://127.0.0.1:58400",
                "Content-Type": "application/json",
                "X-CSRF-Token": csrf,
            },
        )
        with opener.open(request, timeout=15) as response:
            return json.load(response)

    csrf = api("/login", json.loads((LOCAL / "initial-owner.json").read_text()))["csrf"]
    workspace = next(w for w in api("/workspaces") if w["name"] == "Internal team")
    base = "/workspaces/" + workspace["id"] + "/projects"
    project = next(p for p in api(base) if p["name"] == "Operations")
    assert project["status"] == "ready"

    def resources():
        containers = subprocess.run(
            [
                "docker",
                "ps",
                "-a",
                "--filter",
                "label=sibase.stack=sibase-control",
                "--filter",
                "label=sibase.project=" + project["ref"],
                "--format",
                "{{.ID}} {{.Names}}",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        databases = run(
            "exec",
            "-T",
            "data-db",
            "psql",
            "-U",
            "postgres",
            "-Atc",
            "SELECT oid, datname FROM pg_database WHERE datname LIKE 'p_%' ORDER BY datname",
        ).stdout.splitlines()
        return {"containers": sorted(containers), "databases": databases}

    before = resources()
    try:
        run("stop", "worker")
        api(base + "/" + project["id"] + "/lifecycle", {"action": "resume"})
        crashed = run(
            "run",
            "--rm",
            "-e",
            "SIBASE_CRASH_AFTER=database",
            "worker",
            "python",
            "-m",
            "sibase.control.worker",
            check=False,
        )
        assert crashed.returncode == 91, (
            "Fault-injected process did not exit at the requested checkpoint"
        )
        stranded = next(p for p in api(base) if p["id"] == project["id"])
        assert stranded["job"]["state"] == "running"
        print("PASS: real worker process exited after external database step (91)", flush=True)
    finally:
        run("up", "-d", "worker")
    for _ in range(90):
        recovered = next(p for p in api(base) if p["id"] == project["id"])
        if recovered["status"] == "ready":
            break
        time.sleep(2)
    assert recovered["status"] == "ready"
    assert resources() == before, "Retry duplicated or replaced project resources"
    print("PASS: running job recovered; same database OIDs and service container IDs", flush=True)
    (ROOT / "docs/evidence/phase2-recovery.json").write_text(
        json.dumps(
            {
                "exit_code": 91,
                "checkpoint": "database",
                "recovered_status": "ready",
                "same_database_oids": True,
                "same_container_ids": True,
                "resources": before,
            },
            indent=4,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
