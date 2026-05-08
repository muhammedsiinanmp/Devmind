from django.urls import path

from apps.reviews.views import (
    ReviewDetailView,
    ReviewListView,
    ReviewRetriggerView,
    RepoScanTriggerView,
    RepoScanDetailView,
)

urlpatterns = [
    path("", ReviewListView.as_view(), name="review-list"),
    path("<int:pk>/", ReviewDetailView.as_view(), name="review-detail"),
    path("<int:pk>/retrigger/", ReviewRetriggerView.as_view(), name="review-retrigger"),
    path("scans/<int:pk>/", RepoScanDetailView.as_view(), name="scan-detail"),
]
