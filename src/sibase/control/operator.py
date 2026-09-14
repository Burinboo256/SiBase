"""Local operator account bootstrap; never called from the management API."""

import json
import sys
from pathlib import Path

import httpx
import jwt
from sqlalchemy import select

from sibase.control.config import Settings, database
from sibase.control.models import Account, Membership, Workspace, now


def main() -> None:
    settings = Settings.read()
    account = json.loads(Path(sys.argv[1]).read_text())
    _, sessions = database(settings)
    with sessions.begin() as db:
        existing = db.scalar(select(Account).where(Account.email == account["email"]))
        if existing:
            print("Account already provisioned; password unchanged.")
            return
        token = jwt.encode(
            {"role": "service_role", "iss": settings.auth_issuer, "iat": now(), "exp": now() + 60},
            settings.auth_jwt_secret,
            algorithm="HS256",
        )
        with httpx.Client(timeout=15) as client:
            result = client.post(
                settings.auth_url + "/admin/users",
                headers={"Authorization": "Bearer " + token},
                json={**account, "email_confirm": True},
            )
            if result.status_code not in {200, 201}:
                raise RuntimeError("Account creation failed (provider details suppressed)")
        identity = result.json()["id"]
        db.add(Account(id=identity, email=account["email"]))
        db.flush()
        if not db.scalar(select(Workspace.id).limit(1)):
            workspace = Workspace(name="Internal team")
            db.add(workspace)
            db.flush()
            db.add(Membership(workspace_id=workspace.id, account_id=identity, role="owner"))
    print("Platform account provisioned. Credentials remain in the private local account file.")


if __name__ == "__main__":
    main()
