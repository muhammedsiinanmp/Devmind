"""
Tests for vector store service - additional edge cases.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.vector_store import VectorStore, VectorStoreError


class TestVectorStoreEdgeCases:
    @pytest.mark.asyncio
    async def test_search_similar_empty_results(self):
        """Test search returns empty when no results above threshold."""
        store = VectorStore()

        mock_query_emb = [0.1] * 768

        mock_code_emb = MagicMock()
        mock_code_emb.chunk_text = "test"
        mock_code_emb.file_path = "test.py"
        mock_code_emb.language = "python"
        mock_code_emb.chunk_type = "function"
        mock_code_emb.embedding = [0.1] * 768

        mock_session = AsyncMock()

        with patch.object(
            store, "generate_embedding", new_callable=AsyncMock
        ) as mock_gen:
            mock_gen.return_value = mock_query_emb

            with patch("services.vector_store.select", return_value=MagicMock()):
                mock_result = MagicMock()
                mock_result.scalars.return_value.all.return_value = []

                mock_session.execute = AsyncMock(return_value=mock_result)

                results = await store.search_similar(
                    session=mock_session,
                    query_text="unknown code",
                    repo_full_name="owner/repo",
                )

                assert results == []

    @pytest.mark.asyncio
    async def test_store_review_embedding(self):
        """Test storing a review embedding."""
        store = VectorStore()

        mock_query_emb = [0.1] * 768

        mock_session = AsyncMock()

        with patch.object(
            store, "generate_embedding", new_callable=AsyncMock
        ) as mock_gen:
            mock_gen.return_value = mock_query_emb

            with patch(
                "services.vector_store.ReviewEmbedding", return_value=MagicMock()
            ):
                await store.store_review_embedding(
                    session=mock_session,
                    review_id=1,
                    user_id=1,
                    code_hash="abc123",
                    feedback_text="Good code",
                )

    @pytest.mark.asyncio
    async def test_store_code_embedding_duplicate(self):
        """Test duplicate embedding error."""
        store = VectorStore()

        mock_query_emb = [0.1] * 768
        mock_session = AsyncMock()

        with patch.object(
            store, "generate_embedding", new_callable=AsyncMock
        ) as mock_gen:
            mock_gen.return_value = mock_query_emb

            with patch("services.vector_store.hashlib.sha256") as mock_hash:
                mock_hash.return_value.hexdigest.return_value = "test_hash"

                with patch("services.vector_store.select", return_value=MagicMock()):
                    mock_existing = MagicMock()
                    mock_existing.scalar_one_or_none = MagicMock()

                    mock_session.execute = AsyncMock(return_value=mock_existing)

                    with pytest.raises(VectorStoreError):
                        await store.store_code_embedding(
                            session=mock_session,
                            repo_full_name="owner/repo",
                            file_path="src/foo.py",
                            chunk_text="test code",
                        )
