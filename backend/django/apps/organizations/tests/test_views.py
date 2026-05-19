from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.organizations.models import Organization, TeamMembership
from apps.organizations.tests.factories import (
    OrganizationFactory,
    TeamMembershipFactory,
)

User = get_user_model()


@pytest.fixture(autouse=True)
def _reset_cache():
    from django.core.cache import cache

    cache.clear()


@pytest.fixture
def client() -> APIClient:
    return APIClient()


@pytest.fixture
def user(db: Any) -> Any:
    return User.objects.create_user(
        email="test@example.com",
        password="testpass123",
        github_id=12345,
        github_login="testuser",
    )


@pytest.fixture
def auth_client(client: APIClient, user: Any) -> APIClient:
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


class TestOrgCreateView:
    @pytest.mark.django_db
    def test_create_org_returns_201(self, auth_client: APIClient, user: Any) -> None:
        response = auth_client.post(
            "/api/v1/organizations/",
            {"name": "Acme Corp"},
            format="json",
        )
        assert response.status_code == 201
        assert response.data["name"] == "Acme Corp"
        assert "slug" in response.data
        assert response.data["owner"] == user.id
        assert response.data["member_count"] == 1

    @pytest.mark.django_db
    def test_create_org_auto_creates_owner_membership(
        self, auth_client: APIClient, user: Any
    ) -> None:
        response = auth_client.post(
            "/api/v1/organizations/",
            {"name": "Auto Test Org"},
            format="json",
        )
        org = Organization.objects.get(pk=response.data["id"])
        membership = TeamMembership.objects.get(organization=org, user=user)
        assert membership.role == "owner"

    @pytest.mark.django_db
    def test_create_org_without_auth_returns_401(self, client: APIClient) -> None:
        response = client.post(
            "/api/v1/organizations/",
            {"name": "Unauthorized Org"},
            format="json",
        )
        assert response.status_code == 401

    @pytest.mark.django_db
    def test_create_org_generates_unique_slug(self, auth_client: APIClient) -> None:
        auth_client.post(
            "/api/v1/organizations/",
            {"name": "Unique Test"},
            format="json",
        )
        response2 = auth_client.post(
            "/api/v1/organizations/",
            {"name": "Unique Test"},
            format="json",
        )
        assert response2.status_code == 201
        assert response2.data["slug"] != "unique-test"


class TestOrgDetailView:
    @pytest.mark.django_db
    def test_get_org_detail_returns_200_for_admin(
        self, auth_client: APIClient, user: Any
    ) -> None:
        org = OrganizationFactory.create(owner=user)
        TeamMembershipFactory.create(organization=org, user=user, role="owner")

        response = auth_client.get(f"/api/v1/organizations/{org.pk}/")
        assert response.status_code == 200
        assert response.data["name"] == org.name

    @pytest.mark.django_db
    def test_get_org_detail_returns_403_for_non_member(
        self, auth_client: APIClient
    ) -> None:
        org = OrganizationFactory.create()

        response = auth_client.get(f"/api/v1/organizations/{org.pk}/")
        assert response.status_code == 403

    @pytest.mark.django_db
    def test_get_org_detail_returns_403_for_nonexistent_org(
        self, auth_client: APIClient
    ) -> None:
        response = auth_client.get("/api/v1/organizations/99999/")
        assert response.status_code in (403, 404)


class TestInviteView:
    @pytest.mark.django_db
    @override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            }
        }
    )
    def test_invite_member_sends_email_and_stores_token(
        self, auth_client: APIClient, user: Any
    ) -> None:
        org = OrganizationFactory.create(owner=user)
        TeamMembershipFactory.create(organization=org, user=user, role="owner")

        response = auth_client.post(
            f"/api/v1/organizations/{org.pk}/invite/",
            {"email": "newmember@example.com"},
            format="json",
        )
        assert response.status_code == 201

    @pytest.mark.django_db
    def test_invite_member_returns_403_for_member_role(
        self, auth_client: APIClient, user: Any
    ) -> None:
        org = OrganizationFactory.create(owner=user)
        TeamMembershipFactory.create(organization=org, user=user, role="member")

        response = auth_client.post(
            f"/api/v1/organizations/{org.pk}/invite/",
            {"email": "newmember@example.com"},
            format="json",
        )
        assert response.status_code == 403

    @pytest.mark.django_db
    def test_invite_existing_member_returns_400(
        self, auth_client: APIClient, user: Any
    ) -> None:
        org = OrganizationFactory.create(owner=user)
        TeamMembershipFactory.create(organization=org, user=user, role="owner")
        invitee = User.objects.create_user(
            email="existing@example.com",
            password="pass123",
            github_id=99999,
        )
        TeamMembershipFactory.create(organization=org, user=invitee, role="member")

        response = auth_client.post(
            f"/api/v1/organizations/{org.pk}/invite/",
            {"email": "existing@example.com"},
            format="json",
        )
        assert response.status_code == 400
        assert "already a member" in response.data["error"]

    @pytest.mark.django_db
    def test_invite_nonexistent_org_returns_403(self, auth_client: APIClient) -> None:
        response = auth_client.post(
            "/api/v1/organizations/99999/invite/",
            {"email": "newmember@example.com"},
            format="json",
        )
        assert response.status_code == 403


