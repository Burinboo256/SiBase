"""Dynamic data-plane router with per-request key/lifecycle checks."""

import asyncio
import json
import re
from typing import Any
from urllib.parse import quote, urlencode

import httpx
import jwt
from fastapi import FastAPI, HTTPException, Request, Response, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool
from starlette.websockets import WebSocketDisconnect
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from sibase.control.config import Settings, database, digest, unseal
from sibase.control.models import GatewayRoute, Project, ProjectKey
from sibase.logging import RequestLogMiddleware

PORTS = {"auth": 9999, "rest": 3000, "storage": 5000, "realtime": 4000}
HEADERS = {
    "authorization",
    "content-type",
    "accept",
    "prefer",
    "range",
    "range-unit",
    "content-range",
    "if-match",
    "if-none-match",
    "x-client-info",
    "x-supabase-api-version",
    "x-upsert",
    "cache-control",
}
RESPONSE_HEADERS = {
    "content-type",
    "content-range",
    "range-unit",
    "content-disposition",
    "etag",
    "last-modified",
    "location",
}
LIMIT = 10 * 1024 * 1024


def realtime_auth(message: str | bytes) -> tuple[str, str, str]:
    """Read JWT-bearing Phoenix JSON frames, including the v2 array format."""
    try:
        packet = json.loads(message)
    except (ValueError, UnicodeDecodeError):
        return "", "", ""
    if isinstance(packet, list) and len(packet) == 5:
        packet = dict(zip(("join_ref", "ref", "topic", "event", "payload"), packet, strict=True))
    if not isinstance(packet, dict):
        return "", "", ""
    payload = packet.get("payload")
    token = payload.get("access_token", "") if isinstance(payload, dict) else ""
    topic, event = packet.get("topic", ""), packet.get("event", "")
    if not all(isinstance(value, str) for value in (topic, event, token)):
        raise ValueError("Invalid Realtime authentication frame")
    return topic, event, token


