"""baseline

Revision ID: 20312ad1d71e
Revises: 
Create Date: 2026-04-27 08:53:41.915422

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '20312ad1d71e'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Baseline — DB already at this state, no-op."""
    pass


def downgrade() -> None:
    """Baseline — no downgrade."""
    pass
