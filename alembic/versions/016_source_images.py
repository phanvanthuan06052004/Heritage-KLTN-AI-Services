"""source_images: persist extracted images with stable IDs.

Adds the `source_images` table — one row per image extracted from a source
during ingestion. Holds the MinIO object key, vision-AI caption, and ordering
metadata. Wiki page content_md references images by id via `image://<uuid>`
markers placed by the wiki compiler.

Revision ID: 016
Revises: 015
Create Date: 2026-05-07
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_images",
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
        sa.Column("minio_key", sa.Text, nullable=False),
        sa.Column("page_number", sa.Integer, nullable=True),
        sa.Column("image_index", sa.Integer, nullable=False),
        sa.Column("caption", sa.Text, nullable=True),
        sa.Column("content_type", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("source_id", "image_index", name="uq_source_images_source_idx"),
    )
    op.create_index("ix_source_images_source_id", "source_images", ["source_id"])


def downgrade() -> None:
    op.drop_index("ix_source_images_source_id", table_name="source_images")
    op.drop_table("source_images")
