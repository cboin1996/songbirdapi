"""fix import_jobs created_at/updated_at default to use now() function

Revision ID: a1b2c3d4e5f6
Revises: 2f5adcc84df4
Create Date: 2026-04-30 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "2f5adcc84df4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE import_jobs ALTER COLUMN created_at SET DEFAULT now()")
    op.execute("ALTER TABLE import_jobs ALTER COLUMN updated_at SET DEFAULT now()")


def downgrade() -> None:
    pass
