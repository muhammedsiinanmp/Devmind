"""
Integration-style tests for the review RAG flow.

The pgvector tables are replaced by in-memory rows, and the Google embedding
API by an httpx.MockTransport that answers batchEmbedContents with a
deterministic hashed bag-of-words vector and counts requests. The real
VectorStore embedding code, diff parsing, review router and background store
task all run, so these need neither Postgres nor an embedding API.
"""

import asyncio
import hashlib
import json
import logging
import math
import re
from collections import Counter
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy.exc import IntegrityError, ProgrammingError

from models.review import ReviewRequest
from routers import review as review_router
from routers.review import analyze_review
from services.vector_store import SimilarChunk, VectorStore


_DIFF_SYNTAX = ("diff --git", "---", "+++", "@@", "Added:", "Removed:", "Context:")


def _fake_embed(text: str) -> list[float]:
    """Bag of code identifiers hashed into 768 dims. Diff headers and section
    labels are ignored, so a raw diff and its parsed hunk embed close
    together, as they would with a real embedding model."""
    code_lines = [
        line for line in text.splitlines() if not line.startswith(_DIFF_SYNTAX)
    ]
    words = Counter(re.findall(r"[a-z_]+", "\n".join(code_lines).lower()))
    vector = [0.0] * 768
    for word, count in words.items():
        vector[int(hashlib.md5(word.encode()).hexdigest(), 16) % 768] += count
    return vector


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


class FakeEmbeddingAPI:
    """Counting stand-in for Google's batchEmbedContents endpoint."""

    def __init__(self):
        self.requests: list[dict] = []
        # set by the fake_store fixture; checked on every embedding call
        self.open_sessions = lambda: 0
        self.sessions_open_during_calls: list[int] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith(":batchEmbedContents")
        body = json.loads(request.content)
        self.requests.append(body)
        self.sessions_open_during_calls.append(self.open_sessions())
        return httpx.Response(
            200,
            json={
                "embeddings": [
                    {"values": _fake_embed(r["content"]["parts"][0]["text"])}
                    for r in body["requests"]
                ]
            },
        )

    def calls(self, task_type: str | None = None) -> int:
        return sum(
            1
            for body in self.requests
            if task_type is None or body["requests"][0]["taskType"] == task_type
        )

    def documents(self) -> list[str]:
        """Texts sent for RETRIEVAL_DOCUMENT embedding (i.e. to be stored)."""
        return [
            r["content"]["parts"][0]["text"]
            for body in self.requests
            for r in body["requests"]
            if r["taskType"] == "RETRIEVAL_DOCUMENT"
        ]


class FakeVectorStore(VectorStore):
    """The real VectorStore with its database methods kept in memory.

    Mirrors the SQL: rows are unique per (repo_full_name, sha256,
    embedding_model), and lookups only see rows of the configured model.
    """

    def __init__(self, api: FakeEmbeddingAPI):
        super().__init__()
        self._client = httpx.AsyncClient(transport=httpx.MockTransport(api.handler))
        self.rows: list[dict] = []
        # file paths whose insert fails at commit (e.g. a concurrent insert of
        # the same sha256 racing past the existence check)
        self.integrity_error_paths: set[str] = set()
        # when set, every insert fails with this error (e.g. a missing column)
        self.insert_error: Exception | None = None
        self.insert_attempts = 0

    def _key(self, row: dict) -> tuple[str, str, str]:
        return (row["repo_full_name"], row["sha256"], row["embedding_model"])

    async def existing_hashes(self, session, repo_full_name, hashes):
        stored = {
            r["sha256"]
            for r in self.rows
            if r["repo_full_name"] == repo_full_name
            and r["embedding_model"] == self.embedding_model
        }
        return {h for h in hashes if h in stored}

    async def insert_code_embedding(
        self,
        session,
        repo_full_name,
        file_path,
        chunk_text,
        embedding,
        sha256,
        language="python",
        chunk_type="function",
        source_ref=None,
    ):
        self.insert_attempts += 1
        if self.insert_error is not None:
            raise self.insert_error
        if file_path in self.integrity_error_paths:
            raise IntegrityError("INSERT", {}, Exception("duplicate key"))
        row = {
            "repo_full_name": repo_full_name,
            "file_path": file_path,
            "chunk_text": chunk_text,
            "language": language,
            "chunk_type": chunk_type,
            "source_ref": source_ref,
            "sha256": sha256,
            "embedding": embedding,
            "embedding_model": self.embedding_model,
        }
        if any(self._key(r) == self._key(row) for r in self.rows):
            raise IntegrityError("INSERT", {}, Exception("duplicate key"))
        self.rows.append(row)

    async def search_similar_by_embedding(
        self,
        session,
        query_embedding,
        repo_full_name,
        top_k=5,
        threshold=0.6,
        exclude_source_ref=None,
    ):
        scored = []
        for row in self.rows:
            if row["repo_full_name"] != repo_full_name:
                continue
            if row["embedding_model"] != self.embedding_model:
                continue
            if exclude_source_ref is not None and row["source_ref"] == (
                exclude_source_ref
            ):
                continue
            scored.append((_cosine(query_embedding, row["embedding"]), row))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [
            SimilarChunk(
                chunk_text=row["chunk_text"],
                file_path=row["file_path"],
                language=row["language"],
                similarity=round(sim, 4),
                chunk_type=row["chunk_type"],
            )
            for sim, row in scored[:top_k]
            if sim >= threshold
        ]


