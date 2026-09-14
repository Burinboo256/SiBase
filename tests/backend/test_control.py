from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import jwt
import pytest
from cryptography.fernet import Fernet, InvalidToken
from fastapi.testclient import TestClient
from sqlalchemy import select

from sibase.control.api import COOKIE, create_app, csrf
from sibase.control.config import Settings, database, digest, seal, unseal
from sibase.control.models import (
    Account,
    Audit,
    Base,
    GatewayRoute,
    Job,
    LoginSession,
    Membership,
    Project,
    ProjectKey,
    ProjectSecret,
    Workspace,
    now,
)
from sibase.control.worker import reconcile


@pytest.fixture
def control(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'control.db'}",
        session_key="s" * 32,
        auth_jwt_secret="j" * 32,
        vault_key=Fernet.generate_key().decode(),
        gateway_key=Fernet.generate_key().decode(),
    )
    engine, sessions = database(settings)
    Base.metadata.create_all(engine)
    with sessions.begin() as db:
        for role in ("owner", "admin", "developer", "viewer", "outsider"):
            db.add(Account(id=role, email=role + "@example.com"))
            db.add(LoginSession(digest=digest(role), account_id=role, expires=now() + 3600))
        db.add(Workspace(id="workspace", name="Team"))
        db.flush()
        for role in ("owner", "admin", "developer", "viewer"):
            db.add(Membership(workspace_id="workspace", account_id=role, role=role))
    app = create_app(settings)
    with TestClient(app) as client:

        def login_as(role):
            client.cookies.clear()
            client.cookies.set(COOKIE, role, path="/api/v2")
            client.headers.update(
                {"Origin": settings.origins[0], "X-CSRF-Token": csrf(settings, role)}
            )

        login_as("owner")
        yield SimpleNamespace(
            settings=settings,
            sessions=sessions,
            client=client,
            login_as=login_as,
            base="/api/v2/workspaces/workspace",
            engine=engine,
        )
    app.state.engine.dispose()
    engine.dispose()


def project(h, name="Portal", rid="request-0001"):
    response = h.client.post(
        h.base + "/projects", json={"name": name}, headers={"Idempotency-Key": rid}
    )
    assert response.status_code == 202, response.text
    return response.json()


