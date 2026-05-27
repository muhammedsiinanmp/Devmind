from typing import Any

from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from apps.accounts.views import (
    GitHubOAuthCallbackView,
    GitHubOAuthStartView,
    GitHubTokenView,
    InternalLLMConfigListView,
    LLMConfigDetailView,
    LLMConfigListCreateView,
    LLMConfigTestView,
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
    path("github/token/", GitHubTokenView.as_view(), name="github-token"),
    # LLM Config (BYOK) — prefixed with settings/ in devmind/urls.py
    path(
        "llm/",
        LLMConfigListCreateView.as_view(),
        name="llm-config-list",
    ),
    path(
        "llm/test/",
        LLMConfigTestView.as_view(),
        name="llm-config-test",
    ),
    path(
        "llm/<int:pk>/",
        LLMConfigDetailView.as_view(),
        name="llm-config-detail",
    ),
    path(
        "llm/<int:pk>/set_default/",
        LLMConfigDetailView.as_view(),
        name="llm-config-set-default",
    ),
    path(
        "internal/llm-configs/",
        InternalLLMConfigListView.as_view(),
        name="llm-config-internal-list",
    ),
]
