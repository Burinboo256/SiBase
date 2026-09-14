"""Single active local worker, durable queue and crash-safe reconciliation."""

import logging
import os
import secrets
import sys
import time

from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from sibase.control.app_auth import harden, snapshot
from sibase.control.config import Settings, database, seal, unseal
from sibase.control.models import (
    AppAuthConfig,
    AppAuthSnapshot,
    Audit,
    GatewayRoute,
    Job,
    Project,
    ProjectSecret,
    now,
)
from sibase.control.provision import Driver, credentials, tokens

LOCK = 734280192


def reconcile(
    sessions: sessionmaker[Session], driver: Driver, settings: Settings, pid: str
) -> None:
    with sessions.begin() as db:
        project = db.get(Project, pid, with_for_update=True)
        job = db.get(Job, pid)
        assert project and job
        generation, desired, ref, wid = (
            project.generation,
            project.desired,
            project.ref,
            project.workspace_id,
        )
        job.state, job.attempts, job.updated = "running", job.attempts + 1, now()
        project.status = "provisioning" if desired == "ready" else "pending"
        stored = db.get(ProjectSecret, pid)
        if not stored:
            secret = credentials()
            secret["tokens"] = tokens(secret["jwt_secret"])
            stored = ProjectSecret(project_id=pid, ciphertext=seal(settings.vault_key, secret))
            db.add(stored)
        else:
            secret = unseal(settings.vault_key, stored.ciphertext)
        auth_config = db.get(AppAuthConfig, pid)
        if auth_config:
            if (
                not secret.get("app_auth_version")
                or secret.get("signing_epoch", 1) != auth_config.signing_epoch
            ):
                if secret.get("signing_epoch", 1) != auth_config.signing_epoch:
                    secret["jwt_secret"] = secrets.token_hex(32)
                secret["tokens"] = tokens(secret["jwt_secret"])
                secret["app_auth_version"], secret["signing_epoch"] = 1, auth_config.signing_epoch
                stored.ciphertext = seal(settings.vault_key, secret)
            secret["app_auth"] = {"site_url": auth_config.site_url, "jwt_exp": auth_config.jwt_exp}

    def checkpoint(name: str) -> None:
        # Test-only process crash, never exposed by the HTTP API. External effects
        # happen before this hook, so restart tests exercise lost acknowledgements.
        if os.environ.get("SIBASE_CRASH_AFTER") == name:
            os._exit(91)
        with sessions.begin() as db:
            project = db.get(Project, pid, with_for_update=True)
            job = db.get(Job, pid)
            assert project and job
            if project.generation != generation:
                raise InterruptedError("Desired state changed")
            job.checkpoint, job.updated = name, now()

    failure: str | None = None
    try:
        if desired == "ready":
            driver.bootstrap(ref, pid, secret)
            checkpoint("database")
            driver.start(ref, secret, secret["tokens"])
            checkpoint("services")
            driver.await_health(ref, secret, secret["tokens"])
            if auth_config:
                harden(driver, ref)
            checkpoint("healthy")
        else:
            driver.stop(ref)
            checkpoint("stopped")
    except InterruptedError:
        failure = "state_changed"
    except Exception:
        # Upstream exceptions can include credentials; persist a safe code only.
        failure = "provisioning_failed"
    with sessions.begin() as db:
        project = db.get(Project, pid, with_for_update=True)
        job = db.get(Job, pid)
        assert project and job
        if project.generation != generation:
            job.state, job.updated = "pending", now()
            return
        if failure:
            job.error = failure
            job.state = "pending" if job.attempts < 3 else "failed"
            project.status = "pending" if job.state == "pending" else "failed"
        else:
            if desired == "ready":
                route = db.get(GatewayRoute, pid)
                route_data = dict(secret["tokens"])
                if auth_config:
                    route_data["_auth"] = {
                        "secret": secret["jwt_secret"],
                        "issuer": f"{settings.gateway_url}/p/{ref}/auth/v1",
                    }
                cipher = seal(settings.gateway_key, route_data)
                if route:
                    route.ciphertext = cipher
                else:
                    db.add(GatewayRoute(project_id=pid, ciphertext=cipher))
            project.status, job.state, job.error = desired, "succeeded", None
            db.add(Audit(workspace_id=wid, actor="worker", action="project." + desired, target=pid))
        job.updated = now()


def collect_auth(sessions: sessionmaker[Session], driver: Driver, settings: Settings) -> None:
    with sessions() as db:
        candidates = list(
            db.scalars(
                select(Project)
                .join(AppAuthConfig)
                .where(Project.status == "ready", Project.desired == "ready")
            )
        )
    for project in candidates:
        with sessions() as db:
            old = db.get(AppAuthSnapshot, project.id)
            if old and old.collected > now() - 10:
                continue
            stored = db.get(ProjectSecret, project.id)
            if not stored:
                continue
            secret = unseal(settings.vault_key, stored.ciphertext)
        result, error = {}, None
        try:
            result = snapshot(driver, project.ref, secret)
        except Exception:
            error = "auth_snapshot_unavailable"
        with sessions.begin() as db:
            current = db.get(Project, project.id, with_for_update=True)
            if not current or current.generation != project.generation or current.status != "ready":
                continue
            row = db.get(AppAuthSnapshot, project.id)
            if not row:
                row = AppAuthSnapshot(project_id=project.id)
                db.add(row)
            row.collected, row.result, row.error = now(), result, error


def main() -> None:
    settings = Settings.read()
    engine, sessions = database(settings)
    driver = Driver(settings)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    # A dedicated connection owns the lock until the process exits. A restarted
    # worker reclaims running jobs; two workers never reconcile simultaneously.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as lock:
        while not lock.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK}):
            time.sleep(2)
        # A stopped local stack retains metadata. Revalidate previously-ready
        # resources before reopening routes after worker/host restart.
        with sessions.begin() as db:
            for project in db.scalars(
                select(Project)
                .where(Project.status == "ready", Project.desired == "ready")
                .order_by(Project.id)
                .with_for_update()
            ):
                job = db.get(Job, project.id)
                assert job
                project.status, job.state, job.attempts = "pending", "pending", 0
                job.updated = now()
        while True:
            lock.execute(text("SELECT 1"))  # Stop work if lock ownership is lost.
            with sessions() as db:
                pid = db.scalar(
                    select(Job.project_id)
                    .where(Job.state.in_(["pending", "running"]))
                    .order_by(Job.updated)
                    .limit(1)
                )
            if pid:
                reconcile(sessions, driver, settings, pid)
            else:
                collect_auth(sessions, driver, settings)
            time.sleep(2)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("Worker stopped: control-plane or provisioning dependency unavailable", flush=True)
        sys.exit(1)
