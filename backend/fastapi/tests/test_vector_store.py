"""
Tests for vector store service.
"""

import json

import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.dialects import postgresql

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


def _store_with_fake_api(values_for=lambda text: [0.1] * 768, status_code=200):
    """VectorStore whose shared HTTP client answers batchEmbedContents from a
    MockTransport. Returns the store and the list of captured requests."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if status_code != 200:
            return httpx.Response(status_code, text="quota exceeded")
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "embeddings": [
                    {"values": values_for(r["content"]["parts"][0]["text"])}
                    for r in body["requests"]
                ]
            },
        )

    store = VectorStore()
    store._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return store, requests


def _body(request: httpx.Request) -> dict:
    return json.loads(request.content)


class TestVectorStore:
    def test_vector_store_init(self):
        store = VectorStore()
        assert store.embedding_dims == 768
        assert store.embedding_model == "gemini-embedding-001"

    def test_embedding_model_read_from_settings(self):
        """embedding_model must come from Settings, not a hardcoded string."""
        with patch("services.vector_store.settings") as mock_settings:
            mock_settings.embedding_model = "text-embedding-preview-0409"
            store = VectorStore()
            assert store.embedding_model == "text-embedding-preview-0409"

    @pytest.mark.asyncio
    async def test_generate_embedding_success_sends_task_type(self):
        """Request body must include taskType: RETRIEVAL_DOCUMENT by default."""
        store, requests = _store_with_fake_api()

        embedding = await store.generate_embedding("test text")

        assert len(embedding) == 768
        assert embedding[0] == 0.1
        [request] = _body(requests[0])["requests"]
        assert request["taskType"] == "RETRIEVAL_DOCUMENT"
        assert request["content"] == {"parts": [{"text": "test text"}]}

    @pytest.mark.asyncio
    async def test_request_sends_task_type_and_dimensions_at_the_top_level(self):
        """Top-level taskType and outputDimensionality, not embedContentConfig:
        on 2026-11-06 the live API ignored embedContentConfig's
        outputDimensionality and returned 3072 values."""
        store, requests = _store_with_fake_api()

        await store.generate_embeddings(["a"], task_type="RETRIEVAL_QUERY")

        assert _body(requests[0]) == {
            "requests": [
                {
                    "model": "models/gemini-embedding-001",
                    "content": {"parts": [{"text": "a"}]},
                    "taskType": "RETRIEVAL_QUERY",
                    "outputDimensionality": 768,
                }
            ]
        }

    @pytest.mark.asyncio
    async def test_generate_embedding_retrieval_query_task_type(self):
        """search_similar should send taskType: RETRIEVAL_QUERY."""
        store, requests = _store_with_fake_api()

        embedding = await store.generate_embedding(
            "search query", task_type="RETRIEVAL_QUERY"
        )

        assert len(embedding) == 768
        [request] = _body(requests[0])["requests"]
        assert request["taskType"] == "RETRIEVAL_QUERY"

    @pytest.mark.asyncio
    async def test_request_asks_for_768_dimensions_from_the_configured_model(self):
        """gemini-embedding-001 defaults to 3072 values; the column is
        Vector(768), so every request must ask for 768."""
        store, requests = _store_with_fake_api()

        await store.generate_embeddings(["a", "b"], task_type="RETRIEVAL_QUERY")

        [request] = requests
        assert request.url.path == (
            "/v1beta/models/gemini-embedding-001:batchEmbedContents"
        )
        for item in _body(request)["requests"]:
            assert item["outputDimensionality"] == 768
            assert item["model"] == "models/gemini-embedding-001"

    @pytest.mark.asyncio
    async def test_generate_embeddings_sends_one_request_and_keeps_order(self):
        store, requests = _store_with_fake_api(
            values_for=lambda text: [float(len(text))] * 768
        )

        vectors = await store.generate_embeddings(["a", "bbb", "cc"])

        assert len(requests) == 1
        texts = [
            r["content"]["parts"][0]["text"] for r in _body(requests[0])["requests"]
        ]
        assert texts == ["a", "bbb", "cc"]
        assert [v[0] for v in vectors] == [1.0, 3.0, 2.0]

    @pytest.mark.asyncio
    async def test_generate_embeddings_sends_only_uncached_texts_once(self):
        store, requests = _store_with_fake_api()
        await store.generate_embeddings(["cached"])

        vectors = await store.generate_embeddings(["cached", "new", "new"])

        assert len(vectors) == 3
        texts = [
            r["content"]["parts"][0]["text"] for r in _body(requests[1])["requests"]
        ]
        assert texts == ["new"]

    @pytest.mark.asyncio
    async def test_generate_embeddings_all_cached_makes_no_request(self):
        store, requests = _store_with_fake_api()
        await store.generate_embeddings(["a", "b"])

        await store.generate_embeddings(["b", "a"])

        assert len(requests) == 1

    @pytest.mark.asyncio
    async def test_generate_embeddings_splits_large_batches(self):
        store, requests = _store_with_fake_api()
        store.MAX_BATCH_SIZE = 2

        vectors = await store.generate_embeddings(["a", "b", "c"])

        assert len(vectors) == 3
        assert [len(_body(r)["requests"]) for r in requests] == [2, 1]

    @pytest.mark.asyncio
    async def test_calls_share_one_http_client(self):
        store, _ = _store_with_fake_api()
        client = store._get_client()

        await store.generate_embedding("one")
        await store.generate_embedding("two")

        assert store._get_client() is client

    @pytest.mark.asyncio
    async def test_generate_embedding_cache_keys_differ_by_task_type(self):
        """Same text with different task types must not share a cache entry."""
        store, requests = _store_with_fake_api()

        await store.generate_embedding("hello", task_type="RETRIEVAL_DOCUMENT")
        await store.generate_embedding("hello", task_type="RETRIEVAL_QUERY")

        # Two distinct API calls — cache keys must differ
        assert len(requests) == 2

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
        store, _ = _store_with_fake_api(values_for=lambda text: [0.1] * 100)

        with pytest.raises(VectorStoreError):
            await store.generate_embedding("test text")

    @pytest.mark.asyncio
    async def test_generate_embedding_api_error(self):
        store, _ = _store_with_fake_api(status_code=429)

        with pytest.raises(VectorStoreError, match="429"):
            await store.generate_embedding("test text")

    @pytest.mark.asyncio
    async def test_generate_embeddings_wrong_count_raises(self):
        store = VectorStore()
        store._client = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200, json={"embeddings": [{"values": [0.1] * 768}]}
                )
            )
        )

        with pytest.raises(VectorStoreError, match="Expected 2 embeddings"):
            await store.generate_embeddings(["a", "b"])

    @pytest.mark.asyncio
    async def test_store_code_embedding(self):
        store = VectorStore()

        mock_embedding = [0.1] * 768
        mock_session = AsyncMock()

        with patch.object(
            store, "generate_embedding", new_callable=AsyncMock
        ) as mock_gen:
            mock_gen.return_value = mock_embedding

            mock_code_embedding = MagicMock()
            mock_code_embedding.id = 1

            store.existing_hashes = AsyncMock(return_value=set())
            mock_session.add = MagicMock()  # Session.add is synchronous

            with patch(
                "services.vector_store.CodeEmbedding",
                return_value=mock_code_embedding,
            ) as model:
                result = await store.store_code_embedding(
                    session=mock_session,
                    repo_full_name="owner/repo",
                    file_path="src/foo.py",
                    chunk_text="test code",
                )

            assert result is mock_code_embedding
            assert model.call_args.kwargs["embedding"] == mock_embedding
            mock_session.add.assert_called_once_with(mock_code_embedding)
            mock_session.commit.assert_awaited_once()


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


class _StatementSession:
    """Records the statements a VectorStore method executes."""

    def __init__(self):
        self.statements = []
        self.added = []

    async def execute(self, statement):
        self.statements.append(statement)
        result = MagicMock()
        result.all.return_value = []
        result.scalars.return_value.all.return_value = []
        return result

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        pass

    async def refresh(self, obj):
        pass


def _where(statement) -> tuple[str, list]:
    """SQL text after WHERE, and the bound values, as Postgres would get them."""
    compiled = statement.compile(dialect=postgresql.dialect())
    return str(compiled).split("WHERE", 1)[1], list(compiled.params.values())


class TestEmbeddingModelTag:
    """Rows are tagged with the model that embedded them; vectors from another
    model are never compared with the configured model's. The queries also
    run against real pgvector in test_vector_store_pgvector.py (opt-in)."""

    @pytest.mark.asyncio
    async def test_search_only_reads_rows_of_the_configured_model(self):
        store = VectorStore()
        session = _StatementSession()

        await store.search_similar_by_embedding(session, [0.1] * 768, "owner/repo")

        [statement] = session.statements
        where, values = _where(statement)
        assert "code_embeddings.embedding_model = " in where
        assert "gemini-embedding-001" in values
        assert "owner/repo" in values

    @pytest.mark.asyncio
    async def test_duplicate_check_is_per_repository_and_model(self):
        store = VectorStore()
        session = _StatementSession()

        await store.existing_hashes(session, "owner/repo", ["abc"])

        [statement] = session.statements
        where, values = _where(statement)
        assert "code_embeddings.repo_full_name = " in where
        assert "code_embeddings.embedding_model = " in where
        assert "owner/repo" in values
        assert "gemini-embedding-001" in values

    @pytest.mark.asyncio
    async def test_inserted_row_records_the_configured_model(self):
        with patch("services.vector_store.settings") as mock_settings:
            mock_settings.embedding_model = "some-other-model"
            store = VectorStore()
        session = _StatementSession()

        row = await store.insert_code_embedding(
            session, "owner/repo", "a.py", "x = 1", [0.1] * 768, "abc"
        )

        assert session.added == [row]
        assert row.embedding_model == "some-other-model"

    def test_sha256_is_unique_per_repository_and_model_not_globally(self):
        table = CodeEmbedding.__table__
        assert not table.c.sha256.unique
        unique_column_sets = [
            [c.name for c in index.columns] for index in table.indexes if index.unique
        ]
        assert unique_column_sets == [["repo_full_name", "sha256", "embedding_model"]]
        assert not table.c.embedding_model.nullable
