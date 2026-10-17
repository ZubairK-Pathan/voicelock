"""create_user_speaker_mappings_table

Revision ID: 0b98eaf9dc3e
Revises: a4ae5dfd43b3
Create Date: 2026-10-18 04:44:15.840920

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0b98eaf9dc3e'
down_revision: Union[str, Sequence[str], None] = 'a4ae5dfd43b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema to add user_speaker_mappings table."""
    op.create_table(
        'user_speaker_mappings',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('firebase_uid', sa.String(length=128), nullable=False),
        sa.Column('speaker_id', sa.String(length=64), nullable=False),
        sa.Column('assigned_by', sa.String(length=128), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('metadata_json', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['speaker_id'], ['speakers.speaker_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_user_speaker_mappings_firebase_uid'), 'user_speaker_mappings', ['firebase_uid'], unique=True)
    op.create_index(op.f('ix_user_speaker_mappings_speaker_id'), 'user_speaker_mappings', ['speaker_id'], unique=True)


def downgrade() -> None:
    """Downgrade schema to drop user_speaker_mappings table."""
    op.drop_index(op.f('ix_user_speaker_mappings_speaker_id'), table_name='user_speaker_mappings')
    op.drop_index(op.f('ix_user_speaker_mappings_firebase_uid'), table_name='user_speaker_mappings')
    op.drop_table('user_speaker_mappings')

