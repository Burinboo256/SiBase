from datetime import datetime
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Installation(Base):
    __tablename__ = "installation"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))


class ServiceStatus(BaseModel):
    id: str
    name: str
    status: Literal["up", "down"]
    latency_ms: int
    detail: str


class ProjectStatus(BaseModel):
    ref: str
    name: str
    endpoint: str
    status: Literal["healthy", "degraded"]
    services: list[ServiceStatus]


class Overview(BaseModel):
    environment: str
    phase: int = 1
    checked_at: datetime
    platform: ServiceStatus
    projects: list[ProjectStatus]
