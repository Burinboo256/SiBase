from unittest.mock import MagicMock, patch

import pytest
from test_control import project

from sibase.control.config import unseal
from sibase.control.models import AppAuthSnapshot, Project, ProjectSecret
from sibase.control.worker import collect_auth, reconcile

pytest_plugins = ["test_control"]


def ready(control):
    p = project(control)
    with control.sessions.begin() as db:
        db.get(Project, p["id"]).status = "ready"
    return p, control.base + "/projects/" + p["id"] + "/auth"


@pytest.mark.parametrize(
    "role,expected",
    [("owner", 200), ("admin", 200), ("developer", 403), ("viewer", 403), ("outsider", 404)],
)
def test_auth_metadata_permissions(control, role, expected):
    _, path = ready(control)
    control.login_as(role)
    assert control.client.get(path).status_code == expected
    response = control.client.put(
        path, json={"site_url": "https://app.example.com/callback", "jwt_exp": 900}
    )
    assert response.status_code == (202 if expected == 200 else expected)


def test_auth_configuration_and_signing_epoch(control):
    h = control
    p, path = ready(h)
    assert h.client.get(path).json()["enabled"] is False
    assert h.client.post(path + "/rotate-signing-key").status_code == 409
    for url in (
        "http://evil.example.com",
        "https://user:password@example.com",
        "https://example.com/#fragment",
        "https://example.com/?token=value",
    ):
        assert h.client.put(path, json={"site_url": url}).status_code == 422
    assert (
        h.client.put(
            path, json={"site_url": "http://127.0.0.1:3000/callback", "jwt_exp": 60}
        ).status_code
        == 422
    )
    assert (
        h.client.put(
            path, json={"site_url": "http://127.0.0.1:3000/callback", "jwt_exp": 300}
        ).status_code
        == 202
    )
    assert h.client.get(path).json()["enabled"] is True
    assert h.client.put(path, json={"site_url": "https://example.com"}).status_code == 409
    with h.sessions.begin() as db:
        db.get(Project, p["id"]).status = "ready"
        db.add(AppAuthSnapshot(project_id=p["id"], result={"users": [], "sessions": []}))
    assert h.client.post(path + "/rotate-signing-key").status_code == 202
    result = h.client.get(path).json()
    assert result["settings"]["signing_epoch"] == 2
    assert result["snapshot"]["users"] == []
    assert result["contract"]["email_confirmation"] is True


def test_worker_hardening_rotation_and_snapshot(control):
    h = control
    p, path = ready(h)
    assert h.client.put(path, json={"site_url": "https://example.com"}).status_code == 202
    driver = MagicMock()
    with patch("sibase.control.worker.harden") as harden:
        reconcile(h.sessions, driver, h.settings, p["id"])
        harden.assert_called_once_with(driver, p["ref"])
    with h.sessions() as db:
        first = unseal(h.settings.vault_key, db.get(ProjectSecret, p["id"]).ciphertext)
    assert h.client.post(path + "/rotate-signing-key").status_code == 202
    with patch("sibase.control.worker.harden"):
        reconcile(h.sessions, driver, h.settings, p["id"])
    with h.sessions() as db:
        second = unseal(h.settings.vault_key, db.get(ProjectSecret, p["id"]).ciphertext)
    assert first["jwt_secret"] != second["jwt_secret"]
    assert first["passwords"] == second["passwords"]
    assert first["db_enc_key"] == second["db_enc_key"]
    with patch("sibase.control.worker.snapshot", return_value={"users": []}) as snapshot:
        collect_auth(h.sessions, driver, h.settings)
        collect_auth(h.sessions, driver, h.settings)
        snapshot.assert_called_once()
    with h.sessions.begin() as db:
        db.get(AppAuthSnapshot, p["id"]).collected = 0
    with patch(
        "sibase.control.worker.snapshot",
        side_effect=RuntimeError("secret password must not escape"),
    ):
        collect_auth(h.sessions, driver, h.settings)
    assert h.client.get(path).json()["snapshot"]["error"] == "auth_snapshot_unavailable"


def test_snapshot_adapter_is_read_only_and_sanitized(control):
    from sibase.control.app_auth import snapshot

    driver = MagicMock()
    driver.name.return_value = "auth-fixed"
    db = driver.connect.return_value.__enter__.return_value
    db.execute.return_value.fetchall.return_value = []
    with (
        patch("sibase.control.app_auth.httpx.Client") as http,
        patch("sibase.control.app_auth.psycopg.connect") as connect,
    ):
        http.return_value.__enter__.return_value.get.return_value.json.return_value = {
            "users": [
                {
                    "id": "user",
                    "email": "test@example.com",
                    "password": "SECRET",
                    "refresh_token": "SECRET",
                }
            ]
        }
        connect.return_value.__enter__.return_value.execute.return_value.fetchall.return_value = []
        result = snapshot(
            driver,
            "p_123",
            {"tokens": {"service_role": "internal"}, "passwords": {"auth": "secret"}},
        )
        assert "SECRET" not in str(result)
        assert result["users"][0]["email"] == "test@example.com"
        assert all(
            str(c.args[0]).startswith(("SELECT", "SET TRANSACTION READ ONLY"))
            for c in db.execute.call_args_list
        )
