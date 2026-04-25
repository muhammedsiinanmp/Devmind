import pytest
import responses
from django.contrib.auth import get_user_model

from apps.accounts.models import GithubToken
from apps.accounts.oauth import (
    OAuthError,
    exchange_code_for_token,
    generate_oauth_state,
    get_github_user,
    upsert_user,
    validate_oauth_state,
)

User = get_user_model()


# --- OAuth State (CSRF Protection) ---


def test_generate_and_validate_state() -> None:
    state = generate_oauth_state()
    assert isinstance(state, str)
    assert len(state) > 20
    assert validate_oauth_state(state) is True


def test_state_is_single_use() -> None:
    state = generate_oauth_state()
    assert validate_oauth_state(state) is True
    assert validate_oauth_state(state) is False  # Already consumed


def test_invalid_state_rejected() -> None:
    assert validate_oauth_state("totally_fake_state") is False


# --- exchange_code_for_token ---


@responses.activate
def test_exchange_code_success() -> None:
    responses.add(
        responses.POST,
        "https://github.com/login/oauth/access_token",
        json={
            "access_token": "gho_test123",
            "token_type": "bearer",
            "scope": "repo,user",
        },
        status=200,
    )
    result = exchange_code_for_token("valid_code")
    assert result["access_token"] == "gho_test123"
    assert result["token_type"] == "bearer"


@responses.activate
def test_exchange_code_non_200_raises_oauth_error() -> None:
    responses.add(
        responses.POST,
        "https://github.com/login/oauth/access_token",
        json={"message": "server error"},
        status=500,
    )
    with pytest.raises(OAuthError, match="status 500"):
        exchange_code_for_token("bad_code")


@responses.activate
def test_exchange_code_error_in_body_raises_oauth_error() -> None:
    responses.add(
        responses.POST,
        "https://github.com/login/oauth/access_token",
        json={
            "error": "bad_verification_code",
            "error_description": "The code passed is incorrect",
        },
        status=200,
    )
    with pytest.raises(OAuthError, match="incorrect"):
        exchange_code_for_token("expired_code")


# --- get_github_user ---


@responses.activate
def test_get_github_user_success() -> None:
    responses.add(
        responses.GET,
        "https://api.github.com/user",
        json={
            "id": 12345,
            "login": "testuser",
            "email": "test@github.com",
            "avatar_url": "https://avatars.githubusercontent.com/u/12345",
        },
        status=200,
    )
    result = get_github_user("gho_valid_token")
    assert result["id"] == 12345
    assert result["login"] == "testuser"


@responses.activate
def test_get_github_user_non_200_raises_oauth_error() -> None:
    responses.add(
        responses.GET,
        "https://api.github.com/user",
        json={"message": "Bad credentials"},
        status=401,
    )
    with pytest.raises(OAuthError, match="status 401"):
        get_github_user("invalid_token")


# --- upsert_user ---


@pytest.mark.django_db
def test_upsert_user_creates_new_user() -> None:
    github_data = {
        "id": 77777,
        "login": "newuser",
        "email": "new@github.com",
        "avatar_url": "https://avatars.githubusercontent.com/u/77777",
    }
    token_data = {
        "access_token": "gho_new_token",
        "token_type": "bearer",
        "scope": "repo,user",
    }
    user = upsert_user(github_data, token_data)

    assert user.github_id == 77777
    assert user.github_login == "newuser"
    assert user.email == "new@github.com"
    assert User.objects.filter(github_id=77777).count() == 1
    assert GithubToken.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_upsert_user_updates_existing_user() -> None:
    github_data = {
        "id": 88888,
        "login": "existing",
        "email": "existing@github.com",
        "avatar_url": "https://old-avatar.com/pic.jpg",
    }
    token_data = {
        "access_token": "gho_old_token",
        "token_type": "bearer",
        "scope": "repo",
    }
    user_v1 = upsert_user(github_data, token_data)

    # Second login — avatar changed
    updated_data = {
        "id": 88888,
        "login": "existing",
        "email": "existing@github.com",
        "avatar_url": "https://new-avatar.com/pic.jpg",
    }
    new_token_data = {
        "access_token": "gho_refreshed_token",
        "token_type": "bearer",
        "scope": "repo,user",
    }
    user_v2 = upsert_user(updated_data, new_token_data)

    assert user_v1.pk == user_v2.pk
    user_v2.refresh_from_db()
    assert user_v2.avatar_url == "https://new-avatar.com/pic.jpg"
    assert User.objects.filter(github_id=88888).count() == 1


@pytest.mark.django_db
def test_upsert_user_email_collision_raises_oauth_error() -> None:
    """If a new github_id has an email that belongs to another user, raise OAuthError.""" # noqa: E501
    # Create an existing user with a specific email
    User.objects.create_user(
        email="taken@example.com",
        password="pass123",
        github_id=11111,
    )

    # A different GitHub account tries to use the same email
    github_data = {
        "id": 22222,
        "login": "different_user",
        "email": "taken@example.com",
        "avatar_url": "https://avatar.com/22222",
    }
    token_data = {
        "access_token": "gho_collision_token",
        "token_type": "bearer",
        "scope": "repo",
    }
    with pytest.raises(OAuthError, match="already exists"):
        upsert_user(github_data, token_data)
