from django.db import models


class OrganizationQuerySet(models.QuerySet):
    def for_user(self, user: models.Model) -> models.QuerySet:
        return self.filter(
            memberships__user=user,
            memberships__is_active=True,
        ).distinct()


class TeamMembershipQuerySet(models.QuerySet):
    def active(self) -> models.QuerySet:
        return self.filter(is_active=True)

    def admins_and_owners(self) -> models.QuerySet:
        return self.filter(role__in=("owner", "admin"), is_active=True)


OrganizationManager = OrganizationQuerySet.as_manager()
TeamMembershipManager = TeamMembershipQuerySet.as_manager()
