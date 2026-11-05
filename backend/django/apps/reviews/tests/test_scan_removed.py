"""
The regex repository scan was removed (issue #75).

- The scan trigger and scan detail endpoints no longer exist.
- The RepoScan model is gone, and migrating forward from the previous
  migration drops the reviews_reposcan table.
"""

import pytest
from django.apps import apps
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.urls import NoReverseMatch, Resolver404, resolve, reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.repositories.tests.factories import RepositoryFactory, UserFactory

PREVIOUS = [("reviews", "0004_reviewrun_diff_text")]


def _table_exists(name: str) -> bool:
    with connection.cursor() as cursor:
        return name in connection.introspection.table_names(cursor)


@pytest.fixture
def owner_client(db):
    user = UserFactory()
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.mark.django_db
class TestScanEndpointsRemoved:
    def test_scan_trigger_returns_404(self, owner_client):
        client, user = owner_client
        repo = RepositoryFactory(owner=user)
        response = client.post(f"/api/v1/repositories/{repo.pk}/scan/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.parametrize(
        "path", ["/api/v1/repositories/1/scan/", "/api/v1/reviews/scans/1/"]
    )
    def test_scan_paths_do_not_resolve(self, path):
        with pytest.raises(Resolver404):
            resolve(path)

    @pytest.mark.parametrize(
        "name,kwargs",
        [("repositories:scan-trigger", {"pk": 1}), ("scan-detail", {"pk": 1})],
    )
    def test_scan_url_names_are_gone(self, name, kwargs):
        with pytest.raises(NoReverseMatch):
            reverse(name, kwargs=kwargs)


@pytest.mark.django_db
def test_reposcan_model_and_table_are_gone():
    with pytest.raises(LookupError):
        apps.get_model("reviews", "RepoScan")
    assert not _table_exists("reviews_reposcan")


@pytest.mark.django_db(transaction=True)
def test_migrating_forward_drops_reposcan_table():
    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes("reviews")
    try:
        executor.migrate(PREVIOUS)
        assert _table_exists("reviews_reposcan")

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(latest)
        assert not _table_exists("reviews_reposcan")
    finally:
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())
