import pytest
from django.contrib.auth import get_user_model


@pytest.fixture
def user(db):
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
def api_client():
    """Return an unauthenticated DRF APIClient."""
    from rest_framework.test import APIClient

    return APIClient()


@pytest.fixture
def auth_client(api_client, user):
    """Return an APIClient authenticated with a valid JWT."""
    from rest_framework_simplejwt.tokens import RefreshToken

    refresh = RefreshToken.for_user(user)
    api_client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}"
    )
    return api_client
