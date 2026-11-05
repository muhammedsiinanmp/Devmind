"""
Review router with full RAG pipeline.

Wires: parse diff → similarity search per hunk → build prompt → review agent → return response → embed the PR's hunks.
"""

import time
import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, status

from core.security import verify_internal_token
from core.metrics import rag_pipeline_duration, agent_iterations, review_errors_total
from models.review import ReviewRequest, ReviewResponse, ReviewComment
from services.code_parser import DiffChunk, parse_diff
from services.prompt_builder import PromptContext, build_review_prompt
from services.llm_client import AllProvidersDownError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/review", tags=["review"])


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


async def _prepare_rag_context(
    request: ReviewRequest,
) -> tuple[list[DiffChunk], list[str], str]:
    """
    Run the RAG context preparation steps:
    parse diff -> similarity search per hunk -> build prompt.

    Nothing is stored here. The PR's own chunks are embedded by
    store_review_async after the review, so retrieval only sees other code:
    rows tagged with this PR's source_ref are excluded in the query, and any
    result whose text matches a hunk of this diff is dropped.
    """
    parsed_chunks = parse_diff(request.diff)
    similar_patterns: list[str] = []

    hunk_texts = [text for text in map(_chunk_text, parsed_chunks[:20]) if text]
    current_hunks = {_normalize(text[:4000]) for text in hunk_texts}
    legacy_pr_path = f"PR#{request.pr_number}"

    try:
        from core.database import AsyncSessionLocal
        from services.vector_store import SimilarChunk, vector_store

        best: dict[str, SimilarChunk] = {}
        async with AsyncSessionLocal() as session:
            for text in hunk_texts:
                results = await vector_store.search_similar(
                    session=session,
                    query_text=text[:4000],
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

    prompt_context = PromptContext(
        diff_chunks=parsed_chunks,
        similar_patterns=similar_patterns,
    )
    prebuilt_prompt = build_review_prompt(prompt_context)
    return parsed_chunks, similar_patterns, prebuilt_prompt


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

        parsed_chunks, similar_patterns, prebuilt_prompt = await _prepare_rag_context(
            request
        )

        # Run the review agent with RAG-prepared context
        result = await run_review_agent(
            diff_text=request.diff,
            repo_full_name=request.repo_full_name,
            pr_number=request.pr_number,
            user_id=request.user_id,
            diff_chunks=parsed_chunks,
            similar_patterns=similar_patterns,
            prebuilt_prompt=prebuilt_prompt,
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

        comments_data = [c.model_dump() for c in comments]
        risk_score = calculate_risk_score(comments_data)

        latency_ms = int((time.perf_counter() - start) * 1000)
        rag_pipeline_duration.observe(latency_ms)

        model_used = result.get("model_used", "unknown")

        # Embed the PR's hunks after the review (fire-and-forget)
        asyncio.create_task(
            store_review_async(
                repo_full_name=request.repo_full_name,
                pr_number=request.pr_number,
                chunks=parsed_chunks,
            )
        )

        return ReviewResponse(
            repo_full_name=request.repo_full_name,
            pr_number=request.pr_number,
            comments=comments,
            risk_score=risk_score,
            model_used=model_used,
            provider=model_used.split("/")[0] if "/" in model_used else "unknown",
            latency_ms=latency_ms,
            analyzer_runs=result.get("analyzer_runs", {}),
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
):
    """Embed the reviewed PR's hunks, tagged with the PR's source_ref.

    Runs after the review so the PR's own chunks are never retrieved for it.
    """
    try:
        from services.vector_store import vector_store, VectorStoreError
        from core.database import AsyncSessionLocal

        stored = 0
        async with AsyncSessionLocal() as session:
            for chunk in chunks[:20]:
                chunk_text = _chunk_text(chunk)
                if not chunk_text:
                    continue
                try:
                    await vector_store.store_code_embedding(
                        session=session,
                        repo_full_name=repo_full_name,
                        file_path=chunk.file_path or f"PR#{pr_number}",
                        chunk_text=chunk_text[:4000],
                        language=chunk.language or "unknown",
                        chunk_type=chunk.chunk_type or "hunk",
                        source_ref=_source_ref(pr_number),
                    )
                    stored += 1
                except VectorStoreError:
                    # Duplicate chunk or embedding failure: skip this chunk.
                    continue
        logger.info(
            "store_review.done repo=%s pr=%s stored=%d",
            repo_full_name,
            pr_number,
            stored,
        )
    except Exception as e:
        logger.error("store_review.error error=%s", str(e))
