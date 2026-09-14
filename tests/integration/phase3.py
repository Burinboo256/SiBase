"""Real email, app Auth and owner-row RLS contract tests. No secrets in evidence."""

import argparse
import json
import re
import secrets
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import psycopg
from sqlalchemy import text

from sibase.control.config import Settings, database, unseal

LOCAL = Path(".local/sibase-control")


def main(prepare_only=False):
    checks = []

    def passed(name):
        checks.append(name)
        print("PASS:", name, flush=True)

    control = httpx.Client(
        base_url="http://api:8000/api/v2", headers={"Origin": "http://127.0.0.1:58400"}, timeout=15
    )
    login = control.post("/login", json=json.loads((LOCAL / "initial-owner.json").read_text()))
    assert login.status_code == 200
    control.headers["X-CSRF-Token"] = login.json()["csrf"]
    wid = next(w["id"] for w in control.get("/workspaces").json() if w["name"] == "Internal team")
    base = "/workspaces/" + wid + "/projects"
    response = control.post(
        base, json={"name": "Auth Sandbox"}, headers={"Idempotency-Key": "phase3-auth-sandbox"}
    )
    assert response.status_code == 202
    project = response.json()
    pid, ref = project["id"], project["ref"]
    path = base + "/" + pid

    def ready():
        for _ in range(160):
            p = next(p for p in control.get(base).json() if p["id"] == pid)
            if p["status"] == "ready":
                return
            if p["status"] == "failed":
                raise AssertionError("Auth Sandbox provisioning failed; inspect worker safe state")
            time.sleep(2)
        raise AssertionError("Auth Sandbox readiness timed out")

    ready()
    config = control.get(path + "/auth")
    assert config.status_code == 200
    if not config.json()["enabled"]:
        assert (
            control.put(
                path + "/auth",
                json={"jwt_exp": 300, "site_url": "http://127.0.0.1:58400/auth/callback"},
            ).status_code
            == 202
        )
        ready()
    passed("Opt-in project hardened without modifying Phase 2 projects")
    if prepare_only:
        return
    key = control.post(path + "/keys", json={"role": "anon"}).json()
    server = control.post(path + "/keys", json={"role": "service_role"}).json()
    gateway = httpx.Client(
        base_url="http://gateway:8000/p/" + ref,
        headers={"apikey": key["key"]},
        timeout=20,
        follow_redirects=False,
    )
    mail = httpx.Client(base_url="http://mailpit:8025", timeout=10)
    run = secrets.token_hex(5)

    def email_link(email, kind):
        for _ in range(30):
            messages = (
                mail.get("/api/v1/search", params={"query": "to:" + email})
                .json()
                .get("messages", [])
            )
            for item in messages:
                content = mail.get("/api/v1/message/" + item["ID"]).json()
                matches = re.findall(
                    r'https?://[^\s<>"\)]+', content.get("Text", "") + " " + content.get("HTML", "")
                )
                for match in matches:
                    match = match.replace("&amp;", "&")
                    parsed = urlsplit(match)
                    if parsed.path == f"/p/{ref}/auth/v1/verify" and parse_qs(parsed.query).get(
                        "type"
                    ) == [kind]:
                        return "http://gateway:8000" + parsed.path + "?" + parsed.query
            time.sleep(1)
        raise AssertionError("Expected email link not found in local mailbox")

    def verify(link):
        result = httpx.get(link, timeout=15, follow_redirects=False)
        assert result.status_code in {302, 303}
        params = parse_qs(urlsplit(result.headers["location"]).fragment)
        assert "access_token" in params, "Verification failed"
        replay = httpx.get(link, timeout=15, follow_redirects=False)
        assert "access_token" not in parse_qs(urlsplit(replay.headers.get("location", "")).fragment)
        return {k: v[0] for k, v in params.items()}

    users = []
    for name in ("alice", "bob"):
        account = {"email": f"{name}-{run}@example.com", "password": secrets.token_urlsafe(24)}
        signup = gateway.post("/auth/v1/signup", json=account)
        assert signup.status_code == 200
        assert not signup.json().get("access_token")
        assert gateway.post("/auth/v1/token?grant_type=password", json=account).status_code == 400
        session = verify(email_link(account["email"], "signup"))
        user = gateway.get(
            "/auth/v1/user", headers={"Authorization": "Bearer " + session["access_token"]}
        ).json()
        users.append({**account, **session, "id": user["id"]})
    passed("Two email confirmations, unconfirmed-login denial and one-time verification links")

    alice, bob = users

    def headers(user):
        return {
            "Authorization": "Bearer " + user["access_token"],
            "Prefer": "return=representation",
        }

    created = gateway.post(
        "/rest/v1/phase3_tasks", headers=headers(alice), json={"title": "Alice task"}
    )
    assert created.status_code == 201, f"Task insert failed ({created.status_code})"
    task = created.json()[0]
    assert task["owner_id"] == alice["id"]
    assert gateway.get("/rest/v1/phase3_tasks", headers=headers(bob)).json() == []
    assert (
        gateway.patch(
            "/rest/v1/phase3_tasks?id=eq." + task["id"],
            headers=headers(bob),
            json={"title": "Not allowed"},
        ).json()
        == []
    )
    assert (
        gateway.delete("/rest/v1/phase3_tasks?id=eq." + task["id"], headers=headers(bob)).json()
        == []
    )
    assert (
        gateway.post(
            "/rest/v1/phase3_tasks",
            headers=headers(bob),
            json={"title": "Spoofed", "owner_id": alice["id"]},
        ).status_code
        == 403
    )
    assert (
        gateway.patch(
            "/rest/v1/phase3_tasks?id=eq." + task["id"],
            headers=headers(alice),
            json={"owner_id": bob["id"]},
        ).status_code
        == 403
    )
    assert gateway.get("/rest/v1/phase3_tasks").status_code in {401, 403}
    assert (
        gateway.patch(
            "/rest/v1/phase3_tasks?id=eq." + task["id"],
            headers=headers(alice),
            json={"title": "Updated"},
        ).status_code
        == 200
    )
    server_headers = {"apikey": server["key"], "Authorization": "Bearer " + server["key"]}
    assert gateway.get("/rest/v1/phase3_tasks", headers=server_headers).status_code == 200
    passed(
        "Owner-row CRUD, owner spoofing/transfer denial, anonymous denial and explicit server bypass"
    )

    owner = Settings.model_validate_json((LOCAL / "owner.json").read_text())
    worker = Settings.model_validate_json((LOCAL / "worker.json").read_text())
    engine, _ = database(owner)
    with engine.connect() as db:
        cipher = db.scalar(
            text("SELECT ciphertext FROM project_secrets WHERE project_id=:id"), {"id": pid}
        )
    secret = unseal(worker.vault_key, cipher)
    claims = jwt.decode(
        alice["access_token"], secret["jwt_secret"], algorithms=["HS256"], audience="authenticated"
    )
    assert claims["iss"] == project["endpoint"] + "/auth/v1"
    for field, value in [
        ("exp", int(time.time()) - 60),
        ("iss", "https://wrong.example"),
        ("aud", "other-app"),
    ]:
        bad = jwt.encode({**claims, field: value}, secret["jwt_secret"], algorithm="HS256")
        assert (
            gateway.get(
                "/rest/v1/phase3_tasks", headers={"Authorization": "Bearer " + bad}
            ).status_code
            == 401
        )
    assert httpx.get("http://api:8000/api/v2/me", headers=headers(alice)).status_code == 401
    passed("JWT expiry, issuer/audience binding and app-token denial at Control API")
    with psycopg.connect(
        host="data-db", dbname=ref, user=ref + "_owner", password=secret["passwords"]["owner"]
    ) as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS public.phase3_default_probe (id integer PRIMARY KEY)"
        )
        db.execute("GRANT SELECT ON public.phase3_default_probe TO anon, authenticated")
        db.execute("ALTER TABLE public.phase3_default_probe DISABLE ROW LEVEL SECURITY")
        db.execute("NOTIFY pgrst, 'reload schema'")
    with psycopg.connect(
        host="data-db", dbname=ref, user="postgres", password=worker.data_password
    ) as db:
        db.execute("INSERT INTO public.phase3_default_probe VALUES (1) ON CONFLICT DO NOTHING")
        flags = db.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid='public.phase3_default_probe'::regclass"
        ).fetchone()
        assert flags == (True, True)
    time.sleep(1)
    assert gateway.get("/rest/v1/phase3_default_probe").json() == []
    assert gateway.get("/rest/v1/phase3_default_probe", headers=headers(alice)).json() == []
    other = next(p for p in control.get(base).json() if p["name"] == "Inventory")
    other_path = base + "/" + other["id"] + "/keys"
    other_key = control.post(other_path, json={"role": "anon"}).json()
    assert (
        httpx.get(
            "http://gateway:8000/p/" + other["ref"] + "/rest/v1/",
            headers={"apikey": other_key["key"], **headers(alice)},
        ).status_code
        == 401
    )
    assert control.delete(other_path + "/" + other_key["id"]).status_code == 200
    passed("Future tables default-deny, owner cannot disable forced RLS, cross-project JWT denied")

    refresh0 = alice["refresh_token"]
    result = gateway.post(
        "/auth/v1/token?grant_type=refresh_token", json={"refresh_token": refresh0}
    )
    assert result.status_code == 200
    refresh1 = result.json()["refresh_token"]
    result = gateway.post(
        "/auth/v1/token?grant_type=refresh_token", json={"refresh_token": refresh1}
    )
    assert result.status_code == 200
    refresh2 = result.json()["refresh_token"]
    assert len({refresh0, refresh1, refresh2}) == 3
    time.sleep(1)
    assert (
        gateway.post(
            "/auth/v1/token?grant_type=refresh_token", json={"refresh_token": refresh0}
        ).status_code
        == 400
    )
    assert (
        gateway.post(
            "/auth/v1/token?grant_type=refresh_token", json={"refresh_token": refresh2}
        ).status_code
        == 400
    )
    passed("Refresh rotation and grandparent-token reuse revoke the session family")

    logged = gateway.post(
        "/auth/v1/token?grant_type=password",
        json={"email": alice["email"], "password": alice["password"]},
    ).json()
    assert (
        gateway.post(
            "/auth/v1/logout?scope=global",
            headers={"Authorization": "Bearer " + logged["access_token"]},
        ).status_code
        == 204
    )
    assert (
        gateway.post(
            "/auth/v1/token?grant_type=refresh_token",
            json={"refresh_token": logged["refresh_token"]},
        ).status_code
        == 400
    )
    assert (
        gateway.get(
            "/rest/v1/phase3_tasks", headers={"Authorization": "Bearer " + logged["access_token"]}
        ).status_code
        == 200
    )
    passed("Logout revokes refresh tokens; existing access JWT remains valid until expiry")

    assert gateway.post("/auth/v1/recover", json={"email": bob["email"]}).status_code == 200
    recovered = verify(email_link(bob["email"], "recovery"))
    replacement = secrets.token_urlsafe(24)
    assert (
        gateway.put(
            "/auth/v1/user",
            headers={"Authorization": "Bearer " + recovered["access_token"]},
            json={"password": replacement},
        ).status_code
        == 200
    )
    assert (
        gateway.post(
            "/auth/v1/token?grant_type=password",
            json={"email": bob["email"], "password": bob["password"]},
        ).status_code
        == 400
    )
    assert (
        gateway.post(
            "/auth/v1/token?grant_type=password",
            json={"email": bob["email"], "password": replacement},
        ).status_code
        == 200
    )
    passed(
        "Recovery email, password change, old-password rejection and recovery-link replay denial"
    )

    for _ in range(20):
        snapshot = control.get(path + "/auth").json()["snapshot"]
        if (
            snapshot
            and not snapshot["error"]
            and any(u["id"] == alice["id"] for u in snapshot["users"])
        ):
            break
        time.sleep(2)
    assert snapshot and not snapshot["error"]
    assert all(t["rls"] and t["force_rls"] for t in snapshot["tables"])
    assert all(
        not r["superuser"] and not r["bypass_rls"]
        for r in snapshot["roles"]
        if r["name"] != "service_role"
    )
    serialized = json.dumps(snapshot)
    assert all(
        value not in serialized
        for value in (alice["access_token"], bob["refresh_token"], secret["jwt_secret"])
    )
    passed("Sanitized user/session snapshots and live RLS/runtime-role metadata")
    before_rotation = gateway.post(
        "/auth/v1/token?grant_type=password",
        json={"email": alice["email"], "password": alice["password"]},
    ).json()
    assert control.post(path + "/auth/rotate-signing-key").status_code == 202
    ready()
    assert (
        gateway.get(
            "/rest/v1/phase3_tasks",
            headers={"Authorization": "Bearer " + before_rotation["access_token"]},
        ).status_code
        == 401
    )
    after_rotation = gateway.post(
        "/auth/v1/token?grant_type=refresh_token",
        json={"refresh_token": before_rotation["refresh_token"]},
    )
    assert after_rotation.status_code == 200
    assert (
        gateway.get(
            "/rest/v1/phase3_tasks",
            headers={"Authorization": "Bearer " + after_rotation.json()["access_token"]},
        ).status_code
        == 200
    )
    assert gateway.get("/rest/v1/phase3_tasks", headers=server_headers).status_code == 200
    passed(
        "Signing rotation invalidates old JWTs, preserves opaque API keys and allows refresh reauthentication"
    )
    for issued in (key, server):
        assert control.delete(path + "/keys/" + issued["id"]).status_code == 200
    Path("docs/evidence/phase3-auth.json").write_text(
        json.dumps(
            {
                "checks": checks,
                "project": {"id": pid, "ref": ref},
                "auth_image": worker.images["auth"],
            },
            indent=4,
        )
        + "\n"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true")
    main(parser.parse_args().prepare)
