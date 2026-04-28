"""add_player_state_context_seed_fields

Revision ID: 2c1da2b3ace3
Revises: 2656a799d63d
Create Date: 2026-04-28 09:30:10.122826

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '2c1da2b3ace3'
down_revision: Union[str, Sequence[str], None] = '2656a799d63d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('user_player_state', sa.Column('play_context', sa.Text(), nullable=True))
    op.add_column('user_player_state', sa.Column('shuffle_seed', sa.Integer(), nullable=True))
    op.add_column('user_player_state', sa.Column('shuffle_position', sa.Integer(), server_default='0', nullable=False))
    op.add_column('user_player_state', sa.Column('manual_next', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False))
    op.add_column('user_player_state', sa.Column('current_song_uuid', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('user_player_state', 'current_song_uuid')
    op.drop_column('user_player_state', 'manual_next')
    op.drop_column('user_player_state', 'shuffle_position')
    op.drop_column('user_player_state', 'shuffle_seed')
    op.drop_column('user_player_state', 'play_context')
