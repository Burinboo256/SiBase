"""Real platform logins and membership enforcement using local fixture accounts."""

import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

import httpx

LOCAL = Path(".local/sibase-control")


def login(account):
    client = httpx.Client(
        base_url="http://api:8000/api/v2", headers={"Origin": "http://127.0.0.1:58400"}, timeout=15
    )
    result = client.post("/login", json=account)
    assert result.status_code == 200
    client.headers["X-CSRF-Token"] = result.json()["csrf"]
    return client


def main():
    owner = login(json.loads((LOCAL / "initial-owner.json").read_text()))
    wid = next(w["id"] for w in owner.get("/workspaces").json() if w["name"] == "Internal team")
    base = "/workspaces/" + wid
    project = owner.get(base + "/projects").json()[0]
    checks = []
    for role in ("viewer", "developer", "admin", "outsider"):
        path = LOCAL / f"fixture-{role}.json"
        if not path.exists():
            # O_EXCL prevents accidentally replacing any existing credential file.
            with os.fdopen(
                os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w"
            ) as output:
                json.dump(
                    {"email": f"phase2-{role}@sibase.local", "password": secrets.token_urlsafe(24)},
                    output,
                )
        account = json.loads(path.read_text())
        subprocess.run([sys.executable, "-m", "sibase.control.operator", str(path)], check=True)
        if role != "outsider":
            assert (
                owner.put(
                    base + "/members", json={"email": account["email"], "role": role}
                ).status_code
                == 200
            )
        client = login(account)
        assert client.get(base + "/projects").status_code == (404 if role == "outsider" else 200)
        keys = base + "/projects/" + project["id"] + "/keys"
        if role == "admin":
            key = client.post(keys, json={"role": "anon"})
            assert key.status_code == 201
            assert client.delete(keys + "/" + key.json()["id"]).status_code == 200
        else:
            expected = 404 if role == "outsider" else 403
            assert (
                client.post(
                    base + "/projects",
                    json={"name": "Must not exist"},
                    headers={"Idempotency-Key": "rbac-must-not-create"},
                ).status_code
                == expected
            )
            assert client.post(keys, json={"role": "service_role"}).status_code == expected
            assert (
                client.post(
                    base + "/projects/" + project["id"] + "/lifecycle", json={"action": "delete"}
                ).status_code
                == expected
            )
        if role == "viewer":
            aid = client.get("/me").json()["id"]
            assert owner.delete(base + "/members/" + aid).status_code == 200
            assert client.get(base + "/projects").status_code == 404  # same live session
            assert (
                owner.put(
                    base + "/members", json={"email": account["email"], "role": role}
                ).status_code
                == 200
            )
            checks.append("Membership removal takes effect on an existing authenticated session")
        checks.append(role + ": real platform login and expected management permissions")
        client.post("/logout")
        client.close()
        print("PASS:", checks[-1], flush=True)
    (Path("docs/evidence") / "phase2-rbac.json").write_text(
        json.dumps({"checks": checks}, indent=4) + "\n"
    )


if __name__ == "__main__":
    main()
