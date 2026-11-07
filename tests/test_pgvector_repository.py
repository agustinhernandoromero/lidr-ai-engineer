"""DocumentRepository y modelos ORM sin Postgres: sesión falsa y SQL compilada."""

from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from app.db.models import EMBEDDING_DIMENSION, TEXT_SEARCH_CONFIG, Base, Document
from app.db.repository import DocumentRepository, DuplicateSourcePath
from tests.pgvector_fakes import unit_vector


class FakeSession:
    """Lo mínimo de AsyncSession que usa el repositorio."""

    def __init__(self, commit_error: Exception | None = None, scalar_result=None):
        self.commit_error = commit_error
        self.scalar_result = scalar_result
        self.added = []
        self.committed = False
        self.rolled_back = False
        self.statements = []

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        if self.commit_error is not None:
            raise self.commit_error
        self.committed = True

    async def rollback(self):
        self.rolled_back = True

    async def scalar(self, stmt):
        self.statements.append(stmt)
        return self.scalar_result

    async def execute(self, stmt):
        self.statements.append(stmt)
        return SimpleNamespace(all=list)


def _integrity_error() -> IntegrityError:
    return IntegrityError("INSERT INTO documents ...", {}, Exception("duplicate key value"))


def _document() -> Document:
    return Document(source_path="data/budgets/BUD-1.json", document_type="historical_budget")


@pytest.mark.asyncio
async def test_save_adds_and_commits_once():
    session = FakeSession()
    document = _document()
    await DocumentRepository(session).save(document)

    assert session.added == [document]
    assert session.committed
    assert not session.rolled_back


@pytest.mark.asyncio
async def test_save_turns_unique_violation_into_duplicate_with_existing_id():
    session = FakeSession(commit_error=_integrity_error(), scalar_result=42)

    with pytest.raises(DuplicateSourcePath) as excinfo:
        await DocumentRepository(session).save(_document())

    assert excinfo.value.document_id == 42
    assert session.rolled_back  # la sesión queda usable para la consulta del id


@pytest.mark.asyncio
async def test_save_reraises_integrity_errors_that_are_not_a_duplicate():
    # Otra restricción (p. ej. FK): no hay documento con ese source_path.
    session = FakeSession(commit_error=_integrity_error(), scalar_result=None)

    with pytest.raises(IntegrityError):
        await DocumentRepository(session).save(_document())
    assert session.rolled_back


@pytest.mark.asyncio
async def test_find_document_id_filters_by_source_path():
    session = FakeSession(scalar_result=9)
    assert await DocumentRepository(session).find_document_id("a.json") == 9

    sql = str(session.statements[0].compile(dialect=postgresql.dialect()))
    assert "FROM documents" in sql
    assert "documents.source_path =" in sql


@pytest.mark.asyncio
async def test_nearest_chunks_orders_by_cosine_operator_and_limits_to_k():
    session = FakeSession()
    rows = await DocumentRepository(session).nearest_chunks(unit_vector(0), k=5)

    assert rows == []
    [stmt] = session.statements
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    assert "FROM chunks" in sql
    assert "<=>" in sql  # el operador que usará un índice HNSW con vector_cosine_ops
    assert "ORDER BY chunks.embedding <=>" in sql
    assert stmt._limit == 5


@pytest.mark.asyncio
async def test_lexical_chunks_matches_tsvector_with_english_or_query():
    session = FakeSession()
    rows = await DocumentRepository(session).lexical_chunks("Stripe subscription billing", k=50)

    assert rows == []
    [stmt] = session.statements
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    assert "FROM chunks" in sql
    assert "chunks.content_tsv @@ CAST(replace(CAST(plainto_tsquery('english'" in sql
    assert "'&'" in sql or "%(replace_1)s" in sql  # AND turned into OR
    assert "ts_rank(chunks.content_tsv" in sql
    assert "ORDER BY ts_rank(" in sql and "DESC" in sql
    assert stmt._limit == 50


def test_source_path_is_unique_so_the_race_ends_in_409():
    [index] = [i for i in Document.__table__.indexes if i.name == "ix_documents_source_path"]
    assert index.unique


def test_chunks_cascade_and_vector_column_shape():
    chunks = Base.metadata.tables["chunks"]
    [fk] = chunks.c.document_id.foreign_keys
    assert fk.column.table.name == "documents"
    assert fk.ondelete == "CASCADE"
    assert chunks.c.embedding.type.dim == EMBEDDING_DIMENSION == 1536
    assert chunks.c.embedding.nullable


def test_no_vector_index_yet_only_relational_and_text_ones():
    # La línea base es el sequential scan; HNSW se añadirá y se medirá después.
    # content_tsv (sesión 10) es el índice GIN de la búsqueda por palabras, no vectorial.
    indexed_columns = {
        column.name for index in Base.metadata.tables["chunks"].indexes for column in index.columns
    }
    assert indexed_columns == {"document_id", "chunk_type", "metadata", "content_tsv"}


def test_migration_matches_models():
    """Los mismos índices y columnas en la migración y en los modelos."""
    from pathlib import Path

    versions = Path(__file__).resolve().parent.parent / "alembic" / "versions"
    migration = (versions / "0001_initial_schema.py").read_text(encoding="utf-8")
    all_migrations = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(versions.glob("*.py"))
    )

    # Los índices pueden venir de cualquier migración (0002 añade el de content_tsv).
    for table in ("documents", "chunks"):
        for index in Base.metadata.tables[table].indexes:
            assert f'"{index.name}"' in all_migrations, index.name
    assert '["source_path"], unique=True' in migration
    # The text search configuration is the same in the model, the queries and migration 0002.
    fulltext = (versions / "0002_chunks_fulltext_search.py").read_text(encoding="utf-8")
    assert f"to_tsvector('{TEXT_SEARCH_CONFIG}', content)" in fulltext
    assert TEXT_SEARCH_CONFIG == "english"
    assert f"Vector({EMBEDDING_DIMENSION})" in migration
    assert "DROP EXTENSION" not in migration.split("def downgrade")[1]