class FakeSession:
    def __init__(self):
        self.rollbacks = 0
        # SQL text of statements executed directly on the session (the fake
        # store's own methods don't use it)
        self.statements: list[str] = []

    async def execute(self, statement):
        self.statements.append(str(statement))

    async def rollback(self):
        self.rollbacks += 1


SESSIONS: list[FakeSession] = []
OPEN_SESSIONS: list[FakeSession] = []


@asynccontextmanager
async def _fake_session():
    session = FakeSession()
    SESSIONS.append(session)
    OPEN_SESSIONS.append(session)
    try:
        yield session
    finally:
        OPEN_SESSIONS.remove(session)


REPO = "owner/repo"

PR1_DIFF = """diff --git a/app/users.py b/app/users.py
--- a/app/users.py
+++ b/app/users.py
@@ -1,1 +1,3 @@
 import db
+def fetch_user(record_id):
+    return db.query("SELECT * FROM users WHERE id = %s", record_id)
"""

PR2_DIFF = """diff --git a/app/orders.py b/app/orders.py
--- a/app/orders.py
+++ b/app/orders.py
@@ -1,1 +1,3 @@
 import db
+def fetch_order(record_id):
+    return db.query("SELECT * FROM orders WHERE id = %s", record_id)
"""

# PR 2 after a second push: the hunk changed, so its text is not a
# near-duplicate of anything stored from the first push.
PR2_DIFF_PUSH2 = """diff --git a/app/orders.py b/app/orders.py
--- a/app/orders.py
+++ b/app/orders.py
@@ -1,1 +1,3 @@
 import db
+def fetch_order(record_id, limit):
+    return db.query("SELECT * FROM orders WHERE id = %s LIMIT %s", record_id, limit)
"""


async def _review(
    diff: str,
    pr_number: int,
    repo: str = REPO,
    files_skipped: list[dict] | None = None,
) -> list[str]:
    """Run POST /review/analyze for one PR and wait for its background tasks.

    files_skipped is what the review agent reports as not reviewed. Returns
    the similar_patterns handed to the review agent.
    """
    agent = AsyncMock(
        return_value={
            "synthesized_comments": [],
            "model_used": "x/y",
            "files_skipped": files_skipped or [],
        }
    )
    with patch("agents.review_agent.run_review_agent", agent):
        await analyze_review(
            ReviewRequest(diff=diff, repo_full_name=repo, pr_number=pr_number),
            secret="unused",
        )
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    await asyncio.gather(*pending)
    return agent.call_args.kwargs["similar_patterns"]


@pytest.fixture
def embedding_api():
    api = FakeEmbeddingAPI()
    api.open_sessions = lambda: len(OPEN_SESSIONS)
    return api


@pytest.fixture
def fake_store(embedding_api):
    store = FakeVectorStore(embedding_api)
    SESSIONS.clear()
    OPEN_SESSIONS.clear()
    with (
        patch("services.vector_store.vector_store", store),
        patch("core.database.AsyncSessionLocal", _fake_session),
    ):
        yield store


