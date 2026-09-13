"""Post-upstream compatibility migration; no cluster-admin credentials."""

import json
import os
import time
from pathlib import Path

import httpx
import psycopg

projects = json.loads(Path(os.environ["SIBASE_MIGRATION_SETTINGS"]).read_text())
for project in projects:
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        try:
            response = httpx.get(project["health"], timeout=2, trust_env=False)
            if response.is_success:
                break
        except httpx.HTTPError:
            pass
        time.sleep(1)
    else:
        raise SystemExit("Auth migrations did not become ready")
    with psycopg.connect(project["url"], connect_timeout=3) as connection:
        connection.execute(Path("/app/migrations/projects/0001_auth_claims.sql").read_text())
print("Project compatibility migrations applied.")
