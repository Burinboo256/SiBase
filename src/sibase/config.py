"""Private runtime configuration; never serialize this into API responses."""

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class ProbeSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    kind: Literal["http", "postgres"]
    url: SecretStr
    headers: dict[str, SecretStr] = Field(default_factory=dict)
    healthy_json_path: list[str] = Field(default_factory=list)
    storage_topology_url: SecretStr | None = None


class ProjectSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ref: str
    name: str
    endpoint: str
    probes: list[ProbeSettings]


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    environment: Literal["local", "test"] = "local"
    platform_url: SecretStr
    projects: list[ProjectSettings] = Field(default_factory=list)

    @classmethod
    def load(cls) -> "Settings":
        path = Path(os.environ.get("SIBASE_SETTINGS", "/run/secrets/api.json"))
        return cls.model_validate_json(path.read_text())
