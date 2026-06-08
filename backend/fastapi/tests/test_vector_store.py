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

    def test_embedding_model_read_from_settings(self):
        """embedding_model must come from Settings, not a hardcoded string."""
        with patch("services.vector_store.settings") as mock_settings:
            mock_settings.embedding_model = "text-embedding-preview-0409"
            store = VectorStore()
            assert store.embedding_model == "text-embedding-preview-0409"

    @pytest.mark.asyncio
    async def test_generate_embedding_success_sends_task_type(self):
        """Request body must include taskType: RETRIEVAL_DOCUMENT by default."""
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

            call_kwargs = mock_instance.post.call_args.kwargs
            assert call_kwargs["json"]["taskType"] == "RETRIEVAL_DOCUMENT"

    @pytest.mark.asyncio
    async def test_generate_embedding_retrieval_query_task_type(self):
        """search_similar should send taskType: RETRIEVAL_QUERY."""
        store = VectorStore()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"embedding": {"values": [0.2] * 768}}

        with patch("services.vector_store.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = mock_response

            embedding = await store.generate_embedding(
                "search query", task_type="RETRIEVAL_QUERY"
            )

            assert len(embedding) == 768
            call_kwargs = mock_instance.post.call_args.kwargs
            assert call_kwargs["json"]["taskType"] == "RETRIEVAL_QUERY"

    @pytest.mark.asyncio
    async def test_generate_embedding_cache_keys_differ_by_task_type(self):
        """Same text with different task types must not share a cache entry."""
        store = VectorStore()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"embedding": {"values": [0.1] * 768}}

        with patch("services.vector_store.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = mock_response

            await store.generate_embedding("hello", task_type="RETRIEVAL_DOCUMENT")
            await store.generate_embedding("hello", task_type="RETRIEVAL_QUERY")

            # Two distinct API calls — cache keys must differ
            assert mock_instance.post.call_count == 2

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
                mock_session.execute.return_value.scalar_one_or_none = MagicMock(
                    return_value=None
                )

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
