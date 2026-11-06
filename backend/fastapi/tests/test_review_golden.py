"""
Golden test: a diff that fits in one batch gets the same prompts as before
file batching (A5).

tests/golden/small_diff_prompts.json holds the exact messages the analyzers
sent for SMALL_DIFF before batching existed, through the agent alone (the
eval harness path) and through POST /review/analyze (the router path, with
retrieved similar patterns). The committed eval cassettes are keyed on these
prompts, so any change here also breaks `make eval`.

Regenerate only on purpose, after a prompt change that re-records the
cassettes: ``A5_WRITE_GOLDEN=1 uv run pytest tests/test_review_golden.py``.
"""

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from models.review import ReviewRequest

GOLDEN = Path(__file__).parent / "golden" / "small_diff_prompts.json"

SMALL_DIFF = """diff --git a/app/users.py b/app/users.py
--- a/app/users.py
+++ b/app/users.py
@@ -1,4 +1,6 @@
 import db

 def get_user(user_id):
-    return db.query("SELECT * FROM users WHERE id = %s", user_id)
+    sql = f"SELECT * FROM users WHERE id = {user_id}"
+    return db.query(sql)
+
diff --git a/app/views.js b/app/views.js
--- a/app/views.js
+++ b/app/views.js
@@ -10,3 +10,4 @@ function render(el, name) {
   const title = document.createElement("h1");
-  title.textContent = name;
+  title.innerHTML = name;
+  el.appendChild(title);
 }
"""


def _response():
    from services.llm_client import LLMResponse

    return LLMResponse(
        content='{"findings": []}',
        model_used="test/model",
        provider="test",
        prompt_tokens=1,
        completion_tokens=1,
    )


class _Capture:
    def __init__(self):
        self.calls: list[dict] = []

    async def __call__(self, messages, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        return _response()

    def sorted_calls(self) -> list[dict]:
        return sorted(self.calls, key=lambda c: c["messages"][0]["content"])


async def _agent_path() -> list[dict]:
    from agents.review_agent import run_review_agent

    capture = _Capture()
    with patch("agents.review_agent.llm_client") as client:
        client.generate = capture
        await run_review_agent(diff_text=SMALL_DIFF, repo_full_name="o/r")
    return capture.sorted_calls()


class _StubStore:
    async def generate_embeddings(self, texts, task_type=None):
        return [[0.0] for _ in texts]

    async def enable_iterative_scan(self, session):
        return None

    async def search_similar_by_embedding(self, **kwargs):
        from services.vector_store import SimilarChunk

        return [
            SimilarChunk(
                chunk_text='cursor.execute("SELECT * FROM t WHERE id=" + i)',
                file_path="lib/legacy.py",
                language="python",
                similarity=0.9,
                chunk_type="hunk",
            )
        ]


@asynccontextmanager
async def _session():
    yield object()


async def _router_path() -> list[dict]:
    from routers.review import analyze_review

    capture = _Capture()
    with (
        patch("agents.review_agent.llm_client") as client,
        patch("services.vector_store.vector_store", _StubStore()),
        patch("core.database.AsyncSessionLocal", _session),
        patch("routers.review.store_review_async", AsyncMock()),
    ):
        client.generate = capture
        await analyze_review(
            ReviewRequest(diff=SMALL_DIFF, repo_full_name="o/r", pr_number=3),
            secret="unused",
        )
    return capture.sorted_calls()


@pytest.mark.asyncio
async def test_small_diff_prompts_are_byte_identical_to_before_batching():
    captured = {"agent": await _agent_path(), "router": await _router_path()}

    if os.environ.get("A5_WRITE_GOLDEN"):
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(captured, indent=2, ensure_ascii=False) + "\n")

    assert captured == json.loads(GOLDEN.read_text())
    # The router's prompt carries the retrieved pattern; the agent's doesn't.
    assert all(len(calls) == 3 for calls in captured.values())
    assert "lib/legacy.py" in captured["router"][0]["messages"][1]["content"]
