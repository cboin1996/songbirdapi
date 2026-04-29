"""add queue_sources to user_player_state

Revision ID: 2f5adcc84df4
Revises: 4ca3ca774ca4
Create Date: 2026-04-29 13:16:56.058109

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '2f5adcc84df4'
down_revision: Union[str, Sequence[str], None] = '4ca3ca774ca4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('user_player_state', sa.Column('queue_sources', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False))


def downgrade() -> None:
    op.drop_column('user_player_state', 'queue_sources')
