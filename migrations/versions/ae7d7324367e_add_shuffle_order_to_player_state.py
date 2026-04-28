"""add shuffle_order to player state

Revision ID: ae7d7324367e
Revises: 20312ad1d71e
Create Date: 2026-04-27 18:59:35.010874

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'ae7d7324367e'
down_revision: Union[str, Sequence[str], None] = '20312ad1d71e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('user_player_state', sa.Column('shuffle_order', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('user_player_state', 'shuffle_order')
