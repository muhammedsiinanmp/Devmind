"""
Supabase client for BYOK reviews storage.

Provides CRUD operations for reviews stored in Supabase.
"""

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class SupabaseError(Exception):
    """Raised on Supabase client errors."""

    pass


@dataclass
class BYOKReview:
    """BYOK review stored in Supabase."""

    id: str
    user_id: int
    code_snippet: str
    language: str
    review_data: dict[str, Any]
    provider: str | None
    model: str | None
    created_at: str


class SupabaseClient:
    """Client for Supabase BYOK reviews storage."""

    def __init__(self):
        self.url = settings.supabase_url
        self.key = settings.supabase_service_key
        self.table = "byok_reviews"

    async def _request(
        self,
        method: str,
        path: str,
        json: dict | None = None,
    ) -> dict:
        """Make request to Supabase REST API."""
        headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            url = f"{self.url}/rest/v1/{path}"
            response = await client.request(
                method,
                url,
                headers=headers,
                json=json,
            )

            if response.status_code >= 400:
                logger.error(
                    "supabase.error method=%s path=%s status=%s",
                    method,
                    path,
                    response.status_code,
                )
                raise SupabaseError(
                    f"Supabase error: {response.status_code} - {response.text}"
                )

            if method == "DELETE":
                return {}

            return response.json()

    async def insert_review(
        self,
        user_id: int,
        code_snippet: str,
        review_data: dict[str, Any],
        language: str = "python",
        provider: str | None = None,
        model: str | None = None,
    ) -> BYOKReview:
        """
        Insert a new BYOK review.

        Args:
            user_id: User ID
            code_snippet: Code being reviewed
            review_data: Review feedback JSON
            language: Programming language
            provider: LLM provider used
            model: LLM model used

        Returns:
            Created BYOKReview
        """
        data = {
            "user_id": user_id,
            "code_snippet": code_snippet,
            "language": language,
            "review_data": review_data,
            "provider": provider,
            "model": model,
        }

        result = await self._request("POST", self.table, json=data)

        if isinstance(result, list) and result:
            r = result[0]
            return BYOKReview(
                id=r["id"],
                user_id=r["user_id"],
                code_snippet=r["code_snippet"],
                language=r["language"],
                review_data=r["review_data"],
                provider=r.get("provider"),
                model=r.get("model"),
                created_at=r["created_at"],
            )

        raise SupabaseError(f"Failed to insert review: {result}")

    async def get_user_reviews(
        self,
        user_id: int,
        limit: int = 50,
    ) -> list[BYOKReview]:
        """
        Get reviews for a user.

        Args:
            user_id: User ID
            limit: Max reviews to return

        Returns:
            List of BYOKReviews
        """
        params = f"?user_id=eq.{user_id}&order=created_at.desc&limit={limit}"

        result = await self._request("GET", f"{self.table}{params}")

        reviews = []
        for r in result:
            reviews.append(
                BYOKReview(
                    id=r["id"],
                    user_id=r["user_id"],
                    code_snippet=r["code_snippet"],
                    language=r["language"],
                    review_data=r["review_data"],
                    provider=r.get("provider"),
                    model=r.get("model"),
                    created_at=r["created_at"],
                )
            )

        return reviews

    async def get_review(self, review_id: str) -> BYOKReview | None:
        """Get a single review by ID."""
        params = f"?id=eq.{review_id}&limit=1"

        result = await self._request("GET", f"{self.table}{params}")

        if not result:
            return None

        r = result[0]
        return BYOKReview(
            id=r["id"],
            user_id=r["user_id"],
            code_snippet=r["code_snippet"],
            language=r["language"],
            review_data=r["review_data"],
            provider=r.get("provider"),
            model=r.get("model"),
            created_at=r["created_at"],
        )

    async def delete_review(self, review_id: str) -> bool:
        """Delete a review by ID."""
        params = f"?id=eq.{review_id}"

        await self._request("DELETE", f"{self.table}{params}")
        return True


supabase_client = SupabaseClient()
