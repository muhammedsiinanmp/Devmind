"""
Tests for vector store service - additional edge cases.
"""

import hashlib
import logging

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.exc import ProgrammingError

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
    async def test_store_code_embedding_duplicate_skips_embedding(self):
        """A chunk whose sha256 is already stored raises before any
        embedding call is made."""
        store = VectorStore()
        mock_session = AsyncMock()

        with patch.object(
            store, "generate_embedding", new_callable=AsyncMock
        ) as mock_gen:
            existing = MagicMock()
            existing.scalars.return_value.all.return_value = [
                hashlib.sha256(b"test code").hexdigest()
            ]
            mock_session.execute = AsyncMock(return_value=existing)

            with pytest.raises(VectorStoreError, match="already exists"):
                await store.store_code_embedding(
                    session=mock_session,
                    repo_full_name="owner/repo",
                    file_path="src/foo.py",
                    chunk_text="test code",
                )

            mock_gen.assert_not_awaited()
            mock_session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_search_similar_does_not_log_query_text(self, caplog):
        """The query is code from the diff under review; keep it out of logs."""
        store = VectorStore()
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch.object(
            store, "generate_embedding", new_callable=AsyncMock
        ) as mock_gen:
            mock_gen.return_value = [0.1] * 768
            with caplog.at_level(logging.DEBUG, logger="services.vector_store"):
                await store.search_similar(
                    session=mock_session,
                    query_text="password = 'hunter2'",
                    repo_full_name="owner/repo",
                    exclude_source_ref="PR#2",
                )

        messages = [r.getMessage() for r in caplog.records]
        assert any("vector_store.search" in m for m in messages)
        assert not any("hunter2" in m for m in messages)


class _RecordingSession:
    """Session double that records SQL and returns canned search rows."""

    def __init__(self, rows=(), fail_set=False):
        self.statements: list[str] = []
        self.rows = list(rows)
        self.fail_set = fail_set
        self.rollbacks = 0

    async def execute(self, statement):
        sql = str(statement)
        self.statements.append(sql)
        if sql.startswith("SET LOCAL") and self.fail_set:
            raise ProgrammingError(
                sql, {}, Exception('unrecognized parameter "hnsw.iterative_scan"')
            )
        result = MagicMock()
        result.all.return_value = self.rows
        return result

    async def rollback(self):
        self.rollbacks += 1


def _row(path: str, distance: float):
    emb = MagicMock(
        chunk_text="x", file_path=path, language="python", chunk_type="hunk"
    )
    return (emb, distance)


class TestIterativeScan:
    @pytest.mark.asyncio
    async def test_search_similar_enables_iterative_scan_before_searching(self):
        store = VectorStore()
        session = _RecordingSession()

        with patch.object(
            store, "generate_embedding", new=AsyncMock(return_value=[0.1] * 768)
        ):
            await store.search_similar(session, "q", "owner/repo")

        assert session.statements[0] == (
            "SET LOCAL hnsw.iterative_scan = relaxed_order"
        )
        assert "FROM code_embeddings" in session.statements[1]

    @pytest.mark.asyncio
    async def test_unsupported_setting_is_logged_once_and_search_still_runs(
        self, caplog
    ):
        store = VectorStore()
        session = _RecordingSession(rows=[_row("a.py", 0.1)], fail_set=True)

        with patch.object(
            store, "generate_embedding", new=AsyncMock(return_value=[0.1] * 768)
        ):
            with caplog.at_level(logging.WARNING, logger="services.vector_store"):
                first = await store.search_similar(session, "q", "owner/repo")
                second = await store.search_similar(session, "q", "owner/repo")

        assert [c.file_path for c in first] == ["a.py"]
        assert [c.file_path for c in second] == ["a.py"]
        assert session.rollbacks == 2
        warnings = [
            r.getMessage()
            for r in caplog.records
            if "iterative_scan_unavailable" in r.getMessage()
        ]
        assert len(warnings) == 1

    @pytest.mark.asyncio
    async def test_results_are_sorted_by_similarity(self):
        # relaxed_order may return rows slightly out of distance order
        store = VectorStore()
        session = _RecordingSession(rows=[_row("b.py", 0.3), _row("a.py", 0.1)])

        results = await store.search_similar_by_embedding(
            session, [0.1] * 768, "owner/repo"
        )

        assert [c.file_path for c in results] == ["a.py", "b.py"]


class TestClose:
    @pytest.mark.asyncio
    async def test_embedding_after_close_raises_and_opens_no_client(self):
        store = VectorStore()
        store._get_client()

        await store.aclose()

        with pytest.raises(VectorStoreError, match="closed"):
            await store.generate_embedding("text")
        assert store._client is None
