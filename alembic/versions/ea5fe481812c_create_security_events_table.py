"""create_security_events_table

Revision ID: ea5fe481812c
Revises: d0199d309a47
Create Date: 2026-10-19 01:36:36.818874

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ea5fe481812c'
down_revision: Union[str, Sequence[str], None] = 'd0199d309a47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema to add security_events table."""
    op.create_table(
        'security_events',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('event_type', sa.String(length=64), nullable=False),
        sa.Column('severity', sa.String(length=32), nullable=False),
        sa.Column('status', sa.String(length=32), server_default='blocked', nullable=False),
        sa.Column('details', sa.String(length=255), nullable=True),
        sa.Column('user_id', sa.String(length=128), nullable=True),
        sa.Column('device_id', sa.String(length=64), nullable=True),
        sa.Column('request_id', sa.String(length=64), nullable=True),
        sa.Column('metadata_json', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ['device_id'], ['devices.device_id'],
            ondelete='SET NULL',
            name='fk_security_events_device_id',
        ),
        sa.CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')",
            name='ck_security_events_severity',
        ),
        sa.CheckConstraint(
            "status IN ('blocked', 'detected', 'logged', 'resolved')",
            name='ck_security_events_status',
        ),
        sa.CheckConstraint(
            "event_type IN ("
            "'rate_limit_exceeded', 'payload_too_large', 'hmac_nonce_replay', "
            "'hmac_signature_invalid', 'hmac_timestamp_skew', 'unknown_device_rejected', "
            "'revoked_device_blocked', 'device_key_invalid', 'auth_token_expired', "
            "'auth_token_revoked', 'auth_token_invalid', 'unauthorized_access', "
            "'unauthorized_speaker_claim', 'admin_action', 'suspicious_payload'"
            ")",
            name='ck_security_events_event_type',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_security_events_created_at'), 'security_events', ['created_at'], unique=False)
    op.create_index(op.f('ix_security_events_event_type'), 'security_events', ['event_type'], unique=False)
    op.create_index(op.f('ix_security_events_severity'), 'security_events', ['severity'], unique=False)
    op.create_index(op.f('ix_security_events_user_id'), 'security_events', ['user_id'], unique=False)
    op.create_index(op.f('ix_security_events_device_id'), 'security_events', ['device_id'], unique=False)
    op.create_index(op.f('ix_security_events_request_id'), 'security_events', ['request_id'], unique=False)
    op.create_index(op.f('ix_security_events_created_severity'), 'security_events', ['created_at', 'severity'], unique=False)
    op.create_index(op.f('ix_security_events_created_type'), 'security_events', ['created_at', 'event_type'], unique=False)


def downgrade() -> None:
    """Downgrade schema to drop security_events table."""
    op.drop_index(op.f('ix_security_events_created_type'), table_name='security_events')
    op.drop_index(op.f('ix_security_events_created_severity'), table_name='security_events')
    op.drop_index(op.f('ix_security_events_request_id'), table_name='security_events')
    op.drop_index(op.f('ix_security_events_device_id'), table_name='security_events')
    op.drop_index(op.f('ix_security_events_user_id'), table_name='security_events')
    op.drop_index(op.f('ix_security_events_severity'), table_name='security_events')
    op.drop_index(op.f('ix_security_events_event_type'), table_name='security_events')
    op.drop_index(op.f('ix_security_events_created_at'), table_name='security_events')
    op.drop_table('security_events')
