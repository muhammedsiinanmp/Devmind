"""
Review router with full RAG pipeline.

Wires: parse diff → similarity search per hunk → review agent (builds the
prompt per file batch) → return response → embed the PR's hunks.
"""

import time
import asyncio
import hashlib
import logging
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, status

from core.config import get_settings
from core.security import verify_internal_token
from core.metrics import rag_pipeline_duration, agent_iterations, review_errors_total
from models.review import ReviewRequest, ReviewResponse, ReviewComment
from services.code_parser import DiffChunk, parse_diff
from services.comment_anchoring import anchor_comments
from services.diff_batching import ReviewDeadlineError, is_skipped_path
from services.feedback_store import FeedbackContext
from services.llm_client import AllProvidersDownError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/review", tags=["review"])

# Strong references to fire-and-forget tasks; the event loop keeps only weak
# ones, so an unreferenced task can be garbage-collected before it finishes.
_background_tasks: set[asyncio.Task] = set()


def _chunk_text(chunk: DiffChunk) -> str:
    lines = []
    if chunk.hunk_header:
        lines.append(chunk.hunk_header)
    if chunk.added_lines:
        lines.append("Added:")
        lines.extend(chunk.added_lines[:60])
    if chunk.removed_lines:
        lines.append("Removed:")
        lines.extend(chunk.removed_lines[:60])
    if chunk.context_lines:
        lines.append("Context:")
        lines.extend(chunk.context_lines[:40])
    return "\n".join(lines).strip()


def _source_ref(pr_number: int) -> str | None:
    """source_ref tag for a PR's chunks in code_embeddings (None if unknown)."""
    return f"PR#{pr_number}" if pr_number else None


def _normalize(text: str) -> str:
    return " ".join(text.split())


async def _retrieve_feedback(
    repo_full_name: str, query_embeddings: list[list[float]]
) -> FeedbackContext:
    """
    The repository's accepted and rejected feedback examples closest to the
    review's hunks (services/feedback_store.py), searched with the code
    search's query embeddings in a session of its own. Any failure, such as
    a missing feedback_embeddings table, gives no examples.
    """
    try:
        from core.database import AsyncSessionLocal
        from services import feedback_store
        from services.vector_store import vector_store

        async with AsyncSessionLocal() as session:
            return await feedback_store.search_feedback(
                session,
                query_embeddings,
                repo_full_name,
                vector_store.embedding_model,
            )
    except Exception as exc:
        logger.warning(
            "review.feedback_context_failed repo=%s error=%s",
            repo_full_name,
            type(exc).__name__,
        )
        return FeedbackContext()


async def _prepare_rag_context(
    request: ReviewRequest,
) -> tuple[list[DiffChunk], list[str], FeedbackContext]:
    """
    Run the RAG context preparation steps:
    parse diff -> similarity search per hunk -> feedback examples.

    The agent builds the prompt from these, one per file batch, and gives it
    to all three analyzers. Retrieval runs once per review, and files the
    agent will skip (review_skip_patterns) aren't used as queries.

    Nothing is stored here. The PR's own chunks are embedded by
    store_review_async after the review, so retrieval only sees other code:
    rows tagged with this PR's source_ref are excluded in the query, and any
    result whose text matches a hunk of this diff is dropped.

    Feedback examples are searched with the same query embeddings, so they
    cost no extra embedding call.
    """
    parsed_chunks = parse_diff(request.diff)
    similar_patterns: list[str] = []
    query_embeddings: list[list[float]] = []

    all_hunk_texts = [text for text in map(_chunk_text, parsed_chunks) if text]
    skip_patterns = get_settings().review_skip_patterns
    query_texts = [
        text
        for text in map(
            _chunk_text,
            (
                c
                for c in parsed_chunks
                if not is_skipped_path(c.file_path, skip_patterns)
            ),
        )
        if text
    ]
    # Queries are capped at 20 hunks; the duplicate filter covers the whole diff.
    hunk_texts = query_texts[:20]
    current_hunks = {_normalize(text[:4000]) for text in all_hunk_texts}
    legacy_pr_path = f"PR#{request.pr_number}"

    try:
        from core.database import AsyncSessionLocal
        from services.vector_store import SimilarChunk, vector_store

        best: dict[str, SimilarChunk] = {}
        # Embed every query in one batched call before opening a session, so
        # no DB connection is held while waiting on the embedding API.
        query_embeddings = await vector_store.generate_embeddings(
            [text[:4000] for text in hunk_texts], task_type="RETRIEVAL_QUERY"
        )
        async with AsyncSessionLocal() as session:
            if query_embeddings:
                await vector_store.enable_iterative_scan(session)
            for query_embedding in query_embeddings:
                results = await vector_store.search_similar_by_embedding(
                    session=session,
                    query_embedding=query_embedding,
                    repo_full_name=request.repo_full_name,
                    top_k=5,
                    threshold=0.6,
                    exclude_source_ref=_source_ref(request.pr_number),
                )
                for item in results:
                    if item.file_path == legacy_pr_path:
                        # Untagged row written for this PR by older versions
                        continue
                    key = _normalize(item.chunk_text)
                    if key in current_hunks:
                        continue
                    kept = best.get(key)
                    if kept is None or item.similarity > kept.similarity:
                        best[key] = item

        similar_chunks = sorted(best.values(), key=lambda c: -c.similarity)[:5]
        for item in similar_chunks:
            logger.info(
                "review.rag_context.retrieved repo=%s pr=%s file=%s similarity=%s",
                request.repo_full_name,
                request.pr_number,
                item.file_path,
                item.similarity,
            )
        similar_patterns = [
            f"{item.file_path} ({item.language}, sim={item.similarity}): {item.chunk_text[:300]}"
            for item in similar_chunks
        ]
    except Exception as exc:
        logger.warning("review.rag_context_partial error=%s", str(exc))

    feedback = FeedbackContext()
    if query_embeddings:
        feedback = await _retrieve_feedback(request.repo_full_name, query_embeddings)

    return parsed_chunks, similar_patterns, feedback


