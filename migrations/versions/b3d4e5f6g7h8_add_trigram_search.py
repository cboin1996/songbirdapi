"""add pg_trgm extension and trigram index for song search

Revision ID: b3d4e5f6g7h8
Revises: a2c31a799bb0
Create Date: 2026-05-16 18:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3d4e5f6g7h8"
down_revision: Union[str, Sequence[str], None] = "a2c31a799bb0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("""
        CREATE INDEX idx_songs_trgm_search
        ON songs
        USING gin (
            (
                COALESCE(properties->>'trackName', '') || ' ' ||
                COALESCE(properties->>'artistName', '') || ' ' ||
                COALESCE(properties->>'collectionName', '')
            )
            gin_trgm_ops
        )
        """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_songs_trgm_search")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
