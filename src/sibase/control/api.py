"""Cookie-authenticated management API. No Docker socket or project vault key."""

import hashlib
import hmac
import secrets
from collections.abc import Iterator
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

import httpx
import jwt
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from sibase.control.config import Settings, database, digest
from sibase.control.models import (
    Account,
    AppAuthConfig,
    AppAuthSnapshot,
    Audit,
    Job,
    LoginSession,
    Membership,
    Project,
    ProjectKey,
    Workspace,
    identifier,
    now,
)
from sibase.logging import RequestLogMiddleware

COOKIE = "sibase_session"
MANAGERS = {"owner", "admin"}


class Login(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class Named(BaseModel):
    name: str = Field(min_length=1, max_length=80, pattern=r".*\S.*")


class MemberInput(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    role: Literal["admin", "developer", "viewer"]


class KeyInput(BaseModel):
    role: Literal["anon", "service_role"]


class LifecycleInput(BaseModel):
    action: Literal["suspend", "resume", "archive", "delete", "restore", "retry"]


class AppAuthInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    jwt_exp: int = Field(default=900, ge=300, le=3600)
    site_url: str = Field(max_length=512)

    @field_validator("site_url")
    @classmethod
    def valid_site(cls, value: str) -> str:
        url = urlsplit(value)
        if not url.hostname or url.username or url.password or url.fragment or url.query:
            raise ValueError(
                "Use an absolute application URL without credentials, query or fragment"
            )
        if url.scheme != "https" and not (
            url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1"}
        ):
            raise ValueError("HTTPS is required except for loopback development")
        return value.rstrip("/")


def csrf(settings: Settings, sid: str) -> str:
    return hmac.new(settings.session_key.encode(), sid.encode(), hashlib.sha256).hexdigest()


def project_json(project: Project, job: Job | None, settings: Settings) -> dict[str, Any]:
    return {
        "id": project.id,
        "name": project.name,
        "ref": project.ref,
        "workspace_id": project.workspace_id,
        "status": project.status,
        "desired": project.desired,
        "generation": project.generation,
        "endpoint": f"{settings.gateway_url}/p/{project.ref}",
        "restore_until": project.restore_until,
        "job": None
        if job is None
        else {
            "state": job.state,
            "checkpoint": job.checkpoint,
            "attempts": job.attempts,
            "error": job.error,
        },
    }


def key_json(key: ProjectKey) -> dict[str, Any]:
    return {
        "id": key.id,
        "prefix": key.prefix,
        "role": key.role,
        "created": key.created,
        "revoked": key.revoked,
    }


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.read()
    if len(settings.session_key) < 32 or len(settings.auth_jwt_secret) < 32:
        raise ValueError("Platform auth and session secrets are required")
    engine, sessions = database(settings)
    app = FastAPI(title="SiBase Control Plane", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(RequestLogMiddleware)
    app.state.engine = engine

    def get_db() -> Iterator[Session]:
        with sessions() as db, db.begin():
            yield db

    Db = Annotated[Session, Depends(get_db)]

    def origin(request: Request) -> None:
        if request.headers.get("origin") not in settings.origins:
            raise HTTPException(403, "Untrusted origin")

    def identity(request: Request, db: Session) -> Account:
        sid = request.cookies.get(COOKIE, "")
        session = db.get(LoginSession, digest(sid)) if sid else None
        account = db.get(Account, session.account_id) if session else None
        if not session or session.expires <= now() or not account or not account.enabled:
            raise HTTPException(401, "Sign in required")
        if request.method not in {"GET", "HEAD"}:
            origin(request)
            if not hmac.compare_digest(
                request.headers.get("x-csrf-token", ""), csrf(settings, sid)
            ):
                raise HTTPException(403, "Invalid CSRF token")
        return account

    def authorize(
        request: Request, db: Session, wid: str, manage: bool = False
    ) -> tuple[Account, Membership]:
        account = identity(request, db)
        # Serialize workspace mutations, including last-owner, quota and idempotency checks.
        query = select(Workspace).where(Workspace.id == wid)
        if request.method != "GET":
            query = query.with_for_update()
        workspace = db.scalar(query)
        member = db.get(Membership, (wid, account.id)) if workspace else None
        if not member:
            raise HTTPException(404, "Workspace not found")
        if manage and member.role not in MANAGERS:
            raise HTTPException(403, "Owner or Admin required")
        return account, member

    def audit(db: Session, wid: str, actor: str, action: str, target: str) -> None:
        db.add(Audit(workspace_id=wid, actor=actor, action=action, target=target))

    def find_project(
        request: Request, db: Session, wid: str, pid: str, manage: bool = False
    ) -> tuple[Account, Project]:
        account, _ = authorize(request, db, wid, manage)
        query = select(Project).where(Project.id == pid, Project.workspace_id == wid)
        if request.method != "GET":
            query = query.with_for_update()
        project = db.scalar(query)
        if not project:
            raise HTTPException(404, "Project not found")
        return account, project

    @app.get("/health/live")
    def health() -> dict[str, str]:
        return {"status": "up"}

    @app.post("/api/v2/login")
    def login(body: Login, request: Request, response: Response, db: Db) -> dict[str, Any]:
        origin(request)
        try:
            with httpx.Client(timeout=10) as client:
                upstream = client.post(
                    f"{settings.auth_url}/token?grant_type=password", json=body.model_dump()
                )
            if upstream.status_code != 200:
                raise HTTPException(401, "Invalid credentials")
            claims = jwt.decode(
                upstream.json()["access_token"],
                settings.auth_jwt_secret,
                algorithms=["HS256"],
                audience="authenticated",
                issuer=settings.auth_issuer,
                options={"require": ["exp", "iat", "sub", "aud", "iss"]},
            )
        except (httpx.HTTPError, jwt.PyJWTError, KeyError, ValueError) as exc:
            raise HTTPException(503, "Platform authentication unavailable") from exc
        account = db.get(Account, claims["sub"])
        if not account or not account.enabled:
            raise HTTPException(403, "Platform account not enabled")
        old = db.get(LoginSession, digest(request.cookies.get(COOKIE, "")))
        if old:
            db.delete(old)
        sid = secrets.token_urlsafe(32)
        expires = min(int(claims["exp"]), now() + 3600)
        db.add(LoginSession(digest=digest(sid), account_id=account.id, expires=expires))
        response.set_cookie(
            COOKIE,
            sid,
            max_age=expires - now(),
            httponly=True,
            secure=settings.secure_cookie,
            samesite="strict",
            path="/api/v2",
        )
        return {"email": account.email, "csrf": csrf(settings, sid), "expires": expires}

    @app.get("/api/v2/me")
    def me(request: Request, db: Db) -> dict[str, Any]:
        account = identity(request, db)
        return {
            "id": account.id,
            "email": account.email,
            "csrf": csrf(settings, request.cookies[COOKIE]),
        }

    @app.post("/api/v2/logout")
    def logout(request: Request, response: Response, db: Db) -> dict[str, bool]:
        identity(request, db)
        session = db.get(LoginSession, digest(request.cookies[COOKIE]))
        if session:
            db.delete(session)
        response.delete_cookie(
            COOKIE, path="/api/v2", samesite="strict", secure=settings.secure_cookie
        )
        return {"ok": True}

    @app.get("/api/v2/workspaces")
    def workspaces(request: Request, db: Db) -> list[dict[str, str]]:
        account = identity(request, db)
        rows = db.execute(
            select(Workspace, Membership)
            .join(Membership)
            .where(Membership.account_id == account.id)
        )
        return [{"id": w.id, "name": w.name, "role": m.role} for w, m in rows]

    @app.post("/api/v2/workspaces", status_code=201)
    def create_workspace(body: Named, request: Request, db: Db) -> dict[str, str]:
        account = identity(request, db)
        workspace = Workspace(name=body.name.strip())
        db.add(workspace)
        db.flush()
        db.add(Membership(workspace_id=workspace.id, account_id=account.id, role="owner"))
        audit(db, workspace.id, account.id, "workspace.created", workspace.id)
        return {"id": workspace.id, "name": workspace.name, "role": "owner"}

    @app.get("/api/v2/workspaces/{wid}/members")
    def members(wid: str, request: Request, db: Db) -> list[dict[str, str]]:
        authorize(request, db, wid)
        rows = db.execute(
            select(Account, Membership).join(Membership).where(Membership.workspace_id == wid)
        )
        return [{"id": a.id, "email": a.email, "role": m.role} for a, m in rows]

    @app.put("/api/v2/workspaces/{wid}/members")
    def put_member(wid: str, body: MemberInput, request: Request, db: Db) -> dict[str, bool]:
        actor, _ = authorize(request, db, wid, True)
        target = db.scalar(
            select(Account).where(
                Account.email == body.email.lower().strip(), Account.enabled.is_(True)
            )
        )
        if not target:
            raise HTTPException(404, "Account must be provisioned by an operator first")
        member = db.get(Membership, (wid, target.id))
        if member and member.role == "owner":
            raise HTTPException(409, "Use ownership transfer to change Owner")
        if member:
            member.role = body.role
        else:
            db.add(Membership(workspace_id=wid, account_id=target.id, role=body.role))
        audit(db, wid, actor.id, f"member.set.{body.role}", target.id)
        return {"ok": True}

    @app.delete("/api/v2/workspaces/{wid}/members/{aid}")
    def remove_member(wid: str, aid: str, request: Request, db: Db) -> dict[str, bool]:
        actor, _ = authorize(request, db, wid, True)
        member = db.get(Membership, (wid, aid))
        if not member:
            raise HTTPException(404, "Member not found")
        if member.role == "owner":
            raise HTTPException(409, "Cannot remove Owner")
        db.delete(member)
        audit(db, wid, actor.id, "member.removed", aid)
        return {"ok": True}

    @app.post("/api/v2/workspaces/{wid}/transfer/{aid}")
    def transfer(wid: str, aid: str, request: Request, db: Db) -> dict[str, bool]:
        actor, current = authorize(request, db, wid, True)
        target = db.get(Membership, (wid, aid))
        if current.role != "owner":
            raise HTTPException(403, "Owner required")
        if not target or target.account_id == actor.id:
            raise HTTPException(409, "Choose another existing member")
        current.role, target.role = "admin", "owner"
        audit(db, wid, actor.id, "workspace.owner_transferred", aid)
        return {"ok": True}

    @app.get("/api/v2/workspaces/{wid}/projects")
    def projects(wid: str, request: Request, db: Db) -> list[dict[str, Any]]:
        authorize(request, db, wid)
        return [
            project_json(p, db.get(Job, p.id), settings)
            for p in db.scalars(
                select(Project).where(Project.workspace_id == wid).order_by(Project.created)
            )
        ]

    @app.post("/api/v2/workspaces/{wid}/projects", status_code=202)
    def create_project(wid: str, body: Named, request: Request, db: Db) -> dict[str, Any]:
        account, _ = authorize(request, db, wid, True)
        rid = request.headers.get("idempotency-key", "")
        if (
            not 8 <= len(rid) <= 64
            or not rid.isascii()
            or not all(c.isalnum() or c in "-_" for c in rid)
        ):
            raise HTTPException(400, "Idempotency-Key (8–64 letters, digits, - or _) required")
        prior = db.scalar(
            select(Project).where(Project.workspace_id == wid, Project.request_id == rid)
        )
        if prior:
            if prior.name != body.name.strip():
                raise HTTPException(409, "Idempotency-Key already used for a different request")
            return project_json(prior, db.get(Job, prior.id), settings)
        # Soft-deleted projects still occupy resources until an operator purges them.
        if db.get_bind().dialect.name == "postgresql":
            db.execute(text("SELECT pg_advisory_xact_lock(734280193)"))
        count = len(list(db.scalars(select(Project.id))))
        if count >= 5:
            raise HTTPException(
                409, "Local pilot limit: five projects (including retained projects)"
            )
        project = Project(
            name=body.name.strip(), workspace_id=wid, ref="p_" + identifier()[:16], request_id=rid
        )
        db.add(project)
        db.flush()
        job = Job(project_id=project.id)
        db.add(job)
        db.flush()
        audit(db, wid, account.id, "project.created", project.id)
        return project_json(project, job, settings)

    @app.post("/api/v2/workspaces/{wid}/projects/{pid}/lifecycle", status_code=202)
    def lifecycle(
        wid: str, pid: str, body: LifecycleInput, request: Request, db: Db
    ) -> dict[str, Any]:
        actor, project = find_project(request, db, wid, pid, True)
        action = body.action
        if project.desired == "deleted":
            if action not in {"restore", "delete"}:
                raise HTTPException(409, "Restore the deleted project first")
            if action == "restore" and (not project.restore_until or now() > project.restore_until):
                raise HTTPException(409, "Restore window expired; contact an operator")
        elif action == "restore":
            raise HTTPException(409, "Project is not deleted")
        if action == "retry" and project.status != "failed":
            raise HTTPException(409, "Only failed jobs can be retried")
        target = {
            "suspend": "suspended",
            "resume": "ready",
            "archive": "archived",
            "delete": "deleted",
            "restore": "ready",
        }.get(action, project.desired)
        if target == "deleted" and project.desired != "deleted":
            project.restore_until = now() + 7 * 86400
        if action == "restore":
            project.restore_until = None
        project.desired, project.status = target, "pending"
        project.generation += 1
        job = db.get(Job, pid)
        assert job is not None
        job.generation, job.state, job.attempts, job.error = project.generation, "pending", 0, None
        job.updated = now()
        audit(db, wid, actor.id, f"project.{action}", pid)
        return project_json(project, job, settings)

    @app.get("/api/v2/workspaces/{wid}/projects/{pid}/keys")
    def keys(wid: str, pid: str, request: Request, db: Db) -> list[dict[str, Any]]:
        find_project(request, db, wid, pid, True)
        return [
            key_json(k)
            for k in db.scalars(
                select(ProjectKey).where(ProjectKey.project_id == pid).order_by(ProjectKey.created)
            )
        ]

    def issue_key(
        wid: str, pid: str, role: str, request: Request, db: Session, old_id: str | None = None
    ) -> dict[str, Any]:
        actor, project = find_project(request, db, wid, pid, True)
        if project.desired == "deleted":
            raise HTTPException(409, "Restore project before issuing keys")
        if old_id:
            old = db.get(ProjectKey, old_id)
            if not old or old.project_id != pid or old.revoked:
                raise HTTPException(404, "Active key not found")
            role = old.role
            old.revoked = now()
        raw = "sb_" + role + "_" + secrets.token_urlsafe(32)
        key = ProjectKey(project_id=pid, role=role, digest=digest(raw), prefix=raw[:20])
        db.add(key)
        db.flush()
        audit(db, wid, actor.id, "key.rotated" if old_id else "key.created", key.id)
        return {**key_json(key), "key": raw}

    @app.post("/api/v2/workspaces/{wid}/projects/{pid}/keys", status_code=201)
    def create_key(wid: str, pid: str, body: KeyInput, request: Request, db: Db) -> dict[str, Any]:
        return issue_key(wid, pid, body.role, request, db)

    @app.post("/api/v2/workspaces/{wid}/projects/{pid}/keys/{kid}/rotate", status_code=201)
    def rotate_key(wid: str, pid: str, kid: str, request: Request, db: Db) -> dict[str, Any]:
        return issue_key(wid, pid, "anon", request, db, kid)

    @app.delete("/api/v2/workspaces/{wid}/projects/{pid}/keys/{kid}")
    def revoke(wid: str, pid: str, kid: str, request: Request, db: Db) -> dict[str, bool]:
        actor, _ = find_project(request, db, wid, pid, True)
        key = db.get(ProjectKey, kid)
        if not key or key.project_id != pid:
            raise HTTPException(404, "Key not found")
        key.revoked = key.revoked or now()
        audit(db, wid, actor.id, "key.revoked", kid)
        return {"ok": True}

    @app.get("/api/v2/workspaces/{wid}/audit")
    def events(wid: str, request: Request, db: Db) -> list[dict[str, Any]]:
        authorize(request, db, wid)
        return [
            {
                "id": a.id,
                "actor": a.actor,
                "action": a.action,
                "target": a.target,
                "created": a.created,
            }
            for a in db.scalars(
                select(Audit)
                .where(Audit.workspace_id == wid)
                .order_by(Audit.created.desc(), Audit.id)
                .limit(100)
            )
        ]

    @app.get("/api/v2/workspaces/{wid}/projects/{pid}/auth")
    def app_auth(wid: str, pid: str, request: Request, db: Db) -> dict[str, Any]:
        find_project(request, db, wid, pid, True)
        config = db.get(AppAuthConfig, pid)
        snapshot = db.get(AppAuthSnapshot, pid)
        return {
            "enabled": config is not None,
            "settings": {
                "jwt_exp": config.jwt_exp,
                "site_url": config.site_url,
                "signing_epoch": config.signing_epoch,
            }
            if config
            else None,
            "snapshot": {
                "collected": snapshot.collected,
                "error": snapshot.error,
                **snapshot.result,
            }
            if snapshot
            else None,
            "contract": {
                "email_confirmation": True,
                "refresh_rotation": True,
                "refresh_reuse_interval": 0,
                "logout": "Refresh tokens revoked; access JWT remains valid until expiry",
                "rls": "Forced for public tables; existing policies are preserved",
            },
        }

    @app.put("/api/v2/workspaces/{wid}/projects/{pid}/auth", status_code=202)
    def configure_app_auth(
        wid: str, pid: str, body: AppAuthInput, request: Request, db: Db
    ) -> dict[str, Any]:
        actor, project = find_project(request, db, wid, pid, True)
        if project.status != "ready" or project.desired != "ready":
            raise HTTPException(409, "Project must be ready before configuring app authentication")
        config = db.get(AppAuthConfig, pid)
        if config:
            config.jwt_exp, config.site_url = body.jwt_exp, body.site_url
        else:
            db.add(AppAuthConfig(project_id=pid, jwt_exp=body.jwt_exp, site_url=body.site_url))
        project.status, project.generation = "pending", project.generation + 1
        job = db.get(Job, pid)
        assert job
        job.state, job.generation, job.attempts, job.error = "pending", project.generation, 0, None
        job.updated = now()
        audit(db, wid, actor.id, "auth.configured", pid)
        return project_json(project, job, settings)

    @app.post("/api/v2/workspaces/{wid}/projects/{pid}/auth/rotate-signing-key", status_code=202)
    def rotate_app_signing_key(wid: str, pid: str, request: Request, db: Db) -> dict[str, Any]:
        actor, project = find_project(request, db, wid, pid, True)
        config = db.get(AppAuthConfig, pid)
        if not config or project.status != "ready" or project.desired != "ready":
            raise HTTPException(409, "Verified Auth must be enabled and project ready")
        config.signing_epoch += 1
        project.status, project.generation = "pending", project.generation + 1
        job = db.get(Job, pid)
        assert job
        job.state, job.generation, job.attempts, job.error = "pending", project.generation, 0, None
        job.updated = now()
        audit(db, wid, actor.id, "auth.signing_rotation_requested", pid)
        return project_json(project, job, settings)

    return app
