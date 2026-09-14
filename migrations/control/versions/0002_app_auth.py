"""Per-project app authentication settings and sanitized worker snapshots."""

import sqlalchemy as sa
from alembic import op

revision = "control_0002"
down_revision = "control_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_auth_config",
        sa.Column("project_id", sa.String(32), sa.ForeignKey("projects.id"), primary_key=True),
        sa.Column("jwt_exp", sa.Integer(), nullable=False),
        sa.Column("site_url", sa.String(512), nullable=False),
        sa.Column("signing_epoch", sa.Integer(), nullable=False),
    )
    op.create_table(
        "app_auth_snapshots",
        sa.Column("project_id", sa.String(32), sa.ForeignKey("projects.id"), primary_key=True),
        sa.Column("collected", sa.Integer(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("error", sa.String(80)),
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON app_auth_config TO control_api")
    op.execute("GRANT SELECT ON app_auth_config TO control_worker")
    op.execute("GRANT SELECT ON app_auth_snapshots TO control_api")
    op.execute("GRANT SELECT, INSERT, UPDATE ON app_auth_snapshots TO control_worker")


def downgrade() -> None:
    raise RuntimeError("Restore a backup instead of deleting authentication configuration")
