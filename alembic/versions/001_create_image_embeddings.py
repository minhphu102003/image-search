"""create image_embeddings table

Revision ID: 001
Revises:
Create Date: 2026-06-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "image_embeddings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("image_id", sa.String(64), unique=True, nullable=False),
        sa.Column("embedding", Vector(1024), nullable=False),
        sa.Column("caption_embedding", Vector(768), nullable=True),
        sa.Column("model_name", sa.String(64), nullable=False, server_default="siglip2-384"),
        sa.Column("caption", sa.Text, nullable=True),
        sa.Column("file_path", sa.String(512), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.execute("""
        CREATE INDEX idx_image_embeddings_hnsw
        ON image_embeddings
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)

    op.execute("""
        CREATE INDEX idx_image_embeddings_caption_hnsw
        ON image_embeddings
        USING hnsw (caption_embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        WHERE caption_embedding IS NOT NULL
    """)

    op.create_index("idx_image_embeddings_model_name", "image_embeddings", ["model_name"])
    op.create_index("idx_image_embeddings_status", "image_embeddings", ["status"])


def downgrade() -> None:
    op.drop_table("image_embeddings")
    op.execute("DROP EXTENSION IF EXISTS vector")
