"""
Tests for vector store service.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.vector_store import (
    VectorStore,
    VectorStoreError,
    SimilarChunk,
)
from models.embeddings import CodeEmbedding, ReviewEmbedding


class TestSimilarChunk:
    def test_similar_chunk_dataclass(self):
        chunk = SimilarChunk(
            chunk_text="def foo(): pass",
            file_path="src/foo.py",
            language="python",
            similarity=0.85,
            chunk_type="function",
        )
        assert chunk.chunk_text == "def foo(): pass"
        assert chunk.similarity == 0.85


class TestVectorStore:
    def test_vector_store_init(self):
        store = VectorStore()
        assert store.embedding_dims == 768
        assert store.embedding_model == "text-embedding-004"

    @pytest.mark.asyncio
    async def test_generate_embedding_success(self):
        store = VectorStore()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"embedding": {"values": [0.1] * 768}}

        with patch("services.vector_store.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = mock_response

            embedding = await store.generate_embedding("test text")

            assert len(embedding) == 768
            assert embedding[0] == 0.1

    @pytest.mark.asyncio
    async def test_generate_embedding_cache_hit(self):
        store = VectorStore()

        test_embedding = [0.1] * 768
        test_hash = "abc123"

        store._cache[test_hash] = test_embedding

        with patch("services.vector_store.hashlib.sha256") as mock_hash:
            mock_hash.return_value.hexdigest.return_value = test_hash

            embedding = await store.generate_embedding("cached text")

            assert embedding == test_embedding

    @pytest.mark.asyncio
    async def test_generate_embedding_no_api_key(self):
        store = VectorStore()

        with patch("services.vector_store.settings") as mock_settings:
            mock_settings.google_ai_api_key = ""

            with pytest.raises(VectorStoreError):
                await store.generate_embedding("test text")

    @pytest.mark.asyncio
    async def test_generate_embedding_invalid_dimension(self):
        store = VectorStore()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"embedding": {"values": [0.1] * 100}}

        with patch("services.vector_store.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = mock_response

            with pytest.raises(VectorStoreError):
                await store.generate_embedding("test text")

    @pytest.mark.asyncio
    async def test_store_code_embedding(self):
        store = VectorStore()

        mock_embedding = [0.1] * 768
        mock_session = AsyncMock()

        with patch.object(
            store, "generate_embedding", new_callable=AsyncMock
        ) as mock_gen:
            mock_gen.return_value = mock_embedding

            with patch("services.vector_store.hashlib.sha256") as mock_hash:
                mock_hash.return_value.hexdigest.return_value = "test_hash"

                mock_code_embedding = MagicMock()
                mock_code_embedding.id = 1

                mock_session.execute = AsyncMock()
                mock_session.execute.return_value.scalar_one_or_none = None

                with patch("services.vector_store.select", return_value=MagicMock()):
                    with patch(
                        "services.vector_store.CodeEmbedding",
                        return_value=mock_code_embedding,
                    ):
                        await store.store_code_embedding(
                            session=mock_session,
                            repo_full_name="owner/repo",
                            file_path="src/foo.py",
                            chunk_text="test code",
                        )


class TestVectorStoreError:
    def test_vector_store_error(self):
        with pytest.raises(VectorStoreError):
            raise VectorStoreError("Test error")


class TestModels:
    def test_code_embedding_model(self):
        emb = CodeEmbedding(
            repo_full_name="owner/repo",
            file_path="src/foo.py",
            chunk_text="def foo(): pass",
            language="python",
            chunk_type="function",
            embedding=[0.1] * 768,
            sha256="abc123",
        )
        assert emb.repo_full_name == "owner/repo"
        assert emb.language == "python"

    def test_review_embedding_model(self):
        emb = ReviewEmbedding(
            review_id=1,
            user_id=1,
            code_hash="abc123",
            feedback_text="Good code",
            language="python",
            embedding=[0.1] * 768,
        )
        assert emb.review_id == 1
        assert emb.user_id == 1
