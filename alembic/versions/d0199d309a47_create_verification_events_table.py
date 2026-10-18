"""create_verification_events_table

Revision ID: d0199d309a47
Revises: 8046c184216a
Create Date: 2026-10-19 00:05:45.857282

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd0199d309a47'
down_revision: Union[str, Sequence[str], None] = '8046c184216a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema to add verification_events table."""
    op.create_table(
        'verification_events',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('outcome', sa.String(length=32), nullable=False),
        sa.Column('verification_flow', sa.String(length=32), server_default='web', nullable=False),
        sa.Column('user_id', sa.String(length=128), nullable=True),
        sa.Column('speaker_id', sa.String(length=64), nullable=True),
        sa.Column('device_id', sa.String(length=64), nullable=True),
        sa.Column('request_id', sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(['speaker_id'], ['speakers.speaker_id'], ondelete='SET NULL', name='fk_verification_events_speaker_id'),
        sa.ForeignKeyConstraint(['device_id'], ['devices.device_id'], ondelete='SET NULL', name='fk_verification_events_device_id'),
        sa.CheckConstraint(
            "outcome IN ('verified', 'rejected', 'challenge_failed', 'unauthorized', 'error')",
            name='ck_verification_events_outcome',
        ),
        sa.CheckConstraint(
            "verification_flow IN ('web', 'device')",
            name='ck_verification_events_flow',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_verification_events_created_at'), 'verification_events', ['created_at'], unique=False)
    op.create_index(op.f('ix_verification_events_outcome'), 'verification_events', ['outcome'], unique=False)
    op.create_index(op.f('ix_verification_events_created_outcome'), 'verification_events', ['created_at', 'outcome'], unique=False)
    op.create_index(op.f('ix_verification_events_user_id'), 'verification_events', ['user_id'], unique=False)
    op.create_index(op.f('ix_verification_events_speaker_id'), 'verification_events', ['speaker_id'], unique=False)
    op.create_index(op.f('ix_verification_events_device_id'), 'verification_events', ['device_id'], unique=False)
    op.create_index(op.f('ix_verification_events_request_id'), 'verification_events', ['request_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema to drop verification_events table."""
    op.drop_index(op.f('ix_verification_events_request_id'), table_name='verification_events')
    op.drop_index(op.f('ix_verification_events_device_id'), table_name='verification_events')
    op.drop_index(op.f('ix_verification_events_speaker_id'), table_name='verification_events')
    op.drop_index(op.f('ix_verification_events_user_id'), table_name='verification_events')
    op.drop_index(op.f('ix_verification_events_created_outcome'), table_name='verification_events')
    op.drop_index(op.f('ix_verification_events_outcome'), table_name='verification_events')
    op.drop_index(op.f('ix_verification_events_created_at'), table_name='verification_events')
    op.drop_table('verification_events')
