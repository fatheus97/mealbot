"""add_meal_embedding_drop_reciperow

Revision ID: g7h8i9j0k1l2
Revises: f6g7h8i9j0k1
Create Date: 2026-04-13 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector  # type: ignore[import-untyped]


# revision identifiers, used by Alembic.
revision: str = 'g7h8i9j0k1l2'
down_revision: Union[str, None] = 'f6g7h8i9j0k1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add embedding column to mealentry
    op.add_column('mealentry', sa.Column('embedding', Vector(384), nullable=True))

    # Add HNSW index for cosine similarity search
    op.create_index(
        'ix_mealentry_embedding_hnsw',
        'mealentry',
        ['embedding'],
        postgresql_using='hnsw',
        postgresql_with={'m': 16, 'ef_construction': 64},
        postgresql_ops={'embedding': 'vector_cosine_ops'},
    )

    # Drop old RecipeRow table and its index
    op.drop_index('ix_recipe_embedding_hnsw', table_name='reciperow')
    op.drop_table('reciperow')


def downgrade() -> None:
    # Recreate reciperow table
    op.create_table(
        'reciperow',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('ingredients_text', sa.String(), nullable=False),
        sa.Column('steps_text', sa.String(), nullable=False),
        sa.Column('cuisine', sa.String(), nullable=True),
        sa.Column('tags_text', sa.String(), server_default=''),
        sa.Column('embedding', Vector(384), nullable=False),
    )
    op.create_index('ix_reciperow_title', 'reciperow', ['title'])
    op.create_index('ix_reciperow_cuisine', 'reciperow', ['cuisine'])
    op.create_index(
        'ix_recipe_embedding_hnsw',
        'reciperow',
        ['embedding'],
        postgresql_using='hnsw',
        postgresql_with={'m': 16, 'ef_construction': 64},
        postgresql_ops={'embedding': 'vector_cosine_ops'},
    )

    # Drop mealentry embedding
    op.drop_index('ix_mealentry_embedding_hnsw', table_name='mealentry')
    op.drop_column('mealentry', 'embedding')
