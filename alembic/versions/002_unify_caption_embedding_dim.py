"""unify caption_embedding dimension to 1024

Revision ID: 002
Revises: 001
Create Date: 2026-06-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Alter caption_embedding dimension: Vector(768) → Vector(1024)
    op.execute("ALTER TABLE image_embeddings ALTER COLUMN caption_embedding TYPE vector(1024)")

    # 2. Drop old caption HNSW index
    op.execute("DROP INDEX IF EXISTS idx_image_embeddings_caption_hnsw")

    # 3. Recreate HNSW index with new dimensions
    op.execute("""
        CREATE INDEX idx_image_embeddings_caption_hnsw
        ON image_embeddings
        USING hnsw (caption_embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        WHERE caption_embedding IS NOT NULL
    """)

    # 4. Update default model_name
    op.alter_column("image_embeddings", "model_name", server_default="jina-embeddings-v4")


def downgrade() -> None:
    # 1. Revert default model_name
    op.alter_column("image_embeddings", "model_name", server_default="siglip2-384")

    # 2. Drop and recreate caption HNSW index with original dimensions
    op.execute("DROP INDEX IF EXISTS idx_image_embeddings_caption_hnsw")

    op.execute("""
        CREATE INDEX idx_image_embeddings_caption_hnsw
        ON image_embeddings
        USING hnsw (caption_embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        WHERE caption_embedding IS NOT NULL
    """)

    # 3. Revert caption_embedding dimension: Vector(1024) → Vector(768)
    op.execute("ALTER TABLE image_embeddings ALTER COLUMN caption_embedding TYPE vector(768)")
