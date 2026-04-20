import pytest
import responses
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.oauth import generate_oauth_state

User = get_user_model()


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def user_with_token(db):
    user = User.objects.create_user(
        email="viewtest@example.com",
        password="testpass123",
        github_id=55555,
        github_login="viewtester",
    )
    refresh = RefreshToken.for_user(user)
    return user, str(refresh.access_token), str(refresh)


# --- GitHubOAuthStartView ---


@pytest.mark.django_db
def test_start_returns_authorize_url(client):
    response = client.get("/api/v1/auth/github/start/")
    assert response.status_code == 200
    assert "authorize_url" in response.data
    assert "state=" in response.data["authorize_url"]
    assert "github.com/login/oauth/authorize" in response.data["authorize_url"]


# --- GitHubOAuthCallbackView ---


@responses.activate
@pytest.mark.django_db
def test_callback_valid_code_and_state_returns_tokens(client):
    # Generate a valid state token first
    state = generate_oauth_state()

    responses.add(
        responses.POST,
        "https://github.com/login/oauth/access_token",
        json={
            "access_token": "gho_test",
            "token_type": "bearer",
            "scope": "repo",
        },
        status=200,
    )
    responses.add(
        responses.GET,
        "https://api.github.com/user",
        json={
            "id": 66666,
            "login": "callbackuser",
            "email": "callback@github.com",
            "avatar_url": "https://avatar.com/66666",
        },
        status=200,
    )

    response = client.get(
        "/api/v1/auth/github/callback/",
        {"code": "valid_code", "state": state},
    )
    assert response.status_code == 200
    assert "access" in response.data
    assert "refresh" in response.data


@pytest.mark.django_db
def test_callback_missing_code_returns_400(client):
    state = generate_oauth_state()
    response = client.get(
        "/api/v1/auth/github/callback/",
        {"state": state},
    )
    assert response.status_code == 400
    assert "code" in response.data["error"].lower()


@pytest.mark.django_db
def test_callback_missing_state_returns_400(client):
    response = client.get(
        "/api/v1/auth/github/callback/",
        {"code": "some_code"},
    )
    assert response.status_code == 400
    assert "state" in response.data["error"].lower()


@pytest.mark.django_db
def test_callback_invalid_state_returns_400(client):
    response = client.get(
        "/api/v1/auth/github/callback/",
        {"code": "some_code", "state": "forged_state_value"},
    )
    assert response.status_code == 400
    assert "state" in response.data["error"].lower()


@responses.activate
@pytest.mark.django_db
def test_callback_invalid_code_returns_400(client):
    state = generate_oauth_state()
    responses.add(
        responses.POST,
        "https://github.com/login/oauth/access_token",
        json={
            "error": "bad_verification_code",
            "error_description": "The code is invalid",
        },
        status=200,
    )

    response = client.get(
        "/api/v1/auth/github/callback/",
        {"code": "invalid_code", "state": state},
    )
    assert response.status_code == 400


# --- UserMeView ---


@pytest.mark.django_db
def test_me_returns_401_without_token(client):
    response = client.get("/api/v1/auth/me/")
    assert response.status_code == 401


@pytest.mark.django_db
def test_me_returns_user_with_valid_token(client, user_with_token):
    user, access_token, _ = user_with_token
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")

    response = client.get("/api/v1/auth/me/")
    assert response.status_code == 200
    assert response.data["email"] == "viewtest@example.com"
    assert response.data["github_login"] == "viewtester"
    assert response.data["github_id"] == 55555


# --- LogoutView ---


@pytest.mark.django_db
def test_logout_blacklists_token(client, user_with_token):
    _, access_token, refresh_token = user_with_token
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")

    # First logout should succeed
    response = client.post(
        "/api/v1/auth/logout/",
        {"refresh": refresh_token},
    )
    assert response.status_code == 205

    # Using the same refresh token again should fail
    response = client.post(
        "/api/v1/auth/logout/",
        {"refresh": refresh_token},
    )
    assert response.status_code == 400
