import asyncio
import json
import logging
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from sibase.config import Settings
from sibase.main import create_app
from sibase.models import Overview, ServiceStatus
from sibase.monitor import Monitor


def settings() -> Settings:
    return Settings(
        environment="test", platform_url=SecretStr("postgresql://private-password@db/p")
    )


def monitor(status: str = "up") -> Monitor:
    result = ServiceStatus(
        id="platform", name="Platform", status=status, latency_ms=1, detail="safe"
    )
    fake = AsyncMock(spec=Monitor)
    fake.platform.return_value = result
    fake.overview.return_value = Overview(
        environment="test", checked_at=datetime.now(UTC), platform=result, projects=[]
    )
    return fake


def test_live_ready_overview_and_no_mutation():
    fake = monitor()
    with TestClient(create_app(settings(), fake)) as client:
        assert client.get("/health/live").json()["status"] == "ok"
        assert client.get("/health/ready").json() == {"status": "ready"}
        response = client.get("/api/v1/overview")
        assert response.json()["projects"] == []
        assert response.json()["phase"] == 1
        assert response.headers["cache-control"] == "no-store"
        assert "private-password" not in response.text
        assert client.post("/api/v1/overview", json={"name": "new"}).status_code == 405
        assert client.get("/api/openapi.json").status_code == 200
        assert client.get("/api/docs").status_code == 200
    fake.close.assert_awaited_once()


def test_unready_database_is_503_but_liveness_still_works():
    with TestClient(create_app(settings(), monitor("down"))) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 503
        assert client.get("/api/v1/health").json() == {"status": "not_ready"}
        assert client.get("/api/v1/overview").json()["platform"]["status"] == "down"


def test_host_boundary_and_unknown_paths():
    with TestClient(create_app(settings(), monitor())) as client:
        assert client.get("/health/live", headers={"Host": "attacker.example"}).status_code == 400
        assert client.get("/api/v1/projects").status_code == 404


def test_request_id_and_logs_do_not_include_secrets(capsys):
    request_id = "12345678-1234-1234-1234-123456789012"
    with TestClient(create_app(settings(), monitor())) as client:
        response = client.get(
            "/api/v1/overview?token=query-secret",
            headers={"Authorization": "Bearer bearer-secret", "X-Request-ID": request_id},
        )
        assert response.headers["x-request-id"] == request_id
        invalid = client.get("/secret-path", headers={"X-Request-ID": "secret-request-id"})
        assert invalid.headers["x-request-id"] != "secret-request-id"
    logs = capsys.readouterr().err
    for secret in ["query-secret", "bearer-secret", "secret-path", "secret-request-id"]:
        assert secret not in logs
    rows = [json.loads(line) for line in logs.splitlines()]
    assert rows[0]["request_id"] == request_id
    assert rows[-1]["route"] == "[unmatched]"
    logging.getLogger("sibase.requests").handlers.clear()


def test_config_file_and_secret_repr(tmp_path, monkeypatch):
    config = tmp_path / "api.json"
    config.write_text('{"platform_url":"postgresql://secret-config@db/p","environment":"test"}')
    monkeypatch.setenv("SIBASE_SETTINGS", str(config))
    loaded = Settings.load()
    assert "secret-config" not in repr(loaded)
    with pytest.raises(ValidationError):
        Settings(environment="production", platform_url="postgresql://db/p")
    with TestClient(create_app()) as client:
        assert client.get("/health/live").status_code == 200


def test_middleware_passthrough_for_lifespan():
    from sibase.logging import RequestLogMiddleware

    app = AsyncMock()
    asyncio.run(RequestLogMiddleware(app)({"type": "lifespan"}, AsyncMock(), AsyncMock()))
    app.assert_awaited_once()


def test_unexpected_exception_is_sanitized(capsys):
    fake = monitor()
    fake.overview.side_effect = RuntimeError("postgresql://secret-exception@db")
    with TestClient(create_app(settings(), fake)) as client:
        response = client.get("/api/v1/overview")
        assert response.status_code == 500
        assert response.json() == {"detail": "Internal server error"}
        assert response.headers["x-request-id"]
    assert "secret-exception" not in capsys.readouterr().err
    logging.getLogger("sibase.requests").handlers.clear()