class TestRetrievalExcludesCurrentPR:
    @pytest.mark.asyncio
    async def test_reviewing_pr2_never_returns_pr2_chunks(self, fake_store):
        await _review(PR1_DIFF, pr_number=1)

        patterns = await _review(PR2_DIFF, pr_number=2)

        assert patterns, "expected PR 1's similar chunk to be retrieved"
        assert any("app/users.py" in p for p in patterns)
        assert not any("fetch_order" in p for p in patterns)

    @pytest.mark.asyncio
    async def test_re_review_of_pr2_skips_chunks_from_its_earlier_push(
        self, fake_store
    ):
        await _review(PR1_DIFF, pr_number=1)
        await _review(PR2_DIFF, pr_number=2)

        patterns = await _review(PR2_DIFF_PUSH2, pr_number=2)

        assert any("app/users.py" in p for p in patterns)
        assert not any("fetch_order" in p for p in patterns)

    @pytest.mark.asyncio
    async def test_pr_chunks_are_stored_after_review_with_source_ref(self, fake_store):
        await _review(PR1_DIFF, pr_number=1)

        assert fake_store.rows
        assert all(r["source_ref"] == "PR#1" for r in fake_store.rows)
        assert all(r["file_path"] == "app/users.py" for r in fake_store.rows)

    @pytest.mark.asyncio
    async def test_skips_result_that_duplicates_a_current_hunk(self, fake_store):
        # The same hunk landed earlier under PR 1 (e.g. a cherry-pick).
        await _review(PR2_DIFF, pr_number=1)

        patterns = await _review(PR2_DIFF, pr_number=2)

        assert not any("fetch_order" in p for p in patterns)

    @pytest.mark.asyncio
    async def test_skips_untagged_legacy_row_for_same_pr(self, fake_store):
        # Older versions stored the raw diff as file_path "PR#<n>", untagged.
        await fake_store.store_code_embedding(
            None, REPO, "PR#2", PR2_DIFF_PUSH2, language="diff", chunk_type="pr"
        )
        await _review(PR1_DIFF, pr_number=1)

        patterns = await _review(PR2_DIFF, pr_number=2)

        assert any("app/users.py" in p for p in patterns)
        assert not any(p.startswith("PR#2") for p in patterns)


class TestRetrievalLogging:
    @pytest.mark.asyncio
    async def test_logs_path_and_similarity_without_chunk_bodies(
        self, fake_store, caplog
    ):
        await _review(PR1_DIFF, pr_number=1)

        with caplog.at_level(logging.DEBUG):
            await _review(PR2_DIFF, pr_number=2)

        retrieved = [
            r.getMessage()
            for r in caplog.records
            if r.name == "routers.review" and "rag_context.retrieved" in r.msg
        ]
        assert retrieved
        assert any("app/users.py" in m and "similarity=" in m for m in retrieved)
        for record in caplog.records:
            message = record.getMessage()
            assert "fetch_user" not in message
            assert "fetch_order" not in message
            assert "SELECT * FROM" not in message


def _file_diff(i: int) -> str:
    return f"""diff --git a/pkg/mod{i}.py b/pkg/mod{i}.py
--- a/pkg/mod{i}.py
+++ b/pkg/mod{i}.py
@@ -1,1 +1,2 @@
 import os
+value_{i} = os.environ.get("KEY_{i}")
"""


def _diff_with_files(count: int) -> str:
    return "".join(_file_diff(i) for i in range(count))


class TestStoreAfterReview:
    @pytest.mark.asyncio
    async def test_db_error_on_one_chunk_does_not_drop_later_chunks(self, fake_store):
        fake_store.integrity_error_paths.add("pkg/mod0.py")

        await _review(_diff_with_files(3), pr_number=7)

        stored = sorted(r["file_path"] for r in fake_store.rows)
        assert stored == ["pkg/mod1.py", "pkg/mod2.py"]
        assert sum(s.rollbacks for s in SESSIONS) == 1

    @pytest.mark.asyncio
    async def test_background_store_task_is_referenced_until_done(self, fake_store):
        agent = AsyncMock(
            return_value={"synthesized_comments": [], "model_used": "x/y"}
        )
        before = set(review_router._background_tasks)
        with patch("agents.review_agent.run_review_agent", agent):
            await analyze_review(
                ReviewRequest(diff=PR1_DIFF, repo_full_name=REPO, pr_number=1),
                secret="unused",
            )

        tasks = set(review_router._background_tasks) - before
        assert len(tasks) == 1
        await asyncio.gather(*tasks)
        assert not tasks & review_router._background_tasks
        assert fake_store.rows


