"""add standalone general tasks

Revision ID: d7e5b3a9c1f2
Revises: c3f8a1d9e2b4
Create Date: 2026-09-25
"""

from alembic import op
import sqlalchemy as sa


revision = "d7e5b3a9c1f2"
down_revision = "c3f8a1d9e2b4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "general_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("text", sa.String(length=500), nullable=False),
        sa.Column(
            "is_important",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_general_tasks_completed_at"),
        "general_tasks",
        ["completed_at"],
        unique=False,
    )


def downgrade():
    op.drop_index(op.f("ix_general_tasks_completed_at"), table_name="general_tasks")
    op.drop_table("general_tasks")
