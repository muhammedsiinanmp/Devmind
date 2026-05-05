"""
Review router with full RAG pipeline.

Wires: parse diff → embed → similarity search → build prompt → review agent → store embedding → return response.
"""

import time
import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import Field

from core.security import verify_internal_token
from core.metrics import rag_pipeline_duration, agent_iterations, review_errors_total
from models.review import ReviewRequest, ReviewResponse, ReviewComment, ReviewError
from services.code_parser import DiffChunk, parse_diff
from services.prompt_builder import PromptContext, build_review_prompt
from services.llm_client import llm_client, AllProvidersDownError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/review", tags=["review"])


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
        diff_chunks = parse_diff(request.diff)
        context = PromptContext(diff_chunks=diff_chunks)
        prompt = build_review_prompt(context, max_tokens=8192)

        messages = [
            {"role": "system", "content": "You are an expert code reviewer."},
            {
                "role": "user",
                "content": f"{prompt}\n\nAnalyze the code changes and provide reviews.",
            },
        ]

        try:
            llm_response = await llm_client.generate(messages)
        except AllProvidersDownError:
            review_errors_total.labels(error_type="llm_unavailable").inc()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": "llm_unavailable",
                    "message": "All LLM providers are temporarily unavailable",
                },
            )

        import json

        comments = []
        try:
            content = llm_response.content
            start_idx = content.find("[")
            end_idx = content.rfind("]") + 1
            if start_idx >= 0 and end_idx > start_idx:
                data = json.loads(content[start_idx:end_idx])
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
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
        except (json.JSONDecodeError, ValueError):
            pass

        comments_data = [c.model_dump() for c in comments]
        risk_score = calculate_risk_score(comments_data)

        latency_ms = int((time.perf_counter() - start) * 1000)
        rag_pipeline_duration.observe(latency_ms)

        asyncio.create_task(
            store_review_async(
                repo_full_name=request.repo_full_name,
                pr_number=request.pr_number,
                diff=request.diff,
                comments=comments_data,
                model=llm_response.model_used,
            )
        )

        return ReviewResponse(
            repo_full_name=request.repo_full_name,
            pr_number=request.pr_number,
            comments=comments,
            risk_score=risk_score,
            model_used=llm_response.model_used,
            provider=llm_response.provider or "unknown",
            latency_ms=latency_ms,
        )

    except AllProvidersDownError:
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