class TestNearDuplicateFilterCoversWholeDiff:
    @pytest.mark.asyncio
    async def test_hunk_beyond_the_first_20_is_still_filtered(self, fake_store):
        # Hunk 21 of the current diff was stored earlier under another PR.
        await _review(_file_diff(20), pr_number=1)

        patterns = await _review(_diff_with_files(21), pr_number=2)

        assert not any("value_20" in p for p in patterns)


def _clear_embedding_cache(store: VectorStore) -> None:
    """Empty the in-process embedding cache, as after a restart."""
    store._cache = type(store._cache)(maxsize=1000)


class TestBatchedEmbeddingCalls:
    @pytest.mark.asyncio
    async def test_20_hunk_review_makes_at_most_2_embedding_calls(
        self, fake_store, embedding_api
    ):
        await _review(_diff_with_files(20), pr_number=3)

        assert len(embedding_api.requests) <= 2
        assert embedding_api.calls("RETRIEVAL_QUERY") == 1
        assert embedding_api.calls("RETRIEVAL_DOCUMENT") == 1
        assert all(len(body["requests"]) == 20 for body in embedding_api.requests)
        assert len(fake_store.rows) == 20

    @pytest.mark.asyncio
    async def test_re_review_of_unchanged_diff_embeds_and_stores_nothing_new(
        self, fake_store, embedding_api
    ):
        await _review(_diff_with_files(20), pr_number=3)
        assert len(fake_store.rows) == 20
        rows_after_first = list(fake_store.rows)
        document_calls_after_first = embedding_api.calls("RETRIEVAL_DOCUMENT")
        assert document_calls_after_first == 1
        # A new process (or an evicted cache) must still skip stored chunks:
        # only the sha256 check may prevent the document-embedding call.
        _clear_embedding_cache(fake_store)

        await _review(_diff_with_files(20), pr_number=3)

        assert fake_store.rows == rows_after_first
        assert embedding_api.calls("RETRIEVAL_DOCUMENT") == document_calls_after_first

    @pytest.mark.asyncio
    async def test_only_chunks_not_yet_stored_are_embedded(
        self, fake_store, embedding_api
    ):
        await _review(_diff_with_files(2), pr_number=3)
        assert len(fake_store.rows) == 2
        embedding_api.requests.clear()
        _clear_embedding_cache(fake_store)

        await _review(_diff_with_files(3), pr_number=3)

        documents = embedding_api.documents()
        assert len(documents) == 1
        assert "value_2" in documents[0]

    @pytest.mark.asyncio
    async def test_no_db_session_is_open_during_embedding_calls(
        self, fake_store, embedding_api
    ):
        await _review(PR1_DIFF, pr_number=1)
        await _review(PR2_DIFF, pr_number=2)

        assert embedding_api.calls("RETRIEVAL_QUERY") == 2
        assert embedding_api.calls("RETRIEVAL_DOCUMENT") == 2
        assert embedding_api.sessions_open_during_calls == [0, 0, 0, 0]


class TestIterativeScan:
    @pytest.mark.asyncio
    async def test_search_session_enables_hnsw_iterative_scan_once(self, fake_store):
        await _review(_diff_with_files(3), pr_number=3)

        executed = [s.statements for s in SESSIONS]
        assert executed.count(["SET LOCAL hnsw.iterative_scan = relaxed_order"]) == 1


