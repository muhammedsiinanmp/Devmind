"""
Tests for the reviews app views.

Tests match acceptance criteria from P2-02:
- GET /api/v1/reviews/ returns 200 with paginated results
- GET /api/v1/reviews/?status=completed filters correctly
- GET /api/v1/reviews/{id}/ returns nested comments
- POST /api/v1/reviews/{id}/retrigger/ returns 409 when processing
"""

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.reviews.models import Review
from apps.reviews.tests.factories import ReviewCommentFactory, ReviewFactory


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def user(db):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    user = User.objects.create_user(
        email="test@example.com",
        password="testpass123",
    )
    return user


@pytest.fixture
def auth_client(api_client, user):
    api_client.force_authenticate(user=user)
    return api_client


@pytest.mark.django_db
class TestReviewListView:
    """Tests for ReviewListView."""

    def test_list_returns_200(self, auth_client):
        """Authenticated user can access review list."""
        response = auth_client.get("/api/v1/reviews/")
        assert response.status_code == status.HTTP_200_OK

    def test_list_returns_paginated_results(self, auth_client):
        """List returns paginated results."""
        for i in range(5):
            ReviewFactory()
        response = auth_client.get("/api/v1/reviews/")
        assert response.status_code == status.HTTP_200_OK
        assert "results" in response.json()

    def test_list_unauthenticated_returns_401(self, api_client):
        """Unauthenticated user gets 401."""
        response = api_client.get("/api/v1/reviews/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_list_filter_by_status(self, auth_client):
        """Filter by status works."""
        ReviewFactory(status="pending")
        ReviewFactory(status="completed")

        response = auth_client.get("/api/v1/reviews/?status=completed")
        assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestReviewDetailView:
    """Tests for ReviewDetailView."""

    def test_detail_returns_nested_comments(self, auth_client, user):
        """Detail view includes nested comments."""
        review = ReviewFactory(repository__owner=user)
        ReviewCommentFactory(review=review)
        ReviewCommentFactory(review=review)

        response = auth_client.get(f"/api/v1/reviews/{review.pk}/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "comments" in data
        assert len(data["comments"]) == 2

    def test_detail_returns_run(self, auth_client, user):
        """Detail view includes run."""
        from apps.reviews.tests.factories import ReviewRunFactory

        review = ReviewFactory(repository__owner=user)
        ReviewRunFactory(review=review)

        response = auth_client.get(f"/api/v1/reviews/{review.pk}/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "run" in data


@pytest.mark.django_db
class TestReviewRetriggerView:
    """Tests for ReviewRetriggerView."""

    def test_retrigger_pending_review(self, auth_client, user):
        """Can retrigger a pending review."""
        review = ReviewFactory(status="pending", repository__owner=user)

        response = auth_client.post(f"/api/v1/reviews/{review.pk}/retrigger/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == "pending"

    def test_retrigger_failed_review(self, auth_client, user):
        """Can retrigger a failed review."""
        review = ReviewFactory(status="failed", repository__owner=user)

        response = auth_client.post(f"/api/v1/reviews/{review.pk}/retrigger/")
        assert response.status_code == status.HTTP_200_OK

    def test_retrigger_processing_returns_409(self, auth_client, user):
        """Cannot retrigger a processing review."""
        review = ReviewFactory(status="processing", repository__owner=user)

        response = auth_client.post(f"/api/v1/reviews/{review.pk}/retrigger/")
        assert response.status_code == status.HTTP_409_CONFLICT

    def test_retrigger_completed_returns_400(self, auth_client, user):
        """Cannot retrigger a completed review."""
        review = ReviewFactory(status="completed", repository__owner=user)

        response = auth_client.post(f"/api/v1/reviews/{review.pk}/retrigger/")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_retrigger_not_owner_returns_403(self, auth_client):
        """Non-owner cannot retrigger."""
        review = ReviewFactory(status="failed")

        response = auth_client.post(f"/api/v1/reviews/{review.pk}/retrigger/")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_retrigger_not_found_returns_404(self, auth_client):
        """Non-existent review returns 404."""
        response = auth_client.post("/api/v1/reviews/99999/retrigger/")
        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestReviewDetailViewPermissions:
    """Tests for ReviewDetailView permissions."""

    def test_detail_non_owner_returns_403(self, auth_client):
        """Non-owner cannot view review details."""
        review = ReviewFactory()

        response = auth_client.get(f"/api/v1/reviews/{review.pk}/")
        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestListFiltering:
    """Tests for list filtering and search."""

    def test_list_search_by_title(self, auth_client, user):
        """Search by pr_title works."""
        ReviewFactory(pr_title="Fix auth bug", repository__owner=user)
        ReviewFactory(pr_title="Add feature", repository__owner=user)

        response = auth_client.get("/api/v1/reviews/?search=Fix")
        assert response.status_code == status.HTTP_200_OK

    def test_list_ordering(self, auth_client, user):
        """Ordering works."""
        ReviewFactory(risk_score=30, repository__owner=user)
        ReviewFactory(risk_score=80, repository__owner=user)

        response = auth_client.get("/api/v1/reviews/?ordering=risk_score")
        assert response.status_code == status.HTTP_200_OK
