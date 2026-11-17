"""add songs.artwork_updated_at

Revision ID: c4e5f6a7b8c9
Revises: b801ee18954c
Create Date: 2026-11-17 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "b801ee18954c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema. Epoch ms of the last art write; null means original art."""
    op.add_column(
        "songs", sa.Column("artwork_updated_at", sa.BigInteger(), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("songs", "artwork_updated_at")
