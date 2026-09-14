"""Worker-only Auth metadata reads and project RLS installation."""

from pathlib import Path
from typing import Any

import httpx
import psycopg
from psycopg.rows import dict_row

from sibase.control.provision import Driver


def harden(driver: Driver, ref: str) -> None:
    driver.name(ref, "db")
    with driver.connect(ref) as connection:
        connection.execute(
            Path("migrations/projects/0002_app_rls.sql").read_text().replace("@PROJECT@", ref)
        )


def snapshot(driver: Driver, ref: str, secret: dict[str, Any]) -> dict[str, Any]:
    with httpx.Client(timeout=10) as client:
        response = client.get(
            f"http://{driver.name(ref, 'auth')}:9999/admin/users",
            params={"page": 1, "per_page": 100},
            headers={"Authorization": "Bearer " + secret["tokens"]["service_role"]},
        )
        response.raise_for_status()
        users = [
            {
                k: user.get(k)
                for k in ("id", "email", "created_at", "last_sign_in_at", "email_confirmed_at")
            }
            for user in response.json().get("users", [])
        ]
    # Auth has no public session-list API in the pinned release. This adapter is
    # read-only and version-specific; never modify upstream Auth tables here.
    with psycopg.connect(
        host="data-db",
        dbname=ref,
        user=ref + "_auth",
        password=secret["passwords"]["auth"],
        connect_timeout=5,
        row_factory=dict_row,
    ) as connection:
        connection.execute("SET TRANSACTION READ ONLY")
        sessions = connection.execute(
            "SELECT id::text, user_id::text, created_at::text, updated_at::text, not_after::text FROM auth.sessions ORDER BY created_at DESC LIMIT 100"
        ).fetchall()
    with driver.connect(ref, row_factory=dict_row) as connection:
        connection.execute("SET TRANSACTION READ ONLY")
        tables = connection.execute(
            "SELECT c.relname AS name, c.relrowsecurity AS rls, c.relforcerowsecurity AS force_rls FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind IN ('r','p') ORDER BY c.relname LIMIT 100"
        ).fetchall()
        policies = connection.execute(
            "SELECT tablename, policyname, cmd, qual, with_check FROM pg_policies WHERE schemaname='public' ORDER BY tablename, policyname LIMIT 100"
        ).fetchall()
        roles = connection.execute(
            "SELECT rolname AS name, rolsuper AS superuser, rolbypassrls AS bypass_rls FROM pg_roles WHERE rolname IN ('anon','authenticated','service_role',%s)",
            (ref + "_rest",),
        ).fetchall()
    return {
        "users": users,
        "sessions": sessions,
        "tables": tables,
        "policies": policies,
        "roles": roles,
        "limit": 100,
    }
