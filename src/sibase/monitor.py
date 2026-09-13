"""Read-only, bounded probes against operator-configured destinations."""

import asyncio
from datetime import UTC, datetime
from time import perf_counter

import httpx
import psycopg

from sibase.config import ProbeSettings, Settings
from sibase.models import Overview, ProjectStatus, ServiceStatus


class Monitor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = httpx.AsyncClient(timeout=2.0, trust_env=False)

    async def close(self) -> None:
        await self.client.aclose()

    async def probe(self, spec: ProbeSettings, *, platform: bool = False) -> ServiceStatus:
        started = perf_counter()
        healthy = False
        try:
            async with asyncio.timeout(4):
                if spec.kind == "postgres":
                    async with await psycopg.AsyncConnection.connect(
                        spec.url.get_secret_value(), connect_timeout=2
                    ) as connection:
                        async with connection.cursor() as cursor:
                            query = (
                                "SELECT version_num FROM alembic_version"
                                if platform
                                else "SELECT 1"
                            )
                            await cursor.execute(query)
                            row = await cursor.fetchone()
                            healthy = bool(row and (row[0] == "0001" if platform else True))
                else:
                    response = await self.client.get(
                        spec.url.get_secret_value(),
                        headers={k: v.get_secret_value() for k, v in spec.headers.items()},
                    )
                    healthy = response.is_success
                    if healthy and spec.healthy_json_path:
                        value = response.json()
                        for key in spec.healthy_json_path:
                            value = value[key]
                        healthy = value is True
                    if healthy and spec.storage_topology_url:
                        topology = await self.client.get(
                            spec.storage_topology_url.get_secret_value()
                        )
                        topology.raise_for_status()
                        centers = topology.json()["Topology"]["DataCenters"]
                        healthy = any(
                            rack["DataNodes"] for center in centers for rack in center["Racks"]
                        )
        except (
            httpx.HTTPError,
            psycopg.Error,
            TimeoutError,
            OSError,
            ValueError,
            KeyError,
            TypeError,
        ):
            # Never return/log upstream URLs, SQL errors, credentials, or response bodies.
            healthy = False
        return ServiceStatus(
            id=spec.id,
            name=spec.name,
            status="up" if healthy else "down",
            latency_ms=round((perf_counter() - started) * 1000),
            detail="Probe succeeded" if healthy else "Unavailable or not ready",
        )

    async def platform(self) -> ServiceStatus:
        return await self.probe(
            ProbeSettings(
                id="platform",
                name="Platform database",
                kind="postgres",
                url=self.settings.platform_url,
            ),
            platform=True,
        )

    async def overview(self) -> Overview:
        async def project(index: int) -> ProjectStatus:
            settings = self.settings.projects[index]
            services = list(await asyncio.gather(*(self.probe(p) for p in settings.probes)))
            return ProjectStatus(
                ref=settings.ref,
                name=settings.name,
                endpoint=settings.endpoint,
                status="healthy" if all(s.status == "up" for s in services) else "degraded",
                services=services,
            )

        platform = await self.platform()
        projects = await asyncio.gather(*(project(i) for i in range(len(self.settings.projects))))
        return Overview(
            environment=self.settings.environment,
            checked_at=datetime.now(UTC),
            platform=platform,
            projects=list(projects),
        )
