from django.urls import path

from apps.accounts.views import (
    GitHubOAuthCallbackView,
    GitHubOAuthStartView,
    LogoutView,
    UserMeView,
)

urlpatterns: list = [
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
    path("me/", UserMeView.as_view(), name="user-me"),
    path("logout/", LogoutView.as_view(), name="logout"),
]
