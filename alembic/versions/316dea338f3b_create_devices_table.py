"""create_devices_table

Revision ID: 316dea338f3b
Revises: 0b98eaf9dc3e
Create Date: 2026-10-18 18:15:15.093292

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '316dea338f3b'
down_revision: Union[str, Sequence[str], None] = '0b98eaf9dc3e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema to add devices table."""
    op.create_table(
        'devices',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('device_id', sa.String(length=64), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=True),
        sa.Column('status', sa.String(length=32), server_default='active', nullable=False),
        sa.Column('secret_hash', sa.String(length=255), nullable=False),
        sa.Column('key_version', sa.Integer(), server_default='1', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('metadata_json', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_devices_device_id'), 'devices', ['device_id'], unique=True)


def downgrade() -> None:
    """Downgrade schema to drop devices table."""
    op.drop_index(op.f('ix_devices_device_id'), table_name='devices')
    op.drop_table('devices')