class TestStoreStopsOnSystemicDbErrors:
    @pytest.mark.asyncio
    async def test_error_that_hits_every_insert_stops_after_the_first(
        self, fake_store, embedding_api
    ):
        # e.g. source_ref missing because 0001 wasn't applied. The sha256
        # lookup selects only sha256, so it succeeds; the batch is embedded
        # once and the first insert fails.
        fake_store.insert_error = ProgrammingError(
            "INSERT", {}, Exception("column source_ref does not exist")
        )

        await _review(_diff_with_files(5), pr_number=7)

        assert embedding_api.calls("RETRIEVAL_DOCUMENT") == 1
        assert fake_store.insert_attempts == 1
        assert fake_store.rows == []

    @pytest.mark.asyncio
    async def test_failed_duplicate_check_makes_no_document_embedding_call(
        self, fake_store, embedding_api
    ):
        # e.g. the table doesn't exist yet, or the database is unreachable.
        async def missing_table(session, repo_full_name, hashes):
            raise ProgrammingError(
                "SELECT", {}, Exception('relation "code_embeddings" does not exist')
            )

        fake_store.existing_hashes = missing_table

        await _review(_diff_with_files(5), pr_number=7)

        assert embedding_api.calls("RETRIEVAL_DOCUMENT") == 0
        assert fake_store.insert_attempts == 0


OTHER_REPO = "owner/other-repo"

LOCKFILE_DIFF = """diff --git a/uv.lock b/uv.lock
--- a/uv.lock
+++ b/uv.lock
@@ -1,1 +1,2 @@
 version = 1
+lockfile_marker = "abc"
"""


class TestDedupPerRepository:
    @pytest.mark.asyncio
    async def test_same_chunk_in_two_repos_is_stored_for_both(
        self, fake_store, embedding_api
    ):
        await _review(PR1_DIFF, pr_number=1, repo=REPO)
        _clear_embedding_cache(fake_store)

        await _review(PR1_DIFF, pr_number=5, repo=OTHER_REPO)

        repos = sorted(r["repo_full_name"] for r in fake_store.rows)
        assert repos == [OTHER_REPO, REPO]
        assert len({r["sha256"] for r in fake_store.rows}) == 1
        assert embedding_api.calls("RETRIEVAL_DOCUMENT") == 2

    @pytest.mark.asyncio
    async def test_chunk_stored_for_another_repo_is_retrievable_in_this_one(
        self, fake_store
    ):
        await _review(PR1_DIFF, pr_number=1, repo=OTHER_REPO)
        await _review(PR1_DIFF, pr_number=1, repo=REPO)

        patterns = await _review(PR2_DIFF, pr_number=2, repo=REPO)

        assert any("app/users.py" in p for p in patterns)


class TestEmbeddingModelSeparation:
    """The in-memory store mirrors the SQL filters; the real queries are
    checked in test_vector_store.py and test_vector_store_pgvector.py."""

    @pytest.mark.asyncio
    async def test_search_never_returns_rows_from_another_model(self, fake_store):
        fake_store.embedding_model = "text-embedding-004"
        await _review(PR1_DIFF, pr_number=1)
        assert [r["embedding_model"] for r in fake_store.rows] == ["text-embedding-004"]
        fake_store.embedding_model = "gemini-embedding-001"
        _clear_embedding_cache(fake_store)

        patterns = await _review(PR2_DIFF, pr_number=2)

        assert patterns == []

    @pytest.mark.asyncio
    async def test_chunk_stored_with_another_model_is_stored_again(
        self, fake_store, embedding_api
    ):
        fake_store.embedding_model = "text-embedding-004"
        await _review(PR1_DIFF, pr_number=1)
        fake_store.embedding_model = "gemini-embedding-001"
        _clear_embedding_cache(fake_store)

        await _review(PR1_DIFF, pr_number=1)

        models = sorted(r["embedding_model"] for r in fake_store.rows)
        assert models == ["gemini-embedding-001", "text-embedding-004"]


