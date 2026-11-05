"""Full-text search on chunks: generated tsvector column and GIN index.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-05

The budgets are written in Spanish, so the text search configuration is
'spanish' (Spanish stemming and stopwords). The configuration name is passed
explicitly, so the stored values do not depend on default_text_search_config.
PostgreSQL keeps the column in sync with `content` on every write.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE chunks
        ADD COLUMN content_tsv tsvector
        GENERATED ALWAYS AS (to_tsvector('spanish', content)) STORED
        """
    )
    op.create_index("ix_chunks_content_tsv", "chunks", ["content_tsv"], postgresql_using="gin")


def downgrade() -> None:
    op.drop_index("ix_chunks_content_tsv", table_name="chunks")
    op.drop_column("chunks", "content_tsv")
