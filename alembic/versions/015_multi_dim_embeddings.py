"""Multi-dimension embedding storage.

Drops the hardcoded `wiki_pages.embedding vector(768)` column and replaces it
with one table per supported dimension:

  - wiki_page_embeddings_768
  - wiki_page_embeddings_1024
  - wiki_page_embeddings_1536
  - wiki_page_embeddings_3072

Plus an `embedding_jobs` table to track re-embed background jobs (atomic flip
of `app_config.active_embedding_model_spec_id` on completion).

No backfill: after this migration, semantic search returns zero rows until an
admin selects an embedding model in Settings and the re-embed job completes.
This is intentional — the previous on-disk vectors were 768d Google embeddings
that may not match the chosen new model anyway.

Revision ID: 015
Revises: 014
Create Date: 2026-05-07
"""

import sqlalchemy as sa
from pgvector.sqlalchemy import HALFVEC, Vector
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


# pgvector HNSW supports up to 2000 dims for `vector`, but up to 4000 dims for
# `halfvec`. So 3072d models (OpenAI 3-large, Gemini-embedding-001) use halfvec
# storage + halfvec_cosine_ops index. Smaller dims keep full-precision `vector`.
SUPPORTED_DIMENSIONS = (768, 1024, 1536, 3072)
_HALFVEC_DIMS = {3072}


def _embedding_table_name(dim: int) -> str:
    return f"wiki_page_embeddings_{dim}"


def _embedding_column(dim: int):
    if dim in _HALFVEC_DIMS:
        return sa.Column("embedding", HALFVEC(dim), nullable=False)
    return sa.Column("embedding", Vector(dim), nullable=False)


def _hnsw_ops(dim: int) -> str:
    return "halfvec_cosine_ops" if dim in _HALFVEC_DIMS else "vector_cosine_ops"


def upgrade() -> None:
    # 1. Drop old single-column embedding storage on wiki_pages.
    op.execute("DROP INDEX IF EXISTS ix_wiki_pages_embedding_hnsw")
    op.drop_column("wiki_pages", "embedding")

    # 2. Per-dimension embedding tables. One row per (page, model_spec_id).
    for dim in SUPPORTED_DIMENSIONS:
        table = _embedding_table_name(dim)
        op.create_table(
            table,
            sa.Column(
                "page_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("wiki_pages.id", ondelete="CASCADE"),
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
            sa.PrimaryKeyConstraint("page_id", "model_spec_id"),
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

    # 3. Embedding job tracking for background re-embed.
    op.create_table(
        "embedding_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("model_spec_id", sa.String(128), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending",
        ),  # pending | running | completed | failed | cancelled
        sa.Column("total_pages", sa.Integer, nullable=False, server_default="0"),
        sa.Column("done_pages", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_embedding_jobs_status", "embedding_jobs", ["status", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_embedding_jobs_status", table_name="embedding_jobs")
    op.drop_table("embedding_jobs")

    for dim in SUPPORTED_DIMENSIONS:
        table = _embedding_table_name(dim)
        op.drop_index(f"ix_{table}_model", table_name=table)
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_hnsw")
        op.drop_table(table)

    op.add_column(
        "wiki_pages",
        sa.Column("embedding", Vector(768), nullable=True),
    )
    op.execute(
        """
        CREATE INDEX ix_wiki_pages_embedding_hnsw
        ON wiki_pages
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )
