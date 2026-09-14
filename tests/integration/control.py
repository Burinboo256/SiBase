"""Real Phase 2 smoke. Uses only the two named pilot projects; keeps their data.

Run in the operator tools container. Private SDK fixtures stay under .local.
"""

import json
import time
from pathlib import Path

import httpx
import psycopg
from sqlalchemy import text

from sibase.control.config import Settings, database, unseal

LOCAL = Path(".local/sibase-control")
ORIGIN = "http://127.0.0.1:58400"


def main():
    checks = []

    def passed(name):
        checks.append(name)
        print("PASS:", name, flush=True)

    client = httpx.Client(base_url="http://api:8000/api/v2", headers={"Origin": ORIGIN}, timeout=15)
    response = client.post("/login", json=json.loads((LOCAL / "initial-owner.json").read_text()))
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]
    client.headers["X-CSRF-Token"] = response.json()["csrf"]
    workspace = next(w for w in client.get("/workspaces").json() if w["name"] == "Internal team")
    base = "/workspaces/" + workspace["id"] + "/projects"
    passed("Platform Auth login and server-side session")
    assert (
        client.post(
            base,
            json={"name": "Denied"},
            headers={"X-CSRF-Token": "invalid", "Idempotency-Key": "must-not-create"},
        ).status_code
        == 403
    )
    passed("CSRF blocks unauthenticated-origin mutations")
    for name in ("Operations", "Inventory"):
        response = client.post(
            base, json={"name": name}, headers={"Idempotency-Key": "phase2-pilot-" + name}
        )
        assert response.status_code == 202
        repeat = client.post(
            base, json={"name": name}, headers={"Idempotency-Key": "phase2-pilot-" + name}
        )
        assert repeat.json()["id"] == response.json()["id"]
    passed("Two API-created projects and idempotent create")

    def wait_for(pid, target):
        for _ in range(120):
            found = next(p for p in client.get(base).json() if p["id"] == pid)
            if found["status"] == target:
                return found
            assert found["status"] != "failed", "Provisioning failed; inspect safe job state"
            time.sleep(2)
        raise AssertionError("Lifecycle readiness timeout")

    projects = [p for p in client.get(base).json() if p["name"] in {"Operations", "Inventory"}]
    for p in projects:
        wait_for(p["id"], "ready")
    passed("Auth, REST, Storage, Realtime and S3 readiness for both projects")
    worker = Settings.model_validate_json((LOCAL / "worker.json").read_text())
    owner = Settings.model_validate_json((LOCAL / "owner.json").read_text())
    engine, _ = database(owner)
    fixtures = []
    gateway = httpx.Client(base_url="http://gateway:8000", timeout=20)
    for p in projects:
        with engine.connect() as db:
            cipher = db.scalar(
                text("SELECT ciphertext FROM project_secrets WHERE project_id=:id"), {"id": p["id"]}
            )
        secret = unseal(worker.vault_key, cipher)
        with psycopg.connect(
            host="data-db",
            dbname=p["ref"],
            user=p["ref"] + "_owner",
            password=secret["passwords"]["owner"],
        ) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS public.phase2_probe (id integer PRIMARY KEY, marker text NOT NULL)"
            )
            db.execute(
                "INSERT INTO public.phase2_probe VALUES (1, %s) ON CONFLICT (id) DO NOTHING",
                (p["ref"],),
            )
            db.execute("GRANT SELECT ON public.phase2_probe TO anon, authenticated, service_role")
            db.execute("NOTIFY pgrst, 'reload schema'")
        path = base + "/" + p["id"] + "/keys"
        issued = client.post(path, json={"role": "anon"}).json()
        raw = issued["key"]
        root = "/p/" + p["ref"]
        for _ in range(10):
            response = gateway.get(root + "/rest/v1/phase2_probe", headers={"apikey": raw})
            if response.status_code == 200:
                break
            time.sleep(1)  # PostgREST reloads its schema cache asynchronously.
        assert response.status_code == 200, (
            f"REST probe returned {response.status_code}: {response.text}"
        )
        assert response.json() == [{"id": 1, "marker": p["ref"]}]
        assert raw not in client.get(path).text
        rotated = client.post(path + "/" + issued["id"] + "/rotate").json()
        assert gateway.get(root + "/rest/v1/", headers={"apikey": raw}).status_code == 401
        assert (
            gateway.get(root + "/rest/v1/", headers={"apikey": rotated["key"]}).status_code == 200
        )
        server = client.post(path, json={"role": "service_role"}).json()
        fixtures.append(
            {
                **p,
                "anon_key": rotated["key"],
                "key_id": rotated["id"],
                "service_key": server["key"],
                "server_key_id": server["id"],
            }
        )
    passed(
        "Separate real databases, one-time keys, atomic rotation and immediate old-key rejection"
    )
    a, b = fixtures
    assert (
        gateway.get("/p/" + b["ref"] + "/rest/v1/", headers={"apikey": a["anon_key"]}).status_code
        == 401
    )
    passed("Cross-project API key rejected")
    p = a
    path = base + "/" + p["id"] + "/lifecycle"
    for action, status in [
        ("suspend", "suspended"),
        ("resume", "ready"),
        ("archive", "archived"),
        ("resume", "ready"),
        ("delete", "deleted"),
        ("restore", "ready"),
    ]:
        assert client.post(path, json={"action": action}).status_code == 202
        if status != "ready":
            assert (
                gateway.get(
                    "/p/" + p["ref"] + "/rest/v1/", headers={"apikey": p["anon_key"]}
                ).status_code
                == 503
            )
        wait_for(p["id"], status)
    assert (
        gateway.get(
            "/p/" + p["ref"] + "/rest/v1/phase2_probe", headers={"apikey": p["anon_key"]}
        ).json()[0]["marker"]
        == p["ref"]
    )
    passed("Suspend/resume, archive/resume, soft-delete/restore retain data and close gateway")
    for role in ("api", "gateway", "worker"):
        config = Settings.model_validate_json((LOCAL / (role + ".json")).read_text())
        engine_role, _ = database(config)
        with engine_role.connect() as db:
            assert not db.scalar(
                text("SELECT rolcreatedb OR rolsuper FROM pg_roles WHERE rolname=current_user")
            )
            if role == "api":
                assert not db.scalar(
                    text("SELECT has_table_privilege(current_user, 'project_secrets', 'SELECT')")
                )
                assert not db.scalar(
                    text("SELECT has_table_privilege(current_user, 'gateway_routes', 'SELECT')")
                )
            if role == "gateway":
                assert not db.scalar(
                    text("SELECT has_table_privilege(current_user, 'projects', 'UPDATE')")
                )
        engine_role.dispose()
    passed("Live PostgreSQL grants separate API, gateway and worker authority")
    assert "ciphertext" not in client.get("/workspaces/" + workspace["id"] + "/audit").text
    output = LOCAL / "sdk-fixture.json"
    output.write_text(json.dumps({"workspace_id": workspace["id"], "projects": fixtures}))
    output.chmod(0o600)
    evidence = Path("docs/evidence/phase2-http.json")
    evidence.write_text(
        json.dumps(
            {
                "checks": checks,
                "projects": [{"name": p["name"], "ref": p["ref"]} for p in projects],
            },
            indent=4,
        )
        + "\n"
    )
    print("Private SDK fixtures saved; no keys printed.")


if __name__ == "__main__":
    main()
