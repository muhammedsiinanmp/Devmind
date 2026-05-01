from __future__ import annotations

import structlog
from rest_framework import generics, permissions, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.repositories.exceptions import WebhookVerificationError
from apps.repositories.models import Repository
from apps.repositories.serializers import (
    RepositorySerializer,
    RepositoryUpdateSerializer,
)
from apps.repositories.tasks import initial_repository_sync_task
from apps.repositories.webhooks import WebhookDispatcher, verify_webhook_signature

log: structlog.BoundLogger = structlog.get_logger(__name__)


class RepositoryListView(generics.ListAPIView[Repository]):
    """
    GET /api/v1/repositories/
    Returns the authenticated user's active repositories.
    Supports ?review_enabled=true filter.
    """

    serializer_class = RepositorySerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self) -> Repository.objects:  # type: ignore[override]
        qs = Repository.objects.active().for_user(self.request.user)
        review_enabled = self.request.query_params.get("review_enabled")
        if review_enabled is not None:
            qs = qs.filter(review_enabled=review_enabled.lower() == "true")
        return qs.select_related("owner")


class RepositoryDetailView(generics.RetrieveUpdateAPIView[Repository]):
    """
    GET /api/v1/repositories/{id}/
    PATCH /api/v1/repositories/{id}/   — update review_enabled, default_branch
    """

    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self) -> type:
        if self.request.method in ("PUT", "PATCH"):
            return RepositoryUpdateSerializer
        return RepositorySerializer

    def get_queryset(self) -> Repository.objects:  # type: ignore[override]
        return Repository.objects.active().for_user(self.request.user)


class ConnectRepositoriesView(APIView):
    """
    POST /api/v1/repositories/connect/
    Triggers a background sync of all GitHub repositories for the authenticated user.
    Returns 202 Accepted immediately — sync happens asynchronously.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: Request) -> Response:
        log.info("repositories.connect.requested", user_id=request.user.pk)
        initial_repository_sync_task.delay(user_id=request.user.pk)
        return Response(
            {"status": "sync_queued", "message": "Repository sync has been queued."},
            status=status.HTTP_202_ACCEPTED,
        )


class GitHubWebhookView(APIView):
    """
    POST /api/v1/webhooks/github/
    Entry point for all GitHub webhook deliveries.

    Security: Unauthenticated (GitHub cannot send JWT tokens).
    Protection: HMAC-SHA256 signature is verified before ANY processing.
    """

    permission_classes = [permissions.AllowAny]
    authentication_classes = []  # No session/JWT auth — webhooks are public

    def post(self, request: Request) -> Response:
        # Step 1: Verify signature — MUST be first, before any payload access
        try:
            verify_webhook_signature(request)
        except WebhookVerificationError:
            return Response(
                {"error": "Forbidden"},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Step 2: Extract event type from header
        event_type = request.headers.get("X-GitHub-Event", "unknown")

        # Step 3: Dispatch — this enqueues Celery tasks and returns immediately
        dispatcher = WebhookDispatcher()
        dispatcher.dispatch(request.data, event_type=event_type)  # type: ignore[arg-type]

        return Response({"status": "accepted"}, status=status.HTTP_200_OK)
