"""
Tests for the embeddings router.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from routers.embeddings import (
    store_embedding,
    search_embeddings,
    search_get,
)
from services.vector_store import SimilarChunk


class TestEmbeddingsEndpoints:
    @pytest.mark.asyncio
    async def test_store_embedding_success(self):
        from routers.embeddings import StoreEmbeddingRequest

        mock_embedding = MagicMock()
        mock_embedding.id = 1
        mock_embedding.repo_full_name = "owner/repo"
        mock_embedding.file_path = "src/foo.py"
        mock_embedding.chunk_text = "def foo(): pass"
        mock_embedding.language = "python"
        mock_embedding.chunk_type = "function"

        mock_session = AsyncMock()

        with patch("core.database.AsyncSessionLocal") as mock_local:
            mock_local.return_value.__aenter__.return_value = mock_session
            mock_local.return_value.__aexit__.return_value = None

            with patch("routers.embeddings.vector_store") as mock_store:
                mock_store.store_code_embedding = AsyncMock(return_value=mock_embedding)

                result = await store_embedding(
                    StoreEmbeddingRequest(
                        repo_full_name="owner/repo",
                        file_path="src/foo.py",
                        chunk_text="def foo(): pass",
                        language="python",
                        chunk_type="function",
                    )
                )

                assert result.id == 1
                assert result.repo_full_name == "owner/repo"

    @pytest.mark.asyncio
    async def test_store_embedding_error(self):
        from routers.embeddings import StoreEmbeddingRequest
        from services.vector_store import VectorStoreError

        mock_session = AsyncMock()

        with patch("core.database.AsyncSessionLocal") as mock_local:
            mock_local.return_value.__aenter__.return_value = mock_session

            with patch("routers.embeddings.vector_store") as mock_store:
                mock_store.store_code_embedding.side_effect = VectorStoreError("Error")

                with pytest.raises(Exception):
                    await store_embedding(
                        StoreEmbeddingRequest(
                            repo_full_name="owner/repo",
                            file_path="src/foo.py",
                            chunk_text="test",
                        )
                    )

    @pytest.mark.asyncio
    async def test_search_embeddings_success(self):
        from routers.embeddings import SearchRequest

        mock_results = [
            SimilarChunk(
                chunk_text="def foo(): pass",
                file_path="src/foo.py",
                language="python",
                similarity=0.85,
                chunk_type="function",
            )
        ]

        mock_session = AsyncMock()

        with patch("core.database.AsyncSessionLocal") as mock_local:
            mock_local.return_value.__aenter__.return_value = mock_session
            mock_local.return_value.__aexit__.return_value = None

            with patch("routers.embeddings.vector_store") as mock_store:
                mock_store.search_similar = AsyncMock(return_value=mock_results)

                result = await search_embeddings(
                    SearchRequest(
                        q="sql injection",
                        repo="owner/repo",
                        top_k=5,
                        threshold=0.6,
                    )
                )

                assert len(result.results) == 1
                assert result.results[0]["similarity"] == 0.85

    @pytest.mark.asyncio
    async def test_search_get_vector_store_error(self):
        from routers.embeddings import SearchRequest
        from services.vector_store import VectorStoreError

        mock_session = AsyncMock()

        with patch("core.database.AsyncSessionLocal") as mock_local:
            mock_local.return_value.__aenter__.return_value = mock_session

            with patch("routers.embeddings.vector_store") as mock_store:
                mock_store.search_similar.side_effect = VectorStoreError("Error")

                with pytest.raises(Exception):
                    await search_get(
                        q="test",
                        repo="owner/repo",
                    )