def test_auth_session_and_csrf(control):
    h = control
    assert h.client.get("/health/live").json() == {"status": "up"}
    assert h.client.get("/api/v2/me").json()["email"] == "owner@example.com"
    assert h.client.get("/api/v2/workspaces").json()[0]["role"] == "owner"
    assert (
        h.client.post(
            "/api/v2/workspaces", json={"name": "Other"}, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert (
        h.client.post(
            "/api/v2/workspaces", json={"name": "Other"}, headers={"X-CSRF-Token": "bad"}
        ).status_code
        == 403
    )
    response = h.client.post("/api/v2/workspaces", json={"name": "Other"})
    assert response.status_code == 201
    assert h.client.post("/api/v2/logout").status_code == 200
    assert h.client.get("/api/v2/me").status_code == 401
    h.login_as("owner")
    assert h.client.get("/api/v2/me").status_code == 401  # revoked server-side
    h.login_as("viewer")
    with h.sessions.begin() as db:
        db.get(Account, "viewer").enabled = False
    assert h.client.get("/api/v2/me").status_code == 401


def test_platform_login_validates_issuer_and_does_not_expose_provider_token(control):
    h = control
    token = jwt.encode(
        {
            "sub": "owner",
            "iat": now(),
            "exp": now() + 300,
            "iss": h.settings.auth_issuer,
            "aud": "authenticated",
        },
        h.settings.auth_jwt_secret,
        algorithm="HS256",
    )
    upstream = MagicMock()
    upstream.__enter__.return_value.post.return_value = httpx.Response(
        200, json={"access_token": token}
    )
    with patch("sibase.control.api.httpx.Client", return_value=upstream):
        response = h.client.post(
            "/api/v2/login", json={"email": "owner@example.com", "password": "test"}
        )
        assert response.status_code == 200
        assert token not in response.text
        assert "HttpOnly" in response.headers["set-cookie"]
        assert "SameSite=strict" in response.headers["set-cookie"]
        assert h.client.get("/api/v2/me").status_code == 200
        upstream.__enter__.return_value.post.return_value = httpx.Response(401)
        assert (
            h.client.post(
                "/api/v2/login", json={"email": "bad@example.com", "password": "bad"}
            ).status_code
            == 401
        )
        upstream.__enter__.return_value.post.return_value = httpx.Response(
            200, json={"access_token": "app-project-token"}
        )
        assert (
            h.client.post(
                "/api/v2/login", json={"email": "bad@example.com", "password": "bad"}
            ).status_code
            == 503
        )


@pytest.mark.parametrize(
    "role,status",
    [("owner", 202), ("admin", 202), ("developer", 403), ("viewer", 403), ("outsider", 404)],
)
def test_project_rbac(control, role, status):
    h = control
    h.login_as(role)
    assert (
        h.client.post(
            h.base + "/projects", json={"name": "App"}, headers={"Idempotency-Key": "request-0001"}
        ).status_code
        == status
    )
    assert h.client.get(h.base + "/projects").status_code == (404 if role == "outsider" else 200)


def test_idempotency_quota_and_workspace_isolation(control):
    h = control
    p = project(h)
    assert project(h)["id"] == p["id"]
    assert (
        h.client.post(
            h.base + "/projects",
            json={"name": "Different"},
            headers={"Idempotency-Key": "request-0001"},
        ).status_code
        == 409
    )
    assert h.client.post(h.base + "/projects", json={"name": "App"}).status_code == 400
    for i in range(4):
        project(h, str(i), f"request-000{i + 2}")
    assert (
        h.client.post(
            h.base + "/projects", json={"name": "six"}, headers={"Idempotency-Key": "request-0006"}
        ).status_code
        == 409
    )
    h.login_as("outsider")
    assert h.client.get(h.base + "/projects/" + p["id"] + "/keys").status_code == 404
    assert h.client.get(h.base + "/audit").status_code == 404


def test_membership_changes_and_owner_protection(control):
    h = control
    assert len(h.client.get(h.base + "/members").json()) == 4
    assert (
        h.client.put(
            h.base + "/members", json={"email": "outsider@example.com", "role": "viewer"}
        ).status_code
        == 200
    )
    assert (
        h.client.put(
            h.base + "/members", json={"email": "viewer@example.com", "role": "developer"}
        ).status_code
        == 200
    )
    assert (
        h.client.put(
            h.base + "/members", json={"email": "missing@example.com", "role": "viewer"}
        ).status_code
        == 404
    )
    assert (
        h.client.put(
            h.base + "/members", json={"email": "owner@example.com", "role": "admin"}
        ).status_code
        == 409
    )
    assert h.client.delete(h.base + "/members/owner").status_code == 409
    assert h.client.delete(h.base + "/members/missing").status_code == 404
    assert h.client.delete(h.base + "/members/outsider").status_code == 200
    assert h.client.post(h.base + "/transfer/owner").status_code == 409
    h.login_as("admin")
    assert h.client.post(h.base + "/transfer/viewer").status_code == 403
    h.login_as("owner")
    assert h.client.post(h.base + "/transfer/viewer").status_code == 200
    with h.sessions() as db:
        assert db.get(Membership, ("workspace", "owner")).role == "admin"
        assert db.get(Membership, ("workspace", "viewer")).role == "owner"


def test_keys_rotation_revoke_and_audit_never_reveal_secrets(control):
    h = control
    p = project(h)
    path = h.base + "/projects/" + p["id"] + "/keys"
    assert h.client.get(h.base + "/projects/missing/keys").status_code == 404
    key = h.client.post(path, json={"role": "service_role"}).json()
    assert key["key"].startswith("sb_service_role_")
    assert key["key"] not in h.client.get(path).text
    rotated = h.client.post(path + "/" + key["id"] + "/rotate").json()
    assert rotated["key"] != key["key"] and rotated["role"] == "service_role"
    assert h.client.post(path + "/" + key["id"] + "/rotate").status_code == 404
    assert h.client.delete(path + "/" + rotated["id"]).status_code == 200
    assert h.client.delete(path + "/missing").status_code == 404
    assert key["key"] not in h.client.get(h.base + "/audit").text
    h.login_as("developer")
    assert h.client.get(path).status_code == 403
    with h.sessions() as db:
        assert db.get(ProjectKey, key["id"]).digest == digest(key["key"])
        assert db.scalar(select(Audit).where(Audit.action == "key.rotated"))


def test_lifecycle_retention_and_generations(control):
    h = control
    p = project(h)
    path = h.base + "/projects/" + p["id"]
    assert h.client.post(path + "/lifecycle", json={"action": "restore"}).status_code == 409
    assert h.client.post(path + "/lifecycle", json={"action": "retry"}).status_code == 409
    for action, desired in [
        ("suspend", "suspended"),
        ("resume", "ready"),
        ("archive", "archived"),
        ("delete", "deleted"),
    ]:
        response = h.client.post(path + "/lifecycle", json={"action": action})
        assert response.status_code == 202
        assert response.json()["desired"] == desired
        assert response.json()["status"] == "pending"
    assert h.client.post(path + "/keys", json={"role": "anon"}).status_code == 409
    assert h.client.post(path + "/lifecycle", json={"action": "resume"}).status_code == 409
    until = h.client.post(path + "/lifecycle", json={"action": "delete"}).json()["restore_until"]
    assert until >= now() + 6 * 86400
    assert h.client.post(path + "/lifecycle", json={"action": "restore"}).status_code == 202
    with h.sessions.begin() as db:
        stored = db.get(Project, p["id"])
        stored.desired, stored.restore_until = "deleted", now() - 1
    assert h.client.post(path + "/lifecycle", json={"action": "restore"}).status_code == 409


def test_worker_retry_reuses_secrets_and_recovers_running_job(control):
    h = control
    p = project(h)
    driver = MagicMock()
    driver.bootstrap.side_effect = RuntimeError("password must not enter audit")
    for _ in range(3):
        reconcile(h.sessions, driver, h.settings, p["id"])
    with h.sessions() as db:
        assert db.get(Job, p["id"]).state == "failed"
        stored = db.get(ProjectSecret, p["id"]).ciphertext
        secret = unseal(h.settings.vault_key, stored)
        assert secret["jwt_secret"] not in stored
        assert "password" not in db.get(Job, p["id"]).error
    assert (
        h.client.post(
            h.base + "/projects/" + p["id"] + "/lifecycle", json={"action": "retry"}
        ).status_code
        == 202
    )
    driver.bootstrap.side_effect = None
    with h.sessions.begin() as db:
        db.get(Job, p["id"]).state = "running"  # previous worker died before acknowledging
    reconcile(h.sessions, driver, h.settings, p["id"])
    reconcile(h.sessions, driver, h.settings, p["id"])
    with h.sessions() as db:
        assert db.get(Project, p["id"]).status == "ready"
        assert db.get(ProjectSecret, p["id"]).ciphertext == stored
        assert (
            unseal(h.settings.gateway_key, db.get(GatewayRoute, p["id"]).ciphertext)
            == secret["tokens"]
        )
    driver.bootstrap.assert_called_with(p["ref"], p["id"], secret)


def test_worker_state_change_never_publishes_stale_route(control):
    h = control
    p = project(h)
    driver = MagicMock()

    def suspend(*args):
        with h.sessions.begin() as db:
            stored = db.get(Project, p["id"])
            stored.generation += 1
            stored.desired = "suspended"

    driver.bootstrap.side_effect = suspend
    reconcile(h.sessions, driver, h.settings, p["id"])
    driver.start.assert_not_called()
    with h.sessions() as db:
        assert db.get(Job, p["id"]).state == "pending"
        assert db.get(GatewayRoute, p["id"]) is None
    reconcile(h.sessions, driver, h.settings, p["id"])
    driver.stop.assert_called_once_with(p["ref"])
    with h.sessions() as db:
        assert db.get(Project, p["id"]).status == "suspended"


def test_configuration_and_separate_vault_keys(control, tmp_path, monkeypatch):
    h = control
    path = tmp_path / "settings.json"
    path.write_text(h.settings.model_dump_json())
    monkeypatch.setenv("SIBASE_CONTROL_SETTINGS", str(path))
    assert Settings.read() == h.settings
    encrypted = seal(h.settings.vault_key, {"secret": "test"})
    with pytest.raises(InvalidToken):
        unseal(h.settings.gateway_key, encrypted)
    with pytest.raises(ValueError):
        create_app(Settings(database_url="sqlite://"))
    assert "test" not in encrypted
