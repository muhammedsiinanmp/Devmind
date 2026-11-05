"""
Integration-style tests for the review RAG flow.

The pgvector store is replaced by an in-memory fake with a deterministic
bag-of-words embedder, so these run without Postgres or an embedding API.
Everything else (diff parsing, the review router, the background store task)
is the real code.
"""

import asyncio
import hashlib
import logging
import math
import re
from collections import Counter
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest

from models.review import ReviewRequest
from routers.review import analyze_review
from services.vector_store import SimilarChunk, VectorStoreError


_DIFF_SYNTAX = ("diff --git", "---", "+++", "@@", "Added:", "Removed:", "Context:")


def _fake_embed(text: str) -> Counter:
    """Bag of code identifiers. Diff headers and section labels are ignored,
    so a raw diff and its parsed hunk embed close together, as they would with
    a real embedding model."""
    code_lines = [
        line for line in text.splitlines() if not line.startswith(_DIFF_SYNTAX)
    ]
    return Counter(re.findall(r"[a-z_]+", "\n".join(code_lines).lower()))


def _cosine(a: Counter, b: Counter) -> float:
    dot = sum(a[k] * b[k] for k in a)
    norm = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(
        sum(v * v for v in b.values())
    )
    return dot / norm if norm else 0.0


class FakeVectorStore:
    """In-memory stand-in for services.vector_store.VectorStore."""

    def __init__(self):
        self.rows: list[dict] = []

    async def store_code_embedding(
        self,
        session,
        repo_full_name,
        file_path,
        chunk_text,
        language="python",
        chunk_type="function",
        source_ref=None,
    ):
        sha = hashlib.sha256(chunk_text.encode()).hexdigest()
        if any(r["sha256"] == sha for r in self.rows):
            raise VectorStoreError(f"Embedding already exists: {sha[:8]}")
        self.rows.append(
            {
                "repo_full_name": repo_full_name,
                "file_path": file_path,
                "chunk_text": chunk_text,
                "language": language,
                "chunk_type": chunk_type,
                "source_ref": source_ref,
                "sha256": sha,
                "embedding": _fake_embed(chunk_text),
            }
        )

    async def search_similar(
        self,
        session,
        query_text,
        repo_full_name,
        top_k=5,
        threshold=0.6,
        exclude_source_ref=None,
    ):
        query = _fake_embed(query_text)
        scored = []
        for row in self.rows:
            if row["repo_full_name"] != repo_full_name:
                continue
            if exclude_source_ref is not None and row["source_ref"] == (
                exclude_source_ref
            ):
                continue
            scored.append((_cosine(query, row["embedding"]), row))
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


@asynccontextmanager
async def _fake_session():
    yield object()


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


async def _review(diff: str, pr_number: int) -> list[str]:
    """Run POST /review/analyze for one PR and wait for its background tasks.

    Returns the similar_patterns handed to the review agent.
    """
    agent = AsyncMock(return_value={"synthesized_comments": [], "model_used": "x/y"})
    with patch("agents.review_agent.run_review_agent", agent):
        await analyze_review(
            ReviewRequest(diff=diff, repo_full_name=REPO, pr_number=pr_number),
            secret="unused",
        )
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    await asyncio.gather(*pending)
    return agent.call_args.kwargs["similar_patterns"]


@pytest.fixture
def fake_store():
    store = FakeVectorStore()
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
