"""add playlist icon

Revision ID: 2656a799d63d
Revises: 31aebf5bd316
Create Date: 2026-04-28 08:17:48.980480

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '2656a799d63d'
down_revision: Union[str, Sequence[str], None] = '31aebf5bd316'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('playlists', sa.Column('icon', sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column('playlists', 'icon')
