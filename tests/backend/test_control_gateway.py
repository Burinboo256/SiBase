import asyncio
import json
from contextlib import asynccontextmanager

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from test_control import project

from sibase.control import gateway
from sibase.control.config import digest, seal
from sibase.control.models import GatewayRoute, Project, ProjectKey, now

pytest_plugins = ["test_control"]


@pytest.fixture
def route(control):
    h = control
    p = project(h)
    with h.sessions.begin() as db:
        db.get(Project, p["id"]).status = "ready"
        db.add(
            GatewayRoute(
                project_id=p["id"],
                ciphertext=seal(
                    h.settings.gateway_key,
                    {"anon": "internal-anon", "service_role": "internal-server"},
                ),
            )
        )
        db.add(
            ProjectKey(
                id="key",
                project_id=p["id"],
                digest=digest("external"),
                prefix="external",
                role="anon",
            )
        )
    h.project = p
    h.route = "/p/" + p["ref"]
    with TestClient(gateway.create_app(h.settings)) as client:
        h.gateway = client
        yield h


def mock_http(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        gateway.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )


def test_gateway_translates_keys_filters_headers_and_preserves_user_jwt(route, monkeypatch):
    h = route
    seen = []

    def upstream(request):
        seen.append(request)
        return httpx.Response(
            200,
            json=[{"ok": True}],
            headers={"content-range": "0-0/1", "set-cookie": "should-not-escape"},
        )

    mock_http(monkeypatch, upstream)
    assert h.gateway.get("/health/live").status_code == 200
    response = h.gateway.get(
        h.route + "/rest/v1/items?apikey=external&select=*",
        headers={"cookie": "sibase_session=secret", "x-forwarded-host": "evil.example"},
    )
    assert response.status_code == 200
    assert response.headers["content-range"] == "0-0/1"
    assert "set-cookie" not in response.headers
    assert seen[0].headers["authorization"] == "Bearer internal-anon"
    assert "cookie" not in seen[0].headers and "x-forwarded-host" not in seen[0].headers
    assert "apikey" not in seen[0].url.params
    h.gateway.post(
        h.route + "/auth/v1/token",
        headers={"apikey": "external", "authorization": "Bearer external"},
        json={},
    )
    assert seen[-1].headers["authorization"] == "Bearer internal-anon"
    h.gateway.get(
        h.route + "/rest/v1/items",
        headers={"apikey": "external", "authorization": "Bearer app-user"},
    )
    assert seen[-1].headers["authorization"] == "Bearer app-user"


@pytest.mark.parametrize(
    "path,status",
    [
        ("/p/invalid/rest/v1/", 404),
        ("/p/p_0000000000000000/rest/v1/", 404),
        ("/bad/v1/", 404),
        ("/realtime/v1/", 404),
        ("/rest/v1/", 401),
    ],
)
def test_gateway_rejects_unknown_routes_and_missing_keys(route, path, status):
    assert (
        route.gateway.get(path if path.startswith("/p/") else route.route + path).status_code
        == status
    )


def test_gateway_revocation_and_suspension_fail_closed(route, monkeypatch):
    h = route
    mock_http(monkeypatch, lambda request: httpx.Response(200))
    assert h.gateway.get(h.route + "/storage/v1/object/public/bucket/file").status_code == 200
    with h.sessions.begin() as db:
        db.get(ProjectKey, "key").revoked = now()
    assert h.gateway.get(h.route + "/rest/v1/", headers={"apikey": "external"}).status_code == 401
    with h.sessions.begin() as db:
        db.get(Project, h.project["id"]).desired = "suspended"
    assert h.gateway.get(h.route + "/storage/v1/object/public/bucket/file").status_code == 503
    with h.sessions.begin() as db:
        db.get(Project, h.project["id"]).desired = "ready"
        db.get(ProjectKey, "key").revoked = None
        db.delete(db.get(GatewayRoute, h.project["id"]))
    assert h.gateway.get(h.route + "/rest/v1/", headers={"apikey": "external"}).status_code == 503


def test_gateway_limits_and_unavailable_upstream(route, monkeypatch):
    h = route
    monkeypatch.setattr(gateway, "LIMIT", 8)
    assert (
        h.gateway.post(
            h.route + "/storage/v1/object/b/file",
            headers={"apikey": "external"},
            content=b"123456789",
        ).status_code
        == 413
    )
    mock_http(monkeypatch, lambda request: httpx.Response(200, content=b"123456789"))
    assert h.gateway.get(h.route + "/rest/v1/", headers={"apikey": "external"}).status_code == 502


