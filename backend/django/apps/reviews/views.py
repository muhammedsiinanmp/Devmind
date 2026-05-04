from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.reviews.models import Review
from apps.reviews.serializers import ReviewListSerializer, ReviewSerializer


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

    filter_backends = [SearchFilter, OrderingFilter]
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
