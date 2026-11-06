import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Identity,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import text as sql_text  # `text` is also a Resume column name
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import EMBED_DIM

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    source: Mapped[str] = mapped_column(String(32))  # "remotive", "remoteok", "greenhouse"
    source_id: Mapped[str] = mapped_column(String(255))
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    company: Mapped[str] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    remote: Mapped[bool] = mapped_column(Boolean, server_default=sql_text("false"))
    salary: Mapped[str | None] = mapped_column(Text)
    seniority: Mapped[str | None] = mapped_column(String(16))
    description: Mapped[str] = mapped_column(Text)
    skills: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=sql_text("'{}'"))
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # sha256 of the normalized title + company + description; catches the same
    # posting appearing on two sources and tells ingestion when to re-embed.
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIM))
    # Which model produced `embedding`; vectors from different models can't be compared.
    embed_model: Mapped[str | None] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=sql_text("true"))
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_jobs_source_source_id"),
        Index("ix_jobs_active_posted_at", "is_active", "posted_at"),
        Index(
            "ix_jobs_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class Resume(Base):
    __tablename__ = "resumes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    # Extracted text with emails and phone numbers already stripped (Phase 2).
    text: Mapped[str] = mapped_column(Text)
    parsed: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIM))
    embed_model: Mapped[str | None] = mapped_column(String(128))
    # File facts recorded before redaction, for ATS checks: kind, pages, columns,
    # tables, whether an email/phone/LinkedIn was present; plus parse method/warnings.
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=sql_text("'{}'::jsonb"))
    # Indexed for the 24-hour deletion sweep.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), server_default=sql_text("'running'"))
    fetched: Mapped[int] = mapped_column(Integer, server_default=sql_text("0"))
    inserted: Mapped[int] = mapped_column(Integer, server_default=sql_text("0"))
    updated: Mapped[int] = mapped_column(Integer, server_default=sql_text("0"))
    skipped: Mapped[int] = mapped_column(Integer, server_default=sql_text("0"))
    errors: Mapped[int] = mapped_column(Integer, server_default=sql_text("0"))
    # [{"source": "remoteok", "message": "..."}], so one failing source is visible
    # without failing the whole run.
    error_details: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=sql_text("'[]'::jsonb")
    )