RISK_BASE_BY_SEVERITY = {"critical": 70, "error": 45, "warning": 20, "info": 5}


def calculate_risk_score(comments: list[dict]) -> int:
    """
    Calculate risk score from 0-100, driven by the worst finding.

    Base score for the highest severity, plus 3 per other finding above
    info (at most +15). The maximum is 70 + 15 = 85. Unknown severities
    count as info.
    """
    if not comments:
        return 0

    bases = sorted(
        (RISK_BASE_BY_SEVERITY.get(c.get("severity", "info"), 5) for c in comments),
        reverse=True,
    )
    info_base = RISK_BASE_BY_SEVERITY["info"]
    others_above_info = sum(1 for base in bases[1:] if base > info_base)

    return bases[0] + min(15, 3 * others_above_info)


@router.post("/analyze", response_model=ReviewResponse)
async def analyze_review(
    request: ReviewRequest,
    secret: str = Depends(verify_internal_token),
):
    """
    Analyze a PR diff with full RAG pipeline.

    Requires X-Internal-Secret header.
    """
    start = time.perf_counter()
    agent_iterations.inc()

    try:
        from agents.review_agent import run_review_agent

        parsed_chunks, similar_patterns, feedback = await _prepare_rag_context(request)

        # Run the review agent with RAG-prepared context
        result = await run_review_agent(
            diff_text=request.diff,
            repo_full_name=request.repo_full_name,
            pr_number=request.pr_number,
            user_id=request.user_id,
            diff_chunks=parsed_chunks,
            similar_patterns=similar_patterns,
            feedback=feedback,
            share_prompt=True,
            # The deadline counts from the start of the request, retrieval included.
            deadline_seconds=get_settings().review_deadline_seconds
            - (time.perf_counter() - start),
        )

        # Extract comments from agent state
        raw_comments = result.get("synthesized_comments", [])
        comments = []
        for item in raw_comments:
            if isinstance(item, dict) and item.get("body"):
                comments.append(
                    ReviewComment(
                        file_path=item.get("file_path", ""),
                        line_number=item.get("line_number", 0),
                        category=item.get("category", "general"),
                        severity=item.get("severity", "info"),
                        body=item.get("body", ""),
                        suggested_fix=item.get("suggested_fix"),
                    )
                )
        comments, anchor_stats = anchor_comments(parsed_chunks, comments)

        comments_data = [c.model_dump() for c in comments]
        risk_score = calculate_risk_score(comments_data)

        latency_ms = int((time.perf_counter() - start) * 1000)
        rag_pipeline_duration.observe(latency_ms)

        model_used = result.get("model_used", "unknown")
        files_skipped = result.get("files_skipped", [])

        # Embed the reviewed files' hunks after the review (fire-and-forget)
        task = asyncio.create_task(
            store_review_async(
                repo_full_name=request.repo_full_name,
                pr_number=request.pr_number,
                chunks=parsed_chunks,
                skipped_paths={item["file_path"] for item in files_skipped},
            )
        )
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

        return ReviewResponse(
            repo_full_name=request.repo_full_name,
            pr_number=request.pr_number,
            comments=comments,
            risk_score=risk_score,
            model_used=model_used,
            provider=model_used.split("/")[0] if "/" in model_used else "unknown",
            latency_ms=latency_ms,
            analyzer_runs=result.get("analyzer_runs", {}),
            files_reviewed=result.get("files_reviewed", []),
            files_skipped=files_skipped,
            **asdict(anchor_stats),
        )

    except ReviewDeadlineError as exc:
        review_errors_total.labels(error_type="review_deadline").inc()
        logger.warning("review.deadline_no_result error=%s", str(exc))
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={
                "error": "review_deadline",
                "message": f"Nothing was reviewed: {exc}.",
            },
        )
    except AllProvidersDownError:
        review_errors_total.labels(error_type="llm_unavailable").inc()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "llm_rate_limited",
                "message": "All LLM providers are rate limited. Retry in 60s.",
            },
        )
    except Exception as e:
        logger.error("review.error error=%s", str(e))
        review_errors_total.labels(error_type="internal").inc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


