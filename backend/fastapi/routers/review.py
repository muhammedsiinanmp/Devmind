"""
Review router with full RAG pipeline.

Wires: parse diff → embed → similarity search → build prompt → review agent → store embedding → return response.
"""

import time
import asyncio
import logging
from typing import Any

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


async def _prepare_rag_context(
    request: ReviewRequest,
) -> tuple[list[DiffChunk], list[str], str]:
    """
    Run the RAG context preparation steps:
    parse diff -> embed/store chunks -> similarity search -> build prompt.
    """
    parsed_chunks = parse_diff(request.diff)
    similar_patterns: list[str] = []

    try:
        from core.database import AsyncSessionLocal
        from services.vector_store import vector_store, VectorStoreError

        async with AsyncSessionLocal() as session:
            for chunk in parsed_chunks[:20]:
                chunk_text = _chunk_text(chunk)
                if not chunk_text:
                    continue
                try:
                    await vector_store.store_code_embedding(
                        session=session,
                        repo_full_name=request.repo_full_name,
                        file_path=chunk.file_path or f"PR#{request.pr_number}",
                        chunk_text=chunk_text[:4000],
                        language=chunk.language or "unknown",
                        chunk_type=chunk.chunk_type or "hunk",
                    )
                except VectorStoreError:
                    # duplicate or transient embedding issues should not block reviews
                    continue

            search_query = request.diff[:2000]
            similar_chunks = await vector_store.search_similar(
                session=session,
                query_text=search_query,
                repo_full_name=request.repo_full_name,
                top_k=5,
                threshold=0.6,
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


def calculate_risk_score(comments: list[dict]) -> int:
    """Calculate risk score from 0-100 based on comment severity."""
    if not comments:
        return 0

    severity_scores = {
        "critical": 40,
        "error": 25,
        "warning": 10,
        "info": 2,
    }

    total = 0
    for comment in comments:
        severity = comment.get("severity", "info")
        total += severity_scores.get(severity, 2)

    return min(100, total)


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

        # Store embedding asynchronously (fire-and-forget)
        asyncio.create_task(
            store_review_async(
                repo_full_name=request.repo_full_name,
                pr_number=request.pr_number,
                diff=request.diff,
                comments=comments_data,
                model=model_used,
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
        )

    except AllProvidersDownError:
        review_errors_total.labels(error_type="llm_unavailable").inc()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "llm_unavailable",
                "message": "All LLM providers are temporarily unavailable",
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
    diff: str,
    comments: list[dict],
    model: str,
):
    """Store review embedding asynchronously."""
    try:
        from services.vector_store import vector_store
        from core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            await vector_store.store_code_embedding(
                session=session,
                repo_full_name=repo_full_name,
                file_path=f"PR#{pr_number}",
                chunk_text=diff[:1000],
                language="diff",
                chunk_type="pr",
            )
    except Exception as e:
        logger.error("store_review.error error=%s", str(e))
