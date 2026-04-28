"""add user_offline_songs

Revision ID: 31aebf5bd316
Revises: ae7d7324367e
Create Date: 2026-04-27 20:17:04.233362

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '31aebf5bd316'
down_revision: Union[str, Sequence[str], None] = 'ae7d7324367e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'user_offline_songs',
        sa.Column('user_id', sa.Text(), nullable=False),
        sa.Column('song_id', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['song_id'], ['songs.uuid'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id', 'song_id'),
    )


def downgrade() -> None:
    op.drop_table('user_offline_songs')
