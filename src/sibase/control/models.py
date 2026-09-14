"""Control-plane metadata. Never store plaintext passwords or API keys here."""

import time
import uuid
from typing import Any

from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def identifier() -> str:
    return uuid.uuid4().hex


def now() -> int:
    return int(time.time())


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    enabled: Mapped[bool] = mapped_column(default=True)


class LoginSession(Base):
    __tablename__ = "sessions"
    digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"))
    expires: Mapped[int]


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=identifier)
    name: Mapped[str] = mapped_column(String(80))
    created: Mapped[int] = mapped_column(default=now)


class Membership(Base):
    __tablename__ = "memberships"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(16))


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("workspace_id", "request_id"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=identifier)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    ref: Mapped[str] = mapped_column(String(24), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    request_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    desired: Mapped[str] = mapped_column(String(20), default="ready")
    generation: Mapped[int] = mapped_column(default=1)
    restore_until: Mapped[int | None]
    created: Mapped[int] = mapped_column(default=now)


class Job(Base):
    __tablename__ = "jobs"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    state: Mapped[str] = mapped_column(String(16), default="pending")
    generation: Mapped[int] = mapped_column(default=1)
    attempts: Mapped[int] = mapped_column(default=0)
    checkpoint: Mapped[str] = mapped_column(String(32), default="queued")
    error: Mapped[str | None] = mapped_column(String(80))
    updated: Mapped[int] = mapped_column(default=now)


class ProjectSecret(Base):
    __tablename__ = "project_secrets"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    ciphertext: Mapped[str]


class GatewayRoute(Base):
    __tablename__ = "gateway_routes"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    ciphertext: Mapped[str]


class ProjectKey(Base):
    __tablename__ = "project_keys"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=identifier)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    digest: Mapped[str] = mapped_column(String(64), unique=True)
    prefix: Mapped[str] = mapped_column(String(24))
    role: Mapped[str] = mapped_column(String(16))
    created: Mapped[int] = mapped_column(default=now)
    revoked: Mapped[int | None]


class Audit(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=identifier)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    actor: Mapped[str] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(48))
    target: Mapped[str] = mapped_column(String(64))
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created: Mapped[int] = mapped_column(default=now)


class AppAuthConfig(Base):
    __tablename__ = "app_auth_config"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    jwt_exp: Mapped[int] = mapped_column(default=900)
    site_url: Mapped[str] = mapped_column(String(512))
    signing_epoch: Mapped[int] = mapped_column(default=1)


class AppAuthSnapshot(Base):
    __tablename__ = "app_auth_snapshots"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    collected: Mapped[int] = mapped_column(default=now)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(String(80))
