"""
Vector store service using pgvector.

Provides embedding storage and similarity search using cosine distance.
"""

import hashlib
import logging
from dataclasses import dataclass
from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from models.embeddings import CodeEmbedding, ReviewEmbedding

logger = logging.getLogger(__name__)
settings = get_settings()


class VectorStoreError(Exception):
    """Raised on vector store errors."""

    pass


@dataclass
class SimilarChunk:
    """Similar code chunk from search."""

    chunk_text: str
    file_path: str
    language: str
    similarity: float
    chunk_type: str


class VectorStore:
    """Vector store using pgvector for embeddings."""

    def __init__(self):
        self.embedding_dims = 768
        self.embedding_model = "text-embedding-004"
        self._cache: dict[str, list[float]] = {}

    async def generate_embedding(
        self,
        text: str,
        use_cache: bool = True,
    ) -> list[float]:
        """
        Generate embedding using Google AI.

        Args:
            text: Text to embed
            use_cache: Whether to use embedding cache

        Returns:
            768-dimensional embedding vector
        """
        text_hash = hashlib.sha256(text.encode()).hexdigest()

        if use_cache and text_hash in self._cache:
            logger.info("vector_store.cache_hit hash=%s", text_hash[:8])
            return self._cache[text_hash]

        if not settings.google_ai_api_key:
            raise VectorStoreError("Google AI API key not configured")

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:embedContent",
                headers={
                    "Authorization": f"Bearer {settings.google_ai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "content": {
                        "type": "PLAIN_TEXT",
                        "text": text,
                    }
                },
            )

            if response.status_code != 200:
                raise VectorStoreError(
                    f"Failed to generate embedding: {response.status_code}"
                )

            data = response.json()
            embedding_values = data.get("embedding", {}).get("values", [])

            if len(embedding_values) != self.embedding_dims:
                raise VectorStoreError(
                    f"Invalid embedding dimension: {len(embedding_values)}"
                )

            if use_cache:
                self._cache[text_hash] = embedding_values

            return embedding_values

    async def store_code_embedding(
        self,
        session: AsyncSession,
        repo_full_name: str,
        file_path: str,
        chunk_text: str,
        language: str = "python",
        chunk_type: str = "function",
    ) -> CodeEmbedding:
        """
        Store code chunk embedding.

        Args:
            session: Database session
            repo_full_name: Repository full name (owner/repo)
            file_path: File path in repository
            chunk_text: Code chunk text
            language: Programming language
            chunk_type: Type of chunk (function, class, etc.)

        Returns:
            Created CodeEmbedding
        """
        embedding = await self.generate_embedding(chunk_text)
        text_hash = hashlib.sha256(chunk_text.encode()).hexdigest()

        existing = await session.execute(
            select(CodeEmbedding).where(CodeEmbedding.sha256 == text_hash)
        )
        if existing.scalar_one_or_none:
            raise VectorStoreError(f"Embedding already exists: {text_hash[:8]}")

        code_embedding = CodeEmbedding(
            repo_full_name=repo_full_name,
            file_path=file_path,
            chunk_text=chunk_text,
            language=language,
            chunk_type=chunk_type,
            embedding=embedding,
            sha256=text_hash,
        )

        session.add(code_embedding)
        await session.commit()
        await session.refresh(code_embedding)

        logger.info(
            "vector_store.stored repo=%s file=%s",
            repo_full_name,
            file_path,
        )

        return code_embedding

    async def search_similar(
        self,
        session: AsyncSession,
        query_text: str,
        repo_full_name: str,
        top_k: int = 5,
        threshold: float = 0.6,
    ) -> list[SimilarChunk]:
        """
        Search for similar code chunks.

        Args:
            session: Database session
            query_text: Query text to search
            repo_full_name: Repository to search in
            top_k: Number of results to return
            threshold: Minimum similarity threshold (0-1)

        Returns:
            List of similar chunks (empty if no results above threshold)
        """
        query_embedding = await self.generate_embedding(query_text)

        stmt = (
            select(CodeEmbedding)
            .where(CodeEmbedding.repo_full_name == repo_full_name)
            .order_by(CodeEmbedding.embedding.cosine_distance(query_embedding))
            .limit(top_k)
        )

        result = await session.execute(stmt)
        embeddings = result.scalars().all()

        results = []
        for emb in embeddings:
            similarity = 1 - CodeEmbedding.embedding.cosine_distance(
                query_embedding, emb.embedding
            )

            if similarity >= threshold:
                results.append(
                    SimilarChunk(
                        chunk_text=emb.chunk_text,
                        file_path=emb.file_path,
                        language=emb.language,
                        similarity=similarity,
                        chunk_type=emb.chunk_type,
                    )
                )

        logger.info(
            "vector_store.search query=%s results=%d",
            query_text[:30],
            len(results),
        )

        return results

    async def store_review_embedding(
        self,
        session: AsyncSession,
        review_id: int,
        user_id: int,
        code_hash: str,
        feedback_text: str,
        language: str = "python",
        extra_data: Optional[dict] = None,
    ) -> ReviewEmbedding:
        """
        Store review embedding.

        Args:
            session: Database session
            review_id: Review ID
            user_id: User ID
            code_hash: Hash of reviewed code
            feedback_text: Feedback text
            language: Programming language
            extra_data: Additional metadata

        Returns:
            Created ReviewEmbedding
        """
        embedding = await self.generate_embedding(feedback_text)

        review_embedding = ReviewEmbedding(
            review_id=review_id,
            user_id=user_id,
            code_hash=code_hash,
            feedback_text=feedback_text,
            language=language,
            embedding=embedding,
            extra_data=extra_data,
        )

        session.add(review_embedding)
        await session.commit()
        await session.refresh(review_embedding)

        return review_embedding


vector_store = VectorStore()
