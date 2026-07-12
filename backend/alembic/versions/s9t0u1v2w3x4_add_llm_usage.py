"""add llm_usage token-accounting table

One row per successful, non-mock LLM call: provider/model + prompt/completion/
total token counts, attributed to a user and a surface. Best-effort telemetry —
see app.services.token_usage. Feeds per-user / per-surface cost visibility and
(later) the admin stats dashboard.

Revision ID: s9t0u1v2w3x4
Revises: r8s9t0u1v2w3
Create Date: 2026-07-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = "s9t0u1v2w3x4"
down_revision: Union[str, Sequence[str], None] = "r8s9t0u1v2w3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "llmusage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("surface", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("provider", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("model", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("meal_plan_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["meal_plan_id"], ["mealplan.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_llmusage_user_id", "llmusage", ["user_id"], unique=False)
    op.create_index("ix_llmusage_surface", "llmusage", ["surface"], unique=False)
    op.create_index("ix_llmusage_created_at", "llmusage", ["created_at"], unique=False)
    op.create_index(
        "ix_llmusage_meal_plan_id", "llmusage", ["meal_plan_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_llmusage_meal_plan_id", table_name="llmusage")
    op.drop_index("ix_llmusage_created_at", table_name="llmusage")
    op.drop_index("ix_llmusage_surface", table_name="llmusage")
    op.drop_index("ix_llmusage_user_id", table_name="llmusage")
    op.drop_table("llmusage")
