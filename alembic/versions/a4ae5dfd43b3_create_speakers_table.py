"""create_speakers_table

Revision ID: a4ae5dfd43b3
Revises: e32dc984b290
Create Date: 2026-10-18 04:33:38.790615

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4ae5dfd43b3'
down_revision: Union[str, Sequence[str], None] = 'e32dc984b290'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema to add speakers table."""
    op.create_table(
        'speakers',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('speaker_id', sa.String(length=64), nullable=False),
        sa.Column('full_name', sa.String(length=128), nullable=True),
        sa.Column('status', sa.String(length=32), server_default='active', nullable=False),
        sa.Column('embedding_dim', sa.Integer(), server_default='192', nullable=False),
        sa.Column('sample_count', sa.Integer(), server_default='1', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('metadata_json', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_speakers_speaker_id'), 'speakers', ['speaker_id'], unique=True)


def downgrade() -> None:
    """Downgrade schema to remove speakers table."""
    op.drop_index(op.f('ix_speakers_speaker_id'), table_name='speakers')
    op.drop_table('speakers')