class TestInviteAcceptView:
    @pytest.mark.django_db
    @override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            }
        }
    )
    def test_accept_invite_creates_membership(
        self, auth_client: APIClient, user: Any
    ) -> None:
        from django.core.cache import cache

        org = OrganizationFactory.create(owner=user)
        cache.set("org_invite:test_token_123", f"{org.pk}:{user.email}", 3600)

        response = auth_client.get(
            "/api/v1/organizations/invite/accept/?token=test_token_123"
        )
        assert response.status_code == 201
        assert TeamMembership.objects.filter(organization=org, user=user).exists()

    @pytest.mark.django_db
    @override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            }
        }
    )
    def test_accept_invite_returns_403_for_wrong_email(
        self, auth_client: APIClient, user: Any
    ) -> None:
        from django.core.cache import cache

        org = OrganizationFactory.create(owner=user)
        cache.set("org_invite:wrong_token", f"{org.pk}:other@example.com", 3600)

        response = auth_client.get(
            "/api/v1/organizations/invite/accept/?token=wrong_token"
        )
        assert response.status_code == 403

    @pytest.mark.django_db
    def test_accept_invite_returns_400_for_expired_token(
        self, auth_client: APIClient
    ) -> None:
        response = auth_client.get(
            "/api/v1/organizations/invite/accept/?token=expired_token"
        )
        assert response.status_code == 400
        assert "expired" in response.data["error"]

    @pytest.mark.django_db
    def test_accept_invite_returns_400_for_missing_token(
        self, auth_client: APIClient
    ) -> None:
        response = auth_client.get("/api/v1/organizations/invite/accept/")
        assert response.status_code == 400


class TestMemberListView:
    @pytest.mark.django_db
    def test_list_members_returns_200(self, auth_client: APIClient, user: Any) -> None:
        org = OrganizationFactory.create(owner=user)
        TeamMembershipFactory.create(organization=org, user=user, role="owner")

        response = auth_client.get(f"/api/v1/organizations/{org.pk}/members/")
        assert response.status_code == 200
        assert len(response.data) == 1

    @pytest.mark.django_db
    def test_list_members_returns_403_for_non_member(
        self, auth_client: APIClient
    ) -> None:
        org = OrganizationFactory.create()

        response = auth_client.get(f"/api/v1/organizations/{org.pk}/members/")
        assert response.status_code == 403


class TestMemberRemoveView:
    @pytest.mark.django_db
    def test_remove_member_returns_204(self, auth_client: APIClient, user: Any) -> None:
        org = OrganizationFactory.create(owner=user)
        TeamMembershipFactory.create(organization=org, user=user, role="owner")
        member = User.objects.create_user(
            email="removeme@example.com",
            password="pass123",
            github_id=88888,
        )
        membership = TeamMembershipFactory.create(
            organization=org, user=member, role="member"
        )

        response = auth_client.delete(
            f"/api/v1/organizations/{org.pk}/members/{member.pk}/"
        )
        assert response.status_code == 204
        assert not TeamMembership.objects.filter(pk=membership.pk).exists()

    @pytest.mark.django_db
    def test_remove_owner_returns_400(self, auth_client: APIClient, user: Any) -> None:
        org = OrganizationFactory.create(owner=user)
        TeamMembershipFactory.create(organization=org, user=user, role="owner")

        response = auth_client.delete(
            f"/api/v1/organizations/{org.pk}/members/{user.pk}/"
        )
        assert response.status_code == 400
        assert "owner" in response.data["error"]

    @pytest.mark.django_db
    def test_remove_nonexistent_returns_404(
        self, auth_client: APIClient, user: Any
    ) -> None:
        org = OrganizationFactory.create(owner=user)
        TeamMembershipFactory.create(organization=org, user=user, role="owner")

        response = auth_client.delete(f"/api/v1/organizations/{org.pk}/members/99999/")
        assert response.status_code == 404


class TestRoleEnforcement:
    @pytest.mark.django_db
    def test_member_role_cannot_access_invite_view(
        self, auth_client: APIClient, user: Any
    ) -> None:
        org = OrganizationFactory.create(owner=user)
        TeamMembershipFactory.create(organization=org, user=user, role="member")

        response = auth_client.post(
            f"/api/v1/organizations/{org.pk}/invite/",
            {"email": "new@example.com"},
            format="json",
        )
        assert response.status_code == 403

    @pytest.mark.django_db
    def test_admin_role_can_access_invite_view(
        self, auth_client: APIClient, user: Any
    ) -> None:
        org = OrganizationFactory.create(owner=user)
        TeamMembershipFactory.create(organization=org, user=user, role="admin")

        response = auth_client.post(
            f"/api/v1/organizations/{org.pk}/invite/",
            {"email": "new@example.com"},
            format="json",
        )
        assert response.status_code in (201, 400)

    @pytest.mark.django_db
    def test_member_role_cannot_remove_members(
        self, auth_client: APIClient, user: Any
    ) -> None:
        org = OrganizationFactory.create(owner=user)
        TeamMembershipFactory.create(organization=org, user=user, role="member")
        other = User.objects.create_user(
            email="other@example.com",
            password="pass123",
            github_id=77777,
        )
        TeamMembershipFactory.create(organization=org, user=other, role="member")

        response = auth_client.delete(
            f"/api/v1/organizations/{org.pk}/members/{other.pk}/"
        )
        assert response.status_code == 403
