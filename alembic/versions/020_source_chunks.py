"""Add raw source chunks and embeddings.

Revision ID: 020
Revises: 019
Create Date: 2026-05-23
"""

import sqlalchemy as sa
from pgvector.sqlalchemy import HALFVEC, Vector
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None

SUPPORTED_DIMENSIONS = (768, 1024, 1536, 3072)
_HALFVEC_DIMS = {3072}


def _embedding_table_name(dim: int) -> str:
    return f"source_chunk_embeddings_{dim}"


def _embedding_column(dim: int):
    if dim in _HALFVEC_DIMS:
        return sa.Column("embedding", HALFVEC(dim), nullable=False)
    return sa.Column("embedding", Vector(dim), nullable=False)


def _hnsw_ops(dim: int) -> str:
    return "halfvec_cosine_ops" if dim in _HALFVEC_DIMS else "vector_cosine_ops"


def upgrade() -> None:
    op.create_table(
        "source_chunks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("source_id", "chunk_index", name="uq_source_chunks_source_idx"),
    )
    op.create_index("ix_source_chunks_source_id", "source_chunks", ["source_id"])
    op.create_index(
        "ix_source_chunks_source_page",
        "source_chunks",
        ["source_id", "page_number"],
    )

    for dim in SUPPORTED_DIMENSIONS:
        table = _embedding_table_name(dim)
        op.create_table(
            table,
            sa.Column(
                "chunk_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("source_chunks.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("model_spec_id", sa.String(128), nullable=False),
            sa.Column("content_hash", sa.String(64), nullable=False),
            _embedding_column(dim),
            sa.Column(
                "embedded_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("chunk_id", "model_spec_id"),
        )
        op.execute(
            f"""
            CREATE INDEX ix_{table}_hnsw
            ON {table}
            USING hnsw (embedding {_hnsw_ops(dim)})
            WITH (m = 16, ef_construction = 64)
            """
        )
        op.create_index(f"ix_{table}_model", table, ["model_spec_id"])


def downgrade() -> None:
    for dim in SUPPORTED_DIMENSIONS:
        table = _embedding_table_name(dim)
        op.drop_index(f"ix_{table}_model", table_name=table)
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_hnsw")
        op.drop_table(table)

    op.drop_index("ix_source_chunks_source_page", table_name="source_chunks")
    op.drop_index("ix_source_chunks_source_id", table_name="source_chunks")
    op.drop_table("source_chunks")
