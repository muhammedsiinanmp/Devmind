"""
SQLAlchemy models for code embeddings with pgvector.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from pgvector.sqlalchemy import Vector


class Base(DeclarativeBase):
    pass


class CodeEmbedding(Base):
    """Code chunk embedding stored in pgvector."""

    __tablename__ = "code_embeddings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    repo_full_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(20), nullable=False, default="python")
    chunk_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="function"
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(768), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )

    __table_args__ = (
        Index(
            "ix_code_embeddings_repo",
            "repo_full_name",
        ),
        Index(
            "ix_code_embeddings_language",
            "language",
        ),
    )


class ReviewEmbedding(Base):
    """Review/feedback embedding stored in pgvector."""

    __tablename__ = "review_embeddings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    review_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, unique=True, index=True
    )
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    feedback_text: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(20), nullable=False, default="python")
    embedding: Mapped[list[float]] = mapped_column(Vector(768), nullable=False)
    extra_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )

    __table_args__ = (
        Index(
            "ix_review_embeddings_user",
            "user_id",
        ),
    )
