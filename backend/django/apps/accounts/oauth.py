import secrets
from typing import Any, cast

import requests
from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, transaction

from apps.accounts.models import CustomUser, GithubToken

OAUTH_STATE_TTL = 600


class OAuthError(Exception):
    """Raised when any step of GitHub OAuth flow fails."""

    pass


def generate_oauth_state() -> str:
    """
    Generate and cache a cryptographically random OAuth state token.

    The state parameter prevents OAuth Login CSRF attacks by ensuring
    the callback originated from our own login flow, not an attacker's URL.

    Returns: The state string to pass to GitHub's authorize URL.
    """
    state = secrets.token_urlsafe(32)
    cache.set(f"oauth_state:{state}", True, timeout=OAUTH_STATE_TTL)
    return state


def validate_oauth_state(state: str) -> bool:
    """
    Validate and consume an OAuth state token (one-time use).

    Returns True if the state is valid and was consumed.
    Returns False if the state is missing, expired, or already used.
    """
    cache_key = f"oauth_state:{state}"
    if cache.get(cache_key):
        cache.delete(cache_key)  # One-time use: consume immediately
        return True
    return False


def exchange_code_for_token(code: str) -> dict[str, Any]:
    """
    Exchange a GitHub authorization code for an access token.

    POST https://github.com/login/oauth/access_token
    Returns: {"access_token": "...", "token_type": "bearer", "scope": "..."}
    Raises: OAuthError on non-200 response or error in response body.
    """
    response = requests.post(
        "https://github.com/login/oauth/access_token",
        data={
            "client_id": settings.GITHUB_CLIENT_ID,
            "client_secret": settings.GITHUB_CLIENT_SECRET,
            "code": code,
        },
        headers={"Accept": "application/json"},
        timeout=10,
    )

    if response.status_code != 200:
        raise OAuthError(
            f"GitHub token exchange failed with status {response.status_code}"
        )

    data = response.json()
    if "error" in data:
        raise OAuthError(
            f"GitHub OAuth error: {data.get('error_description',data['error'])}"
        )

    return cast(dict[str, Any], data)


def get_github_user(access_token: str) -> dict[str, Any]:
    """
    Fetch the authenticated GitHub user's profile.

    GET https://api.github.com/user
    Returns: {"id": ..., "login": "...", "email": "...", "avatar_url": "..."}
    Raises: OAuthError on non-200 response.
    """
    response = requests.get(
        "https://api.github.com/user",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
        timeout=10,
    )

    if response.status_code != 200:
        raise OAuthError(f"GitHub user fetch failed with status {response.status_code}")

    return cast(dict[str, Any], response.json())


@transaction.atomic
def upsert_user(github_data: dict[str, Any], token_data: dict[str, Any]) -> CustomUser:
    """
    Create or update a user from GitHub OAuth data.

    Uses github_id as the unique identifier. Updates profile fields
    (login, avatar, email) on every login to keep them current.
    Also creates/updates the associated GithubToken.

    Wrapped in transaction.atomic() to ensure user + token are
    created/updated together or not at all.

    Raises: OAuthError if the GitHub email conflicts with an existing account.
    """
    try:
        user, _created = CustomUser.objects.update_or_create(
            github_id=github_data["id"],
            defaults={
                "email": github_data.get("email")
                or f"{github_data['login']}@github.devmind",
                "github_login": github_data["login"],
                "avatar_url": github_data.get("avatar_url", ""),
            },
        )
    except IntegrityError as err:
        raise OAuthError(
            "An account with this email already exists. "
            "Please log in with the original method."
        ) from err

    GithubToken.objects.update_or_create(
        user=user,
        defaults={
            "access_token": token_data["access_token"],
            "token_type": token_data.get("token_type", "bearer"),
            "scopes": (
                token_data.get("scope", "").split(",")
                if token_data.get("scope")
                else []
            ),
        },
    )

    return user
