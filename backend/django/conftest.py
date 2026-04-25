from typing import Any

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser


@pytest.fixture
def user(db: Any) -> CustomUser:
    """Create a standard test user with GitHub fields populated."""
    user_model = get_user_model()
    return user_model.objects.create_user(
        email="test@example.com",
        password="testpass123",
        github_id=12345,
        github_login="testuser",
        avatar_url="https://avatars.githubusercontent.com/u/12345",
    )


@pytest.fixture
def api_client() -> Any:
    """Return an unauthenticated DRF APIClient."""

    return APIClient()


@pytest.fixture
def auth_client(api_client: Any, user: Any) -> Any:
    """Return an APIClient authenticated with a valid JWT."""
    from rest_framework_simplejwt.tokens import RefreshToken

    refresh = RefreshToken.for_user(user)
    api_client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}"
    )
    return api_client
