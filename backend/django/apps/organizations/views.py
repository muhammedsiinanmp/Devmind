import secrets
from typing import Any

from django.conf import settings
from django.core.cache import cache
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.organizations.models import Organization, TeamMembership
from apps.organizations.permissions import IsOrgAdminOrOwner
from apps.organizations.serializers import (
    InviteSerializer,
    OrganizationDetailSerializer,
    OrganizationSerializer,
    TeamMembershipSerializer,
)
from apps.organizations.tasks import send_invite_email_task


class OrgCreateView(APIView):
    """POST /api/v1/organizations/ — Create a new org. Requesting user becomes owner."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=OrganizationSerializer,
        responses={201: OrganizationSerializer},
        summary="Create organization",
    )
    def post(self, request: Request) -> Response:
        serializer = OrganizationSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        org = serializer.save(owner=request.user)
        TeamMembership.objects.create(
            organization=org,
            user=request.user,
            role="owner",
        )
        return Response(
            OrganizationSerializer(org).data,
            status=status.HTTP_201_CREATED,
        )


class OrgDetailView(APIView):
    """GET /api/v1/organizations/{id}/"""

    permission_classes = [IsAuthenticated, IsOrgAdminOrOwner]

    @extend_schema(responses={200: OrganizationDetailSerializer})
    def get(self, request: Request, pk: int) -> Response:
        try:
            org = Organization.objects.prefetch_related("memberships__user").get(pk=pk)
        except Organization.DoesNotExist:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(OrganizationDetailSerializer(org).data)


class InviteView(APIView):
    """POST /api/v1/organizations/{org_pk}/invite/ — Send invite email (admin/owner only)."""

    permission_classes = [IsAuthenticated, IsOrgAdminOrOwner]

    @extend_schema(
        request=InviteSerializer,
        responses={201: None},
        summary="Invite member to organization",
    )
    def post(self, request: Request, org_pk: int) -> Response:
        serializer = InviteSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        email = serializer.validated_data["email"]
        try:
            org = Organization.objects.get(pk=org_pk)
        except Organization.DoesNotExist:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

        if TeamMembership.objects.filter(organization=org, user__email=email).exists():
            return Response(
                {"error": "User is already a member of this organization"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        token = secrets.token_urlsafe(32)
        cache.set(f"org_invite:{token}", f"{org_pk}:{email}", 72 * 3600)

        send_invite_email_task.delay(
            email=email,
            org_name=org.name,
            invite_url=f"{settings.DEVMIND_PUBLIC_URL}/invite/accept?token={token}",
        )

        return Response(status=status.HTTP_201_CREATED)


class MemberListView(APIView):
    """GET /api/v1/organizations/{org_pk}/members/"""

    permission_classes = [IsAuthenticated, IsOrgAdminOrOwner]

    @extend_schema(responses={200: TeamMembershipSerializer(many=True)})
    def get(self, request: Request, org_pk: int) -> Response:
        try:
            Organization.objects.get(pk=org_pk)
        except Organization.DoesNotExist:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

        memberships = TeamMembership.objects.filter(
            organization_id=org_pk,
            is_active=True,
        ).select_related("user")
        return Response(TeamMembershipSerializer(memberships, many=True).data)


class MemberRemoveView(APIView):
    """DELETE /api/v1/organizations/{org_pk}/members/{user_id}/ (admin/owner only)."""

    permission_classes = [IsAuthenticated, IsOrgAdminOrOwner]

    @extend_schema(responses={204: None})
    def delete(self, request: Request, org_pk: int, user_id: int) -> Response:
        try:
            membership = TeamMembership.objects.select_related("organization").get(
                organization_id=org_pk,
                user_id=user_id,
            )
        except TeamMembership.DoesNotExist:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

        if membership.role == "owner":
            return Response(
                {"error": "Cannot remove the organization owner"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        membership.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class InviteAcceptView(APIView):
    """GET /api/v1/organizations/invite/accept/?token=TOKEN — Accept invite."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[{"name": "token", "in": "query", "schema": {"type": "string"}}],
        responses={200: OrganizationSerializer},
        summary="Accept organization invite",
    )
    def get(self, request: Request) -> Response:
        token = request.query_params.get("token")
        if not token:
            return Response(
                {"error": "Missing 'token' parameter"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = cache.get(f"org_invite:{token}")
        if not data:
            return Response(
                {"error": "Invalid or expired invite token"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if isinstance(data, bytes):
            data = data.decode()
        org_pk_str, email = data.split(":", 1)
        org_pk = int(org_pk_str)

        if request.user.email != email:
            return Response(
                {"error": "Invite is for a different email address"},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            org = Organization.objects.get(pk=org_pk)
        except Organization.DoesNotExist:
            return Response(
                {"error": "Organization not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        membership, created = TeamMembership.objects.get_or_create(
            organization=org,
            user=request.user,
            defaults={"role": "member"},
        )

        cache.delete(f"org_invite:{token}")

        return Response(
            OrganizationSerializer(org).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )
