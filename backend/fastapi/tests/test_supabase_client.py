"""
Tests for Supabase client.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.supabase_client import (
    SupabaseClient,
    SupabaseError,
    BYOKReview,
)


class TestBYOKReview:
    def test_byok_review_dataclass(self):
        review = BYOKReview(
            id="test-id",
            user_id=1,
            code_snippet="print('hello')",
            language="python",
            review_data={"feedback": "Good"},
            provider="google",
            model="gemini-2.0-flash",
            created_at="2025-01-01T00:00:00Z",
        )
        assert review.id == "test-id"
        assert review.user_id == 1


class TestSupabaseClient:
    @pytest.mark.asyncio
    async def test_insert_review_success(self):
        client = SupabaseClient()

        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = [
            {
                "id": "new-review-id",
                "user_id": 1,
                "code_snippet": "print('hello')",
                "language": "python",
                "review_data": {"feedback": "Good"},
                "provider": "google",
                "model": "gemini",
                "created_at": "2025-01-01T00:00:00Z",
            }
        ]

        with patch("services.supabase_client.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.request.return_value = mock_response

            review = await client.insert_review(
                user_id=1,
                code_snippet="print('hello')",
                review_data={"feedback": "Good"},
            )

            assert review.id == "new-review-id"

    @pytest.mark.asyncio
    async def test_insert_review_error(self):
        client = SupabaseClient()

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad request"

        with patch("services.supabase_client.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.request.return_value = mock_response

            with pytest.raises(SupabaseError):
                await client.insert_review(
                    user_id=1,
                    code_snippet="test",
                    review_data={},
                )

    @pytest.mark.asyncio
    async def test_get_user_reviews(self):
        client = SupabaseClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "id": "review-1",
                "user_id": 1,
                "code_snippet": "test",
                "language": "python",
                "review_data": {"feedback": "Good"},
                "provider": "google",
                "model": "gemini",
                "created_at": "2025-01-01T00:00:00Z",
            }
        ]

        with patch("services.supabase_client.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.request.return_value = mock_response

            reviews = await client.get_user_reviews(user_id=1)

            assert len(reviews) == 1
            assert reviews[0].id == "review-1"

    @pytest.mark.asyncio
    async def test_get_review_not_found(self):
        client = SupabaseClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = []

        with patch("services.supabase_client.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.request.return_value = mock_response

            review = await client.get_review("nonexistent")

            assert review is None

    @pytest.mark.asyncio
    async def test_delete_review(self):
        client = SupabaseClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}

        with patch("services.supabase_client.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.request.return_value = mock_response

            result = await client.delete_review("test-id")

            assert result is True


class TestSupabaseError:
    def test_supabase_error(self):
        with pytest.raises(SupabaseError):
            raise SupabaseError("Test error")
