"""
SQLAlchemy models for code embeddings with pgvector.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Index, String, Text
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
    # Model that produced `embedding`. Vectors from different models aren't
    # comparable, so searches and the duplicate check only use rows with the
    # configured model (migrations/sql/0003_code_embeddings_model_tag.sql).
    embedding_model: Mapped[str] = mapped_column(String(100), nullable=False)
    # sha256 of chunk_text. Unique per repository and model, not globally.
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    # Where the chunk came from, e.g. "PR#12". Retrieval for a PR excludes rows
    # with that PR's source_ref so a review never retrieves its own diff.
    source_ref: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )

    __table_args__ = (
        # Also created by migrations/sql/0003_code_embeddings_model_tag.sql.
        Index(
            "ux_code_embeddings_repo_sha256_model",
            "repo_full_name",
            "sha256",
            "embedding_model",
            unique=True,
        ),
        Index(
            "ix_code_embeddings_repo",
            "repo_full_name",
        ),
        Index(
            "ix_code_embeddings_language",
            "language",
        ),
        # Serves ORDER BY cosine distance in similarity search. Also created
        # by migrations/sql/0002_code_embeddings_hnsw_index.sql.
        Index(
            "ix_code_embeddings_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class FeedbackEmbedding(Base):
    """
    A DevMind comment developers accepted or rejected, embedded with its code
    hunk. Created by migrations/sql/0004_feedback_embeddings.sql.
    """

    __tablename__ = "feedback_embeddings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    repo_full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Django's ReviewComment id.
    comment_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    signal: Mapped[str] = mapped_column(String(10), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    code_hunk: Mapped[str] = mapped_column(Text, nullable=False, default="")
    embedding: Mapped[list[float]] = mapped_column(Vector(768), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(100), nullable=False)
    # PR the comment was on ("PR#12"); that PR's reviews leave the row out.
    source_ref: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )

    __table_args__ = (
        Index(
            "ux_feedback_embeddings_comment_model",
            "comment_id",
            "embedding_model",
            unique=True,
        ),
        Index(
            "ix_feedback_embeddings_repo_model",
            "repo_full_name",
            "embedding_model",
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
