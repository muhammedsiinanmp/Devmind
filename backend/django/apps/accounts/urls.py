from typing import Any

from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from apps.accounts.views import (
    GitHubOAuthCallbackView,
    GitHubOAuthStartView,
    LogoutView,
    UserMeView,
)

urlpatterns: list[Any] = [
    path(
        "github/start/",
        GitHubOAuthStartView.as_view(),
        name="github-start",
    ),
    path(
        "github/callback/",
        GitHubOAuthCallbackView.as_view(),
        name="github-callback",
    ),
    path("token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("me/", UserMeView.as_view(), name="user-me"),
    path("logout/", LogoutView.as_view(), name="logout"),
]
