"""Modelos ORM de documents y chunks.

Reflejan la migración alembic/versions/0001_initial_schema.py; `alembic check`
avisa si se desalinean. La columna se llama "metadata" en la base de datos,
pero el atributo Python es `metadata_`: `metadata` está reservado en los
modelos declarativos de SQLAlchemy (es el registro de tablas).
"""

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Dimensión de text-embedding-3-small. Gemini se pide a esta misma dimensión
# (output_dimensionality) para que los dos proveedores quepan en la columna.
EMBEDDING_DIMENSION = 1536


class Base(DeclarativeBase):
    pass


class Document(Base):
    """Un presupuesto histórico ingestado."""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_path: Mapped[str] = mapped_column(Text, nullable=False, index=True, unique=True)
    document_type: Mapped[str] = mapped_column(String(50), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, server_default=text("'{}'"), nullable=False
    )

    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )


class Chunk(Base):
    """Un fragmento de un documento con su embedding."""

    __tablename__ = "chunks"
    # GIN sobre el JSONB: filtrar por claves arbitrarias sin migrar el esquema.
    __table_args__ = (Index("ix_chunks_metadata_gin", "metadata", postgresql_using="gin"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Nullable: deja la puerta abierta a rellenar el embedding después; aquí
    # siempre se inserta junto al chunk.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSION), nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, server_default=text("'{}'"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    document: Mapped[Document] = relationship(back_populates="chunks")
