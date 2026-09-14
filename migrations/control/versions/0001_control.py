"""Isolated Phase 2 metadata and least-privilege grants."""

from alembic import op

from sibase.control.models import Base

revision = "control_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Keep the original migration's table set fixed as new models are added.
    names = (
        "accounts",
        "sessions",
        "workspaces",
        "memberships",
        "projects",
        "jobs",
        "project_keys",
        "project_secrets",
        "gateway_routes",
        "audit_events",
    )
    Base.metadata.create_all(op.get_bind(), tables=[Base.metadata.tables[name] for name in names])
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON accounts, sessions, workspaces, memberships, projects, jobs, project_keys TO control_api"
    )
    op.execute("GRANT SELECT, INSERT ON audit_events TO control_api")
    op.execute("GRANT SELECT, UPDATE ON projects, jobs TO control_worker")
    op.execute("GRANT SELECT, INSERT, UPDATE ON project_secrets, gateway_routes TO control_worker")
    op.execute("GRANT INSERT ON audit_events TO control_worker")
    op.execute("GRANT SELECT ON projects, project_keys, gateway_routes TO control_gateway")


def downgrade() -> None:
    raise RuntimeError("Control-plane downgrade would destroy metadata; restore a backup instead")
