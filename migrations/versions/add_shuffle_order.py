"""add shuffle_order to user_player_state

Revision ID: a3f8c2d1e490
Revises: 20312ad1d71e
Create Date: 2026-04-27 12:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = 'a3f8c2d1e490'
down_revision: Union[str, Sequence[str], None] = '20312ad1d71e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('user_player_state', sa.Column('shuffle_order', JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column('user_player_state', 'shuffle_order')
