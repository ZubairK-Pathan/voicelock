"""add_embedding_json_to_speakers

Revision ID: 8046c184216a
Revises: 316dea338f3b
Create Date: 2026-10-18 23:03:16.355761

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8046c184216a'
down_revision: Union[str, Sequence[str], None] = '316dea338f3b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema to add nullable embedding_json column to speakers table."""
    with op.batch_alter_table('speakers') as batch_op:
        batch_op.add_column(sa.Column('embedding_json', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema to drop embedding_json column from speakers table."""
    with op.batch_alter_table('speakers') as batch_op:
        batch_op.drop_column('embedding_json')
