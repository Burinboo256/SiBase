import hashlib
import json
import os
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    database_url: str
    auth_url: str = "http://platform-auth:9999"
    auth_issuer: str = "http://platform-auth:9999"
    auth_jwt_secret: str = ""
    session_key: str = ""
    vault_key: str = ""
    gateway_key: str = ""
    gateway_url: str = "http://127.0.0.1:58420"
    origins: list[str] = ["http://127.0.0.1:58400", "http://localhost:58400"]
    secure_cookie: bool = False
    stack: str = "sibase-control"
    data_password: str = ""
    images: dict[str, str] = {}
    smtp_host: str = "mailpit"
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_sender: str = "noreply@sibase.local"

    @classmethod
    def read(cls) -> "Settings":
        try:
            return cls.model_validate_json(Path(os.environ["SIBASE_CONTROL_SETTINGS"]).read_text())
        except (ValueError, OSError, KeyError):
            raise ValueError("Control-plane settings are missing or invalid") from None


def database(settings: Settings) -> tuple[Engine, sessionmaker[Session]]:
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    return engine, sessionmaker(engine, expire_on_commit=False)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def seal(key: str, value: dict[str, Any]) -> str:
    return Fernet(key.encode()).encrypt(json.dumps(value).encode()).decode()


def unseal(key: str, value: str) -> dict[str, Any]:
    result: dict[str, Any] = json.loads(Fernet(key.encode()).decrypt(value.encode()))
    return result