async def store_review_async(
    repo_full_name: str,
    pr_number: int,
    chunks: list[DiffChunk],
    skipped_paths: set[str] | None = None,
):
    """Embed the reviewed PR's hunks, tagged with the PR's source_ref.

    Runs after the review so the PR's own chunks are never retrieved for it.
    Only files the review covered are embedded: files in ``skipped_paths``
    (the review's files_skipped: generated, batch_limit or deadline) and
    files matching review_skip_patterns are left out. Chunks already stored
    for this repository with the configured embedding model are skipped
    before embedding, the rest are embedded in one batched call, and no DB
    connection is held during that call.
    """
    try:
        from sqlalchemy.exc import DataError, IntegrityError

        from services.vector_store import vector_store
        from core.database import AsyncSessionLocal

        source_ref = _source_ref(pr_number)
        skipped_paths = skipped_paths or set()
        skip_patterns = get_settings().review_skip_patterns
        reviewed_chunks = [
            chunk
            for chunk in chunks
            if chunk.file_path not in skipped_paths
            and not is_skipped_path(chunk.file_path, skip_patterns)
        ]
        pending: dict[str, tuple[DiffChunk, str]] = {}  # sha256 -> (chunk, text)
        for chunk in reviewed_chunks[:20]:
            chunk_text = _chunk_text(chunk)
            if not chunk_text:
                continue
            chunk_text = chunk_text[:4000]
            text_hash = hashlib.sha256(chunk_text.encode()).hexdigest()
            pending.setdefault(text_hash, (chunk, chunk_text))

        if pending:
            async with AsyncSessionLocal() as session:
                existing = await vector_store.existing_hashes(
                    session, repo_full_name, list(pending)
                )
            for text_hash in existing:
                pending.pop(text_hash, None)

        stored = 0
        if pending:
            embeddings = await vector_store.generate_embeddings(
                [text for _, text in pending.values()],
                task_type="RETRIEVAL_DOCUMENT",
            )
            async with AsyncSessionLocal() as session:
                for (text_hash, (chunk, chunk_text)), embedding in zip(
                    pending.items(), embeddings
                ):
                    try:
                        await vector_store.insert_code_embedding(
                            session=session,
                            repo_full_name=repo_full_name,
                            file_path=chunk.file_path or f"PR#{pr_number}",
                            chunk_text=chunk_text,
                            embedding=embedding,
                            sha256=text_hash,
                            language=chunk.language or "unknown",
                            chunk_type=chunk.chunk_type or "hunk",
                            source_ref=source_ref,
                        )
                        stored += 1
                    except (IntegrityError, DataError) as exc:
                        # This row only, e.g. a concurrent insert of the same
                        # (repo, sha256, model) or a value too long for its
                        # column. Reset the session so the remaining chunks
                        # can still be stored.
                        # Any other error (a missing column, a lost connection)
                        # would hit every chunk, so it ends the task below.
                        await session.rollback()
                        logger.warning(
                            "store_review.chunk_error repo=%s pr=%s file=%s error=%s",
                            repo_full_name,
                            pr_number,
                            chunk.file_path,
                            type(exc).__name__,
                        )
                        continue
        logger.info(
            "store_review.done repo=%s pr=%s stored=%d",
            repo_full_name,
            pr_number,
            stored,
        )
    except Exception as e:
        logger.error("store_review.error error=%s", str(e))