def test_gateway_network_error(route, monkeypatch):
    def unavailable(request):
        raise httpx.ConnectError("upstream secret must not escape")

    mock_http(monkeypatch, unavailable)
    response = route.gateway.get(route.route + "/rest/v1/", headers={"apikey": "external"})
    assert response.status_code == 503 and "secret" not in response.text


def test_browser_sdk_cors_and_realtime_token_mapping(route):
    response = route.gateway.options(
        route.route + "/auth/v1/token",
        headers={
            "Origin": route.settings.origins[0],
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "apikey,authorization,x-client-info,x-supabase-api-version",
        },
    )
    assert response.status_code == 200
    packet = '{"event":"phx_join","payload":{"access_token":"external"}}'
    assert "internal" in gateway.realtime_payload(packet, "external", "internal")
    assert gateway.realtime_payload(packet, "another-key", "internal") == packet
    assert gateway.realtime_payload("not-json", "external", "internal") == "not-json"


def test_realtime_claim_frames():
    assert gateway.realtime_auth(
        '[null,"1","realtime:tasks","phx_join",{"access_token":"jwt"}]'
    ) == ("realtime:tasks", "phx_join", "jwt")
    assert gateway.realtime_auth(b"\xff") == ("", "", "")
    assert gateway.realtime_auth('"text"') == ("", "", "")
    with pytest.raises(ValueError):
        gateway.realtime_auth('{"payload":{"access_token":123}}')


@pytest.mark.parametrize("invalid", ["expired", "issuer", "audience", "role"])
def test_phase3_gateway_validates_http_and_socket_claims(route, monkeypatch, invalid):
    h = route
    secret = "s" * 48
    issuer = "https://gateway.example" + h.route + "/auth/v1"
    with h.sessions.begin() as db:
        db.get(GatewayRoute, h.project["id"]).ciphertext = seal(
            h.settings.gateway_key,
            {
                "anon": "internal-anon",
                "service_role": "internal-server",
                "_auth": {"secret": secret, "issuer": issuer},
            },
        )
    claims = {
        "sub": "user",
        "iat": now(),
        "exp": now() + 60,
        "iss": issuer,
        "aud": "authenticated",
        "role": "authenticated",
    }
    mock_http(monkeypatch, lambda request: httpx.Response(200))
    good = jwt.encode(claims, secret, algorithm="HS256")
    assert (
        h.gateway.get(
            h.route + "/rest/v1/items",
            headers={"apikey": "external", "Authorization": "Bearer " + good},
        ).status_code
        == 200
    )
    field, value = {
        "expired": ("exp", now() - 1),
        "issuer": ("iss", "wrong"),
        "audience": ("aud", "wrong"),
        "role": ("role", "service_role"),
    }[invalid]
    claims[field] = value
    bad = jwt.encode(claims, secret, algorithm="HS256")
    assert (
        h.gateway.get(
            h.route + "/rest/v1/items",
            headers={"apikey": "external", "Authorization": "Bearer " + bad},
        ).status_code
        == 401
    )

    @asynccontextmanager
    async def connection(*args, **kwargs):
        class Waiting:
            async def send(self, message):
                pytest.fail("Invalid JWT must not reach Realtime")

            def __aiter__(self):
                return self

            async def __anext__(self):
                await asyncio.Future()

        yield Waiting()

    monkeypatch.setattr(gateway, "connect", connection)
    with h.gateway.websocket_connect(h.route + "/realtime/v1/websocket?apikey=external") as ws:
        ws.send_text(
            json.dumps(
                {"topic": "realtime:test", "event": "phx_join", "payload": {"access_token": bad}}
            )
        )
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()
        assert exc.value.code == 1008


def test_websocket_echo_and_revoke_closes_existing_connection(route, monkeypatch):
    h = route

    @asynccontextmanager
    async def connection(url, **kwargs):
        assert "apikey=internal-anon" in url

        class Echo:
            def __init__(self):
                self.queue = asyncio.Queue()

            async def send(self, message):
                await self.queue.put(message)

            def __aiter__(self):
                return self

            async def __anext__(self):
                return await self.queue.get()

        yield Echo()

    monkeypatch.setattr(gateway, "connect", connection)
    with h.gateway.websocket_connect(h.route + "/realtime/v1/websocket?apikey=external") as ws:
        ws.send_text("hello")
        assert ws.receive_text() == "hello"
        ws.send_bytes(b"bytes")
        assert ws.receive_bytes() == b"bytes"
        with h.sessions.begin() as db:
            db.get(ProjectKey, "key").revoked = now()
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()
        assert exc.value.code == 1008
    with (
        pytest.raises(WebSocketDisconnect),
        h.gateway.websocket_connect(h.route + "/realtime/v1/websocket?apikey=external"),
    ):
        pass
