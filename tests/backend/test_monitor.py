import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import psycopg
import pytest
from pydantic import SecretStr

from sibase.config import ProbeSettings, ProjectSettings, Settings
from sibase.monitor import Monitor


def make_monitor() -> Monitor:
    return Monitor(Settings(platform_url="postgresql://db/platform"))


@pytest.mark.parametrize("code,status", [(200, "up"), (503, "down"), (401, "down")])
def test_http_probe(code, status):
    async def run():
        instance = make_monitor()
        await instance.client.aclose()
        instance.client = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(code)),
        )
        result = await instance.probe(
            ProbeSettings(
                id="auth",
                name="Auth",
                kind="http",
                url="http://auth/health",
                headers={"Authorization": SecretStr("private-header")},
            )
        )
        assert result.status == status
        assert "private-header" not in result.model_dump_json()
        await instance.close()

    asyncio.run(run())


def test_http_failure_does_not_leak_upstream():
    async def run():
        instance = make_monitor()
        await instance.client.aclose()

        def fail(request):
            raise httpx.ConnectError("private-upstream-secret")

        instance.client = httpx.AsyncClient(transport=httpx.MockTransport(fail))
        result = await instance.probe(
            ProbeSettings(
                id="auth",
                name="Auth",
                kind="http",
                url="http://auth/health",
            )
        )
        assert result.status == "down"
        assert "private-upstream" not in result.model_dump_json()
        await instance.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "body,status",
    [
        ({"data": {"healthy": True}}, "up"),
        ({"data": {"healthy": False}}, "down"),
        ({"unexpected": True}, "down"),
    ],
)
def test_realtime_health_checks_json_not_only_http_status(body, status):
    async def run():
        instance = make_monitor()
        await instance.client.aclose()
        instance.client = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body)),
        )
        result = await instance.probe(
            ProbeSettings(
                id="realtime",
                name="Realtime",
                kind="http",
                url="http://realtime/health",
                healthy_json_path=["data", "healthy"],
            )
        )
        assert result.status == status
        await instance.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "row,platform,status",
    [
        ((1,), False, "up"),
        (("0001",), True, "up"),
        (("wrong",), True, "down"),
        (None, False, "down"),
    ],
)
def test_database_probe(row, platform, status):
    async def run():
        instance = make_monitor()
        connection = AsyncMock()
        cursor = AsyncMock()
        cursor.fetchone.return_value = row
        connection.__aenter__.return_value.cursor = lambda: cursor
        cursor.__aenter__.return_value = cursor
        with patch("psycopg.AsyncConnection.connect", AsyncMock(return_value=connection)):
            result = await instance.probe(
                ProbeSettings(
                    id="database",
                    name="DB",
                    kind="postgres",
                    url="postgresql://db/p",
                ),
                platform=platform,
            )
        assert result.status == status
        await instance.close()

    asyncio.run(run())


def test_database_failure_and_project_aggregation():
    async def run():
        instance = make_monitor()
        instance.settings.projects = [
            ProjectSettings(
                ref="alpha",
                name="Alpha",
                endpoint="http://127.0.0.1:58201",
                probes=[
                    ProbeSettings(id="db", name="DB", kind="postgres", url="postgresql://db/p")
                ],
            )
        ]
        with patch(
            "psycopg.AsyncConnection.connect",
            AsyncMock(
                side_effect=psycopg.OperationalError("password=private-value"),
            ),
        ):
            overview = await instance.overview()
        assert overview.platform.status == "down"
        assert overview.projects[0].status == "degraded"
        assert "private-value" not in overview.model_dump_json()
        assert overview.checked_at.tzinfo is not None
        await instance.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "centers,status",
    [
        ([{"Racks": [{"DataNodes": [{"Volumes": 0}]}]}], "up"),
        ([], "down"),
    ],
)
def test_storage_waits_for_volume_server_registration(centers, status):
    async def run():
        instance = make_monitor()
        await instance.client.aclose()

        def respond(request):
            return httpx.Response(200, json={"Topology": {"DataCenters": centers}})

        instance.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        result = await instance.probe(
            ProbeSettings(
                id="storage",
                name="Storage",
                kind="http",
                url="http://storage/status",
                storage_topology_url="http://s3:9333/dir/status",
            )
        )
        assert result.status == status
        await instance.close()

    asyncio.run(run())
