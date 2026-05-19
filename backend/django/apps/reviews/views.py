from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.reviews.models import Review
from apps.reviews.serializers import (
    ReviewListSerializer,
    ReviewSerializer,
    RepoScanSerializer,
)


class ReviewListView(ListAPIView):
    """
    GET /api/v1/reviews/
    Returns paginated list of reviews.

    Query params:
    - status: filter by status (pending, processing, completed, failed)
    - repository: filter by repository_id
    - search: search in pr_title
    - ordering: order by field (created_at, -created_at, risk_score, etc.)
    """

    permission_classes = [IsAuthenticated]
    serializer_class = ReviewListSerializer
    queryset = Review.objects.select_related("repository").all()

    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["status", "repository"]
    search_fields = ["pr_title", "repository__full_name"]
    ordering_fields = ["created_at", "risk_score", "status"]
    ordering = ["-created_at"]

    def get_serializer_class(self):
        if self.request.query_params.get("detail") == "true":
            return ReviewSerializer
        return ReviewListSerializer


class ReviewDetailView(RetrieveAPIView):
    """
    GET /api/v1/reviews/{id}/
    Returns full review with nested comments and run.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = ReviewSerializer
    queryset = Review.objects.select_related("repository").prefetch_related(
        "comments", "run"
    )

    def get_object(self):
        obj = super().get_object()
        if obj.repository.owner != self.request.user:
            raise PermissionDenied("You do not have permission to view this review")
        return obj


class ReviewRetriggerView(APIView):
    """
    POST /api/v1/reviews/{id}/retrigger/
    Re-queues a failed review for processing.

    Returns:
    - 200: Review re-queued successfully
    - 409: Review is currently processing
    - 403: User is not the repository owner
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, pk: int) -> Response:
        try:
            review = Review.objects.get(pk=pk)
        except Review.DoesNotExist:
            return Response(
                {"error": "Review not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if review.repository.owner != request.user:
            return Response(
                {"error": "Only repository owner can retrigger reviews"},
                status=status.HTTP_403_FORBIDDEN,
            )

        if review.status == "processing":
            return Response(
                {"error": "Review is currently processing"},
                status=status.HTTP_409_CONFLICT,
            )

        if review.status not in ["pending", "failed"]:
            return Response(
                {"error": f"Cannot retrigger review with status '{review.status}'"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        review.status = "pending"
        review.risk_score = None
        review.summary = ""
        review.completed_at = None
        review.save()

        return Response(
            {
                "message": "Review re-queued successfully",
                "review_id": review.pk,
                "status": review.status,
            },
            status=status.HTTP_200_OK,
        )


class ReviewCreateView(APIView):
    """
    POST /api/v1/reviews/
    Create a new review (for manual triggering).
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        return Response(
            {"error": "Reviews are created via webhook events"},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )


class RepoScanTriggerView(APIView):
    """
    POST /api/v1/repositories/{id}/scan/
    Trigger a full repository scan.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={202: RepoScanSerializer, 429: None, 404: None},
        summary="Trigger a full repository scan",
    )
    def post(self, request: Request, pk: int) -> Response:
        from django.utils import timezone
        from datetime import timedelta
        from apps.repositories.models import Repository
        from apps.reviews.models import RepoScan
        from apps.reviews.tasks import full_repo_scan_task

        try:
            repo = Repository.objects.get(pk=pk, owner=request.user)
        except Repository.DoesNotExist:
            return Response(
                {"error": "Repository not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        last_scan = (
            RepoScan.objects.filter(repository=repo).order_by("-created_at").first()
        )

        if last_scan and last_scan.status == "completed":
            time_since_last = timezone.now() - last_scan.created_at
            if time_since_last < timedelta(hours=24):
                retry_after = 24 * 3600 - int(time_since_last.total_seconds())
                return Response(
                    {
                        "error": "Scan rate limit exceeded",
                        "retry_after": retry_after,
                        "message": f"Last scan was {time_since_last.total_seconds() / 3600:.1f} hours ago. Wait 24 hours between scans.",
                    },
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                    headers={"Retry-After": str(retry_after)},
                )

        scan = RepoScan.objects.create(
            repository=repo,
            triggered_by=request.user,
            status="queued",
            progress=0,
            files_scanned=0,
            total_files=0,
        )

        full_repo_scan_task.delay(scan.pk)

        return Response(
            {
                "scan_id": scan.pk,
                "status": "queued",
                "message": f"Scan queued for {repo.full_name}",
            },
            status=status.HTTP_202_ACCEPTED,
        )


class RepoScanDetailView(RetrieveAPIView):
    """
    GET /api/v1/scans/{scan_id}/
    Get scan details and report.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = RepoScanSerializer

    def get_queryset(self):
        from apps.reviews.models import RepoScan
        from apps.repositories.models import Repository

        user_repos = Repository.objects.filter(owner=self.request.user).values_list(
            "pk", flat=True
        )
        return RepoScan.objects.filter(repository_id__in=user_repos)
