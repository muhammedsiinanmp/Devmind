from typing import Any

from rest_framework.permissions import BasePermission


class IsOrgAdminOrOwner(BasePermission):
    """
    Requires user to have an active owner or admin membership in the org.
    Expects `view.kwargs` to contain the organization PK under one of:
    `organization_pk`, `org_pk`, or `pk`.
    """

    def has_permission(self, request: Any, view: Any) -> bool:
        user = request.user
        if not user or not user.is_authenticated:
            return False

        org_pk = (
            view.kwargs.get("organization_pk")
            or view.kwargs.get("org_pk")
            or view.kwargs.get("pk")
        )
        if not org_pk:
            return False

        from apps.organizations.models import TeamMembership

        return TeamMembership.objects.filter(
            organization_id=org_pk,
            user=user,
            role__in=("owner", "admin"),
            is_active=True,
        ).exists()
