"""fix timestamp server defaults to use func.now()

Revision ID: db1d80281c83
Revises: b3d4e5f6g7h8
Create Date: 2026-05-18 18:56:47.145044

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "db1d80281c83"
down_revision: Union[str, Sequence[str], None] = "b3d4e5f6g7h8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column("users", "created_at", server_default=sa.func.now())
    op.alter_column("songs", "created_at", server_default=sa.func.now())
    op.alter_column("user_songs", "added_at", server_default=sa.func.now())
    op.alter_column("song_plays", "played_at", server_default=sa.func.now())
    op.alter_column("user_player_state", "updated_at", server_default=sa.func.now())
    op.alter_column("song_downloads", "downloaded_at", server_default=sa.func.now())
    op.alter_column("song_share_tokens", "created_at", server_default=sa.func.now())
    op.alter_column("edit_jobs", "created_at", server_default=sa.func.now())
    op.alter_column("edit_jobs", "updated_at", server_default=sa.func.now())
    op.alter_column("song_edit_drafts", "updated_at", server_default=sa.func.now())
    op.alter_column("user_offline_songs", "created_at", server_default=sa.func.now())
    op.alter_column("error_logs", "timestamp", server_default=sa.func.now())


def downgrade() -> None:
    """Downgrade schema."""
    pass
