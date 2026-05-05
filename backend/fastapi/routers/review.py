"""
Review router for BYOK code reviews.

Endpoints for submitting code reviews and retrieving review history.
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from typing import Any

from services.supabase_client import (
    supabase_client,
    SupabaseError,
    BYOKReview,
)
from services.llm_client import llm_client

router = APIRouter(prefix="/review", tags=["review"])


class ReviewRequest(BaseModel):
    """Request to analyze code."""

    code: str
    language: str = "python"
    user_id: int


class ReviewResponse(BaseModel):
    """Review response."""

    id: str
    user_id: int
    code_snippet: str
    language: str
    review_data: dict[str, Any]
    provider: str | None
    model: str | None
    created_at: str


@router.post("/analyze", response_model=ReviewResponse)
async def analyze_code(request: ReviewRequest):
    """
    Analyze code and store in Supabase.

    TODO: Integrate with LLM client (P2-04) for actual review
    """
    try:
        from services.llm_client import llm_client

        messages = [
            {
                "role": "system",
                "content": "You are a code reviewer. Review the code and provide feedback.",
            },
            {
                "role": "user",
                "content": f"Review this {request.language} code:\n\n{request.code}",
            },
        ]

        llm_response = await llm_client.generate(messages)

        review_data = {
            "feedback": llm_response.content,
            "issues": [],
        }

        review = await supabase_client.insert_review(
            user_id=request.user_id,
            code_snippet=request.code[:500],
            review_data=review_data,
            language=request.language,
            provider=llm_response.provider,
            model=llm_response.model_used,
        )

        return ReviewResponse(
            id=review.id,
            user_id=review.user_id,
            code_snippet=review.code_snippet,
            language=review.language,
            review_data=review.review_data,
            provider=review.provider,
            model=review.model,
            created_at=review.created_at,
        )

    except SupabaseError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Storage error: {str(e)}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get("/history/{user_id}", response_model=list[ReviewResponse])
async def get_review_history(user_id: int, limit: int = 50):
    """Get review history for a user."""
    try:
        reviews = await supabase_client.get_user_reviews(user_id, limit)

        return [
            ReviewResponse(
                id=r.id,
                user_id=r.user_id,
                code_snippet=r.code_snippet,
                language=r.language,
                review_data=r.review_data,
                provider=r.provider,
                model=r.model,
                created_at=r.created_at,
            )
            for r in reviews
        ]

    except SupabaseError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Storage error: {str(e)}",
        )


@router.get("/{review_id}", response_model=ReviewResponse)
async def get_review(review_id: str):
    """Get a specific review."""
    review = await supabase_client.get_review(review_id)

    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review not found",
        )

    return ReviewResponse(
        id=review.id,
        user_id=review.user_id,
        code_snippet=review.code_snippet,
        language=review.language,
        review_data=review.review_data,
        provider=review.provider,
        model=review.model,
        created_at=review.created_at,
    )


@router.delete("/{review_id}")
async def delete_review(review_id: str):
    """Delete a review."""
    await supabase_client.delete_review(review_id)
    return {"message": "Review deleted"}
