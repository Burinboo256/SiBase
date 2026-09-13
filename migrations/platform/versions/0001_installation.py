"""Create the platform foundation, not workspace/project provisioning."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    table = op.create_table(
        "installation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
    )
    op.bulk_insert(table, [{"id": 1, "name": "SiBase local development"}])


def downgrade() -> None:
    op.drop_table("installation")
