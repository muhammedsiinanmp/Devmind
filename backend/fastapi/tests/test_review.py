"""
Tests for the review router.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from routers.review import (
    analyze_code,
    get_review_history,
    get_review,
    delete_review,
)
from services.supabase_client import BYOKReview


class TestReviewEndpoints:
    @pytest.mark.asyncio
    async def test_analyze_code_success(self):
        from services.llm_client import LLMResponse
        from routers.review import ReviewRequest

        mock_llm = AsyncMock()
        mock_llm.generate.return_value = LLMResponse(
            content="Review feedback",
            model_used="google/gemini",
            provider="google",
            prompt_tokens=10,
            completion_tokens=5,
        )

        mock_review = BYOKReview(
            id="review-1",
            user_id=1,
            code_snippet="print('hello')",
            language="python",
            review_data={"feedback": "Good"},
            provider="google",
            model="gemini",
            created_at="2025-01-01T00:00:00Z",
        )

        with patch("services.llm_client.llm_client", mock_llm):
            with patch("routers.review.supabase_client") as mock_client:
                mock_client.insert_review = AsyncMock(return_value=mock_review)

                result = await analyze_code(
                    ReviewRequest(code="print('hello')", language="python", user_id=1)
                )

                assert result.id == "review-1"
                assert result.user_id == 1

    @pytest.mark.asyncio
    async def test_analyze_code_supabase_error(self):
        from services.supabase_client import SupabaseError
        from routers.review import ReviewRequest

        mock_llm = AsyncMock()
        mock_llm.generate.return_value = MagicMock()

        with patch("services.llm_client.llm_client", mock_llm):
            with patch("routers.review.supabase_client") as mock_client:
                mock_client.insert_review.side_effect = SupabaseError("Error")

                with pytest.raises(Exception):
                    await analyze_code(
                        ReviewRequest(code="test", language="python", user_id=1)
                    )

    @pytest.mark.asyncio
    async def test_get_review_history(self):
        mock_reviews = [
            BYOKReview(
                id="review-1",
                user_id=1,
                code_snippet="test",
                language="python",
                review_data={"feedback": "Good"},
                provider="google",
                model="gemini",
                created_at="2025-01-01T00:00:00Z",
            )
        ]

        with patch("routers.review.supabase_client") as mock_client:
            mock_client.get_user_reviews = AsyncMock(return_value=mock_reviews)

            result = await get_review_history(user_id=1)

            assert len(result) == 1
            assert result[0].id == "review-1"

    @pytest.mark.asyncio
    async def test_get_review_found(self):
        mock_review = BYOKReview(
            id="review-1",
            user_id=1,
            code_snippet="test",
            language="python",
            review_data={"feedback": "Good"},
            provider="google",
            model="gemini",
            created_at="2025-01-01T00:00:00Z",
        )

        with patch("routers.review.supabase_client") as mock_client:
            mock_client.get_review = AsyncMock(return_value=mock_review)

            result = await get_review("review-1")

            assert result.id == "review-1"

    @pytest.mark.asyncio
    async def test_get_review_not_found(self):
        with patch("routers.review.supabase_client") as mock_client:
            mock_client.get_review = AsyncMock(return_value=None)

            with pytest.raises(Exception):
                await get_review("review-1")

    @pytest.mark.asyncio
    async def test_delete_review(self):
        with patch("routers.review.supabase_client") as mock_client:
            mock_client.delete_review = AsyncMock(return_value=True)

            result = await delete_review("review-1")

            assert result["message"] == "Review deleted"