class TestSkippedFilesAreNotEmbedded:
    @pytest.mark.asyncio
    async def test_generated_files_are_not_embedded(self, fake_store, embedding_api):
        await _review(
            LOCKFILE_DIFF + PR1_DIFF,
            pr_number=1,
            files_skipped=[{"file_path": "uv.lock", "reason": "generated"}],
        )

        assert [r["file_path"] for r in fake_store.rows] == ["app/users.py"]
        assert not any("lockfile_marker" in d for d in embedding_api.documents())

    @pytest.mark.asyncio
    async def test_generated_files_are_not_embedded_even_if_not_reported(
        self, fake_store, embedding_api
    ):
        # The review skip patterns apply on their own, too.
        await _review(LOCKFILE_DIFF + PR1_DIFF, pr_number=1)

        assert [r["file_path"] for r in fake_store.rows] == ["app/users.py"]
        assert not any("lockfile_marker" in d for d in embedding_api.documents())

    @pytest.mark.asyncio
    @pytest.mark.parametrize("reason", ["batch_limit", "deadline"])
    async def test_files_the_review_did_not_reach_are_not_embedded(
        self, fake_store, embedding_api, reason
    ):
        await _review(
            _diff_with_files(3),
            pr_number=1,
            files_skipped=[{"file_path": "pkg/mod2.py", "reason": reason}],
        )

        stored = sorted(r["file_path"] for r in fake_store.rows)
        assert stored == ["pkg/mod0.py", "pkg/mod1.py"]
        assert not any("value_2" in d for d in embedding_api.documents())

    @pytest.mark.asyncio
    async def test_skipped_files_do_not_use_up_the_20_chunk_cap(self, fake_store):
        diff = _diff_with_files(21)
        skipped = [{"file_path": "pkg/mod0.py", "reason": "batch_limit"}]

        await _review(diff, pr_number=1, files_skipped=skipped)

        stored = {r["file_path"] for r in fake_store.rows}
        assert len(stored) == 20
        assert "pkg/mod0.py" not in stored
        assert "pkg/mod20.py" in stored


class TestFeedbackRetrieval:
    """Issue #74: feedback examples are searched with the code-search queries."""

    @pytest.mark.asyncio
    async def test_reuses_the_query_embeddings_without_another_embedding_call(
        self, fake_store, embedding_api
    ):
        from services.feedback_store import FeedbackContext

        search = AsyncMock(return_value=FeedbackContext(rejected=["example"]))
        with patch("services.feedback_store.search_feedback", search):
            _, _, feedback = await review_router._prepare_rag_context(
                ReviewRequest(diff=PR1_DIFF, repo_full_name=REPO, pr_number=1)
            )

        assert feedback.rejected == ["example"]
        assert embedding_api.calls("RETRIEVAL_QUERY") == 1
        session, embeddings, repo, model = search.call_args.args
        assert (repo, model) == (REPO, fake_store.embedding_model)
        # Security review of #109, rule 2: this PR's own feedback is left out.
        assert search.call_args.kwargs["exclude_source_ref"] == "PR#1"
        [query_text] = embedding_api.requests[0]["requests"]
        assert embeddings == [_fake_embed(query_text["content"]["parts"][0]["text"])]

    @pytest.mark.asyncio
    async def test_search_failure_gives_no_examples_and_keeps_code_context(
        self, fake_store, caplog
    ):
        await _review(PR1_DIFF, pr_number=1)  # stores PR 1's hunk
        search = AsyncMock(side_effect=RuntimeError("no feedback_embeddings"))
        with (
            patch("services.feedback_store.search_feedback", search),
            caplog.at_level(logging.WARNING, logger="routers.review"),
        ):
            _, patterns, feedback = await review_router._prepare_rag_context(
                ReviewRequest(diff=PR2_DIFF, repo_full_name=REPO, pr_number=2)
            )

        assert not feedback
        assert len(patterns) == 1
        assert "review.feedback_context_failed" in caplog.text

    @pytest.mark.asyncio
    async def test_no_query_embeddings_no_search(self, fake_store):
        search = AsyncMock()
        diff = "diff --git a/x.min.js b/x.min.js\n--- a/x.min.js\n+++ b/x.min.js\n"
        with patch("services.feedback_store.search_feedback", search):
            _, _, feedback = await review_router._prepare_rag_context(
                ReviewRequest(diff=diff, repo_full_name=REPO, pr_number=1)
            )

        assert not feedback
        search.assert_not_called()

    @pytest.mark.asyncio
    async def test_review_hands_the_examples_to_the_agent(self, fake_store):
        from services.feedback_store import FeedbackContext

        context = FeedbackContext(rejected=["example"])
        agent = AsyncMock(
            return_value={"synthesized_comments": [], "model_used": "x/y"}
        )
        with (
            patch(
                "services.feedback_store.search_feedback",
                AsyncMock(return_value=context),
            ),
            patch("agents.review_agent.run_review_agent", agent),
        ):
            await analyze_review(
                ReviewRequest(diff=PR1_DIFF, repo_full_name=REPO, pr_number=1),
                secret="unused",
            )

        assert agent.call_args.kwargs["feedback"] is context
