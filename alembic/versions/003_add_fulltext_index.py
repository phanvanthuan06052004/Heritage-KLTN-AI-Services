"""Add GIN index for full-text search on source_chunks.

Revision ID: 003
Revises: 002
"""

from alembic import op

# revision identifiers
revision = "003"
down_revision = "002_rbac"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # GIN index for PostgreSQL full-text search
    # Using 'simple' config (no stemming) — better for Vietnamese content
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_source_chunks_fulltext
        ON source_chunks
        USING GIN (to_tsvector('simple', content))
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_source_chunks_fulltext")
