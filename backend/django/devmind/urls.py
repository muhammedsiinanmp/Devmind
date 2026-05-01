from typing import Any

from django.contrib import admin
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.urls import include, path


def health_check(request: HttpRequest) -> HttpResponse:
    from django.db import connection
    from django_redis import get_redis_connection

    try:
        connection.ensure_connection()
        db_status = "ok"
    except Exception:
        db_status = "error"

    try:
        redis_conn = get_redis_connection("default")
        redis_conn.ping()
        redis_status = "ok"
    except Exception:
        redis_status = "error"

    return JsonResponse({"status": "ok", "db": db_status, "redis": redis_status})


urlpatterns: list[Any] = [
    path("admin/", admin.site.urls),
    path("health/", health_check, name="health"),
    path(
        "api/v1/",
        include(
            [
                path("auth/", include("apps.accounts.urls")),
                path("", include("apps.reviews.urls")),
                path("", include("apps.notifications.urls")),
                path("", include("apps.analytics.urls")),
            ]
        ),
    ),
    path(
        "api/v1/repositories/",
        include("apps.repositories.urls", namespace="repositories"),
    ),
    path(
        "api/v1/webhooks/github/",
        include(
            [
                path(
                    "",
                    __import__(
                        "apps.repositories.views", fromlist=["GitHubWebhookView"]
                    ).GitHubWebhookView.as_view(),
                    name="github-webhook",
                ),
            ]
        ),
    ),
]
