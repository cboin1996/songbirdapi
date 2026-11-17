"""add songs.tagged_at

Revision ID: d5f6a7b8c9d0
Revises: c4e5f6a7b8c9
Create Date: 2026-11-17 00:10:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "c4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema. Songs that already have properties count as tagged."""
    op.add_column(
        "songs", sa.Column("tagged_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute("UPDATE songs SET tagged_at = created_at WHERE properties IS NOT NULL")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("songs", "tagged_at")
