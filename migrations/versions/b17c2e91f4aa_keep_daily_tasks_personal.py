"""keep daily tasks personal and expand client categories

Revision ID: b17c2e91f4aa
Revises: a92d4e71bc03
Create Date: 2026-09-21
"""

from alembic import op
import sqlalchemy as sa


revision = "b17c2e91f4aa"
down_revision = "a92d4e71bc03"
branch_labels = None
depends_on = None


def upgrade():
    # Remove rows that the previous release created automatically from client
    # and iCloud calendar events. Personal explicit calendar tasks remain.
    op.execute(
        sa.text(
            "DELETE FROM daily_tasks WHERE calendar_event_id IN "
            "(SELECT id FROM calendar_events "
            "WHERE origin = 'icloud' OR client_id IS NOT NULL)"
        )
    )
    op.execute(
        sa.text(
            "UPDATE clients SET client_group = CASE client_group "
            "WHEN 'active' THEN 'a' WHEN 'potential' THEN 'p' "
            "ELSE client_group END"
        )
    )


def downgrade():
    op.execute(
        sa.text(
            "UPDATE clients SET client_group = CASE client_group "
            "WHEN 'a' THEN 'active' WHEN 'p' THEN 'potential' "
            "ELSE client_group END"
        )
    )