def realtime_payload(message: str, raw: str, token: str) -> str:
    """Translate only the SDK's anonymous key; never replace an app-user JWT."""
    try:
        packet = json.loads(message)
    except ValueError:
        return message
    payload = (
        packet.get("payload")
        if isinstance(packet, dict)
        else packet[4]
        if isinstance(packet, list) and len(packet) == 5
        else None
    )
    if isinstance(payload, dict) and payload.get("access_token") == raw:
        payload["access_token"] = token
        return json.dumps(packet)
    return message


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.read()
    _, sessions = database(settings)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(RequestLogMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"],
        allow_headers=[*HEADERS, "apikey"],
        expose_headers=list(RESPONSE_HEADERS),
    )

    def resolve(ref: str, raw: str, public: bool = False, user_token: str = "") -> tuple[str, str]:
        if not re.fullmatch(r"p_[0-9a-f]{16}", ref):
            raise HTTPException(404, "Project not found")
        with sessions() as db:
            project = db.scalar(select(Project).where(Project.ref == ref))
            if not project:
                raise HTTPException(404, "Project not found")
            if project.status != "ready" or project.desired != "ready":
                raise HTTPException(503, "Project unavailable")
            key = (
                db.scalar(
                    select(ProjectKey).where(
                        ProjectKey.project_id == project.id,
                        ProjectKey.digest == digest(raw),
                        ProjectKey.revoked.is_(None),
                    )
                )
                if raw
                else None
            )
            if not public and not key:
                raise HTTPException(401, "Invalid project API key")
            route = db.get(GatewayRoute, project.id)
            if not route:
                raise HTTPException(503, "Project route unavailable")
            role = key.role if key else "anon"
            route_data = unseal(settings.gateway_key, route.ciphertext)
            contract = route_data.get("_auth")
            if contract and user_token and user_token != raw:
                try:
                    claims = jwt.decode(
                        user_token,
                        contract["secret"],
                        algorithms=["HS256"],
                        issuer=contract["issuer"],
                        audience="authenticated",
                        options={"require": ["exp", "iat", "sub", "iss", "aud"]},
                    )
                    if claims.get("role") != "authenticated":
                        raise jwt.InvalidTokenError("Unexpected app role")
                except jwt.PyJWTError:
                    raise HTTPException(401, "Invalid application access token") from None
            token: str = route_data[role]
            return role, token

    @app.get("/health/live")
    def health() -> dict[str, str]:
        return {"status": "up"}

    @app.api_route(
        "/p/{ref}/{kind}/v1/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"]
    )
    async def proxy(ref: str, kind: str, path: str, request: Request) -> Response:
        if kind not in PORTS or kind == "realtime" or ".." in path.split("/"):
            raise HTTPException(404, "Route not found")
        public = (
            kind == "storage"
            and request.method in {"GET", "HEAD"}
            and path.startswith(("object/sign/", "object/public/"))
        )
        public = public or (kind == "auth" and request.method == "GET" and path == "verify")
        raw = request.headers.get("apikey") or request.query_params.get("apikey", "")
        authorization = request.headers.get("authorization", "")
        user_token = authorization[7:] if authorization.lower().startswith("bearer ") else ""
        _, token = await run_in_threadpool(resolve, ref, raw, public, user_token)
        headers = {k: v for k, v in request.headers.items() if k in HEADERS}
        headers["apikey"] = token
        if not headers.get("authorization") or headers["authorization"] == "Bearer " + raw:
            headers["authorization"] = "Bearer " + token
        # No cookies, forwarded host or arbitrary upstream URL can cross this boundary.
        query = [(k, v) for k, v in request.query_params.multi_items() if k != "apikey"]
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > LIMIT:
                raise HTTPException(413, "Local gateway limit: 10 MiB")
        upstream = f"http://{settings.stack}-{kind}-{ref}:{PORTS[kind]}/{quote(path, safe='/')}"
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                async with client.stream(
                    request.method,
                    upstream,
                    params=urlencode(query),
                    headers=headers,
                    content=bytes(body),
                ) as response:
                    result = bytearray()
                    async for chunk in response.aiter_bytes():
                        result.extend(chunk)
                        if len(result) > LIMIT:
                            raise HTTPException(
                                502, "Upstream response exceeds local gateway limit"
                            )
                    safe = {k: v for k, v in response.headers.items() if k in RESPONSE_HEADERS}
                    safe["referrer-policy"] = "no-referrer"
                    return Response(bytes(result), status_code=response.status_code, headers=safe)
        except httpx.HTTPError as exc:
            raise HTTPException(503, "Project service unavailable") from exc

    @app.websocket("/p/{ref}/realtime/v1/websocket")
    async def realtime(ref: str, websocket: WebSocket) -> None:
        raw = websocket.headers.get("apikey") or websocket.query_params.get("apikey", "")
        initial_token = websocket.query_params.get("access_token", "")
        try:
            _, token = await run_in_threadpool(resolve, ref, raw, False, initial_token)
        except HTTPException:
            await websocket.close(code=1008)
            return
        query = [(k, v) for k, v in websocket.query_params.multi_items() if k != "apikey"]
        query.append(("apikey", token))
        hostname = f"{settings.stack}-realtime-{ref}"
        url = f"ws://{hostname}.localhost:4000/socket/websocket?{urlencode(query)}"
        await websocket.accept()
        tasks: list[asyncio.Task[Any]] = []
        active_tokens = {"": initial_token} if initial_token else {}
        try:
            async with connect(
                url,
                host=hostname,
                port=4000,
                proxy=None,
                open_timeout=10,
                max_size=LIMIT,
            ) as upstream:

                async def incoming() -> None:
                    while True:
                        message = await websocket.receive()
                        if message["type"] == "websocket.disconnect":
                            return
                        payload: str | bytes = (
                            message["text"] if message.get("text") is not None else message["bytes"]
                        )
                        topic, event, access_token = realtime_auth(payload)
                        if access_token:
                            await run_in_threadpool(resolve, ref, raw, False, access_token)
                            if len(active_tokens) >= 100 and topic not in active_tokens:
                                raise ValueError("Local gateway limit: 100 channel tokens")
                            active_tokens[topic] = access_token
                        if event == "phx_leave":
                            active_tokens.pop(topic, None)
                        if isinstance(payload, str):
                            payload = realtime_payload(payload, raw, token)
                        await upstream.send(payload)

                async def outgoing() -> None:
                    async for message in upstream:
                        if isinstance(message, str):
                            await websocket.send_text(message)
                        else:
                            await websocket.send_bytes(message)

                async def watchdog() -> None:
                    while True:
                        await asyncio.sleep(1)
                        await run_in_threadpool(resolve, ref, raw)
                        for access_token in set(active_tokens.values()):
                            await run_in_threadpool(resolve, ref, raw, False, access_token)

                tasks = [asyncio.create_task(fn()) for fn in (incoming, outgoing, watchdog)]
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
        except (HTTPException, WebSocketDisconnect, ConnectionClosed, OSError, ValueError):
            pass
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            try:
                await websocket.close(code=1008)
            except RuntimeError:
                pass

    return app
