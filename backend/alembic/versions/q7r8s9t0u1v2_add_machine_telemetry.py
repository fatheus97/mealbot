"""add machine_generation and machine_correction telemetry tables

Captures the machine-output → user-correction delta: every LLM/OCR generation
(machinegeneration) plus every user edit/commit of that output
(machinecorrection), linked via generation_id. Append-only, best-effort — see
app.services.telemetry.

Revision ID: q7r8s9t0u1v2
Revises: p6q7r8s9t0u1
Create Date: 2026-07-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import sqlmodel


revision: str = "q7r8s9t0u1v2"
down_revision: Union[str, Sequence[str], None] = "p6q7r8s9t0u1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "machinegeneration",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("surface", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("meal_plan_id", sa.Integer(), nullable=True),
        sa.Column("request_json", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("output_json", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["meal_plan_id"], ["mealplan.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_machinegeneration_user_id", "machinegeneration", ["user_id"], unique=False
    )
    op.create_index(
        "ix_machinegeneration_surface", "machinegeneration", ["surface"], unique=False
    )
    op.create_index(
        "ix_machinegeneration_created_at",
        "machinegeneration",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_machinegeneration_meal_plan_id",
        "machinegeneration",
        ["meal_plan_id"],
        unique=False,
    )

    op.create_table(
        "machinecorrection",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("surface", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("generation_id", sa.Integer(), nullable=True),
        sa.Column("meal_plan_id", sa.Integer(), nullable=True),
        sa.Column("context_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("before_json", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("after_json", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["generation_id"], ["machinegeneration.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["meal_plan_id"], ["mealplan.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_machinecorrection_user_id", "machinecorrection", ["user_id"], unique=False
    )
    op.create_index(
        "ix_machinecorrection_surface", "machinecorrection", ["surface"], unique=False
    )
    op.create_index(
        "ix_machinecorrection_created_at",
        "machinecorrection",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_machinecorrection_generation_id",
        "machinecorrection",
        ["generation_id"],
        unique=False,
    )
    op.create_index(
        "ix_machinecorrection_meal_plan_id",
        "machinecorrection",
        ["meal_plan_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_machinecorrection_meal_plan_id", table_name="machinecorrection")
    op.drop_index("ix_machinecorrection_generation_id", table_name="machinecorrection")
    op.drop_index("ix_machinecorrection_created_at", table_name="machinecorrection")
    op.drop_index("ix_machinecorrection_surface", table_name="machinecorrection")
    op.drop_index("ix_machinecorrection_user_id", table_name="machinecorrection")
    op.drop_table("machinecorrection")

    op.drop_index("ix_machinegeneration_meal_plan_id", table_name="machinegeneration")
    op.drop_index("ix_machinegeneration_created_at", table_name="machinegeneration")
    op.drop_index("ix_machinegeneration_surface", table_name="machinegeneration")
    op.drop_index("ix_machinegeneration_user_id", table_name="machinegeneration")
    op.drop_table("machinegeneration")
