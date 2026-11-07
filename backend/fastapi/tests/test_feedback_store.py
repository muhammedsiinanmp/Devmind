"""
Feedback examples (issue #74): formatting, selection and POST /feedback/upsert.
The database and embedding API are replaced by mocks; the SQL itself is
covered by tests/test_vector_store_pgvector.py when PGVECTOR_TEST_URL is set.
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest

from core.config import get_settings
from models.embeddings import FeedbackEmbedding
from routers.review import _chunk_text
from services.feedback_store import (
    FeedbackExample,
    MAX_BODY_CHARS,
    MAX_CODE_LINES,
    document_text,
    feedback_context,
    format_feedback_example,
    select_examples,
)

HUNK = "@@ -1,2 +1,3 @@\n import os\n+query = f'SELECT * FROM t WHERE id={uid}'\n x = 1"


def _row(comment_id: int, signal: str, body: str = "b") -> FeedbackEmbedding:
    return FeedbackEmbedding(
        comment_id=comment_id,
        signal=signal,
        repo_full_name="o/r",
        file_path=f"f{comment_id}.py",
        category="security",
        severity="error",
        body=body,
        code_hunk="+x = 1",
        embedding_model="m",
    )


class TestFormatFeedbackExample:
    def test_lists_location_comment_and_code(self):
        text = format_feedback_example(
            FeedbackExample(
                file_path="app/db.py",
                category="security",
                severity="error",
                body="SQL injection via f-string.",
                code="+q = f'...'",
                similarity=0.8312,
            )
        )
        assert text == (
            "app/db.py (security, error, similarity 0.83)\n"
            "Comment: SQL injection via f-string.\n"
            "Code:\n"
            "+q = f'...'"
        )

    def test_without_code_or_similarity(self):
        text = format_feedback_example(
            FeedbackExample(
                file_path="a.py", category="quality", severity="info", body="x"
            )
        )
        assert text == "a.py (quality, info)\nComment: x"

    def test_long_body_and_code_are_cut(self):
        text = format_feedback_example(
            FeedbackExample(
                file_path="a.py",
                category="quality",
                severity="info",
                body="y" * (MAX_BODY_CHARS + 50),
                code="\n".join(f"+line {i}" for i in range(MAX_CODE_LINES + 5)),
            )
        )
        assert "y" * MAX_BODY_CHARS + " [cut]" in text
        assert "[5 more lines cut]" in text
        assert f"+line {MAX_CODE_LINES}" not in text


class TestSelectExamples:
    def test_best_per_signal_above_threshold(self):
        rows = [
            (_row(1, "rejected"), 0.95),
            (_row(2, "rejected"), 0.90),
            (_row(3, "accepted"), 0.80),
            (_row(4, "accepted"), 0.50),  # under the threshold
            (_row(1, "rejected"), 0.70),  # same row found by another query
        ]
        accepted, rejected = select_examples(rows, top_k=1, threshold=0.7)
        assert [e.file_path for e in accepted] == ["f3.py"]
        assert [(e.file_path, e.similarity) for e in rejected] == [("f1.py", 0.95)]

    def test_row_keeps_its_best_similarity(self):
        rows = [(_row(1, "accepted"), 0.71), (_row(1, "accepted"), 0.88)]
        accepted, _ = select_examples(rows, threshold=0.7)
        assert [e.similarity for e in accepted] == [0.88]

    def test_nothing_close_enough_is_empty(self):
        assert select_examples([(_row(1, "rejected"), 0.2)]) == ([], [])

    def test_empty_context_is_falsy(self):
        assert not feedback_context([], [])
        assert feedback_context([], [FeedbackExample("a", "b", "c", "d")])


class TestDocumentText:
    def test_hunk_is_rendered_like_review_queries(self):
        from services.code_parser import parse_diff

        diff = f"diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n{HUNK}"
        expected = _chunk_text(parse_diff(diff)[0])

        assert document_text("app.py", HUNK, "body", _chunk_text) == expected
        assert "Added:" in expected

    def test_without_hunk_the_body_is_embedded(self):
        assert document_text("app.py", "", "the body", _chunk_text) == "the body"


def _headers():
    return {"X-Internal-Secret": get_settings().fastapi_internal_secret}


@asynccontextmanager
async def _session():
    yield object()


class TestUpsertEndpoint:
    @pytest.mark.asyncio
    async def test_stores_the_embedded_hunk_for_the_configured_model(self, client):
        replace = AsyncMock()
        embed = AsyncMock(return_value=[[0.1] * 768])
        with (
            patch("core.database.AsyncSessionLocal", _session),
            patch("services.feedback_store.replace_feedback", replace),
            patch("services.vector_store.vector_store.generate_embeddings", embed),
        ):
            response = await client.post(
                "/feedback/upsert",
                json={
                    "comment_id": 7,
                    "repo_full_name": "o/r",
                    "signal": "rejected",
                    "file_path": "app.py",
                    "category": "security",
                    "severity": "error",
                    "body": "SQL injection",
                    "code_hunk": HUNK,
                    "pr_number": 12,
                },
                headers=_headers(),
            )

        assert response.status_code == 200
        assert response.json() == {"stored": True, "deleted": 0}
        # Rule 2: tagged with its PR, so that PR's reviews can leave it out.
        assert replace.call_args.kwargs["source_ref"] == "PR#12"
        [texts] = embed.call_args.args
        assert texts == [document_text("app.py", HUNK, "SQL injection", _chunk_text)]
        assert embed.call_args.kwargs == {"task_type": "RETRIEVAL_DOCUMENT"}
        kwargs = replace.call_args.kwargs
        assert kwargs["comment_id"] == 7
        assert kwargs["signal"] == "rejected"
        assert kwargs["embedding_model"] == get_settings().embedding_model

    @pytest.mark.asyncio
    async def test_null_signal_deletes_without_embedding(self, client):
        delete = AsyncMock(return_value=2)
        embed = AsyncMock()
        with (
            patch("core.database.AsyncSessionLocal", _session),
            patch("services.feedback_store.delete_feedback", delete),
            patch("services.vector_store.vector_store.generate_embeddings", embed),
        ):
            response = await client.post(
                "/feedback/upsert",
                json={"comment_id": 7, "repo_full_name": "o/r", "signal": None},
                headers=_headers(),
            )

        assert response.json() == {"stored": False, "deleted": 2}
        assert delete.call_args.args[1] == 7
        embed.assert_not_called()

    @pytest.mark.asyncio
    async def test_store_failure_is_a_500_for_django_to_retry(self, client):
        with (
            patch("core.database.AsyncSessionLocal", _session),
            patch(
                "services.feedback_store.replace_feedback",
                AsyncMock(side_effect=RuntimeError("relation does not exist")),
            ),
            patch(
                "services.vector_store.vector_store.generate_embeddings",
                AsyncMock(return_value=[[0.1] * 768]),
            ),
        ):
            response = await client.post(
                "/feedback/upsert",
                json={
                    "comment_id": 7,
                    "repo_full_name": "o/r",
                    "signal": "accepted",
                    "body": "x",
                },
                headers=_headers(),
            )

        assert response.status_code == 500
        assert "relation" not in response.text

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "field,size",
        [
            ("code_hunk", 20_001),
            ("body", 10_001),
            ("file_path", 1_001),
            ("category", 51),
            ("severity", 51),
        ],
    )
    async def test_oversized_fields_are_rejected(self, client, field, size):
        """Security review of #109, rule 6."""
        replace = AsyncMock()
        with (
            patch("core.database.AsyncSessionLocal", _session),
            patch("services.feedback_store.replace_feedback", replace),
            patch(
                "services.vector_store.vector_store.generate_embeddings",
                AsyncMock(return_value=[[0.1] * 768]),
            ),
        ):
            response = await client.post(
                "/feedback/upsert",
                json={
                    "comment_id": 7,
                    "repo_full_name": "o/r",
                    "signal": "accepted",
                    "body": "x",
                    field: "y" * size,
                },
                headers=_headers(),
            )
        assert response.status_code == 422
        replace.assert_not_called()

    @pytest.mark.asyncio
    async def test_negative_pr_number_is_rejected(self, client):
        response = await client.post(
            "/feedback/upsert",
            json={
                "comment_id": 7,
                "repo_full_name": "o/r",
                "signal": None,
                "pr_number": -1,
            },
            headers=_headers(),
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_unknown_signal_is_rejected(self, client):
        response = await client.post(
            "/feedback/upsert",
            json={"comment_id": 7, "repo_full_name": "o/r", "signal": "maybe"},
            headers=_headers(),
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_nothing_to_embed_is_rejected(self, client):
        response = await client.post(
            "/feedback/upsert",
            json={"comment_id": 7, "repo_full_name": "o/r", "signal": "accepted"},
            headers=_headers(),
        )
        assert response.status_code == 422
