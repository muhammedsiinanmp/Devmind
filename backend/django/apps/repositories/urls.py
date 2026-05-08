from django.urls import path

from apps.repositories import views
from apps.reviews.views import RepoScanTriggerView

app_name = "repositories"

urlpatterns = [
    path("", views.RepositoryListView.as_view(), name="list"),
    path("connect/", views.ConnectRepositoriesView.as_view(), name="connect"),
    path("<int:pk>/", views.RepositoryDetailView.as_view(), name="detail"),
    path("<int:pk>/scan/", RepoScanTriggerView.as_view(), name="scan-trigger"),
]
