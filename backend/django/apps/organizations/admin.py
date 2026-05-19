from django.contrib import admin

from apps.organizations.models import OrgRepository, Organization, TeamMembership


@admin.register(Organization)
class OrgAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "owner", "member_count", "created_at"]
    search_fields = ["name", "slug", "owner__email"]
    readonly_fields = ["slug", "created_at", "updated_at"]

    def member_count(self, obj: Organization) -> int:
        return obj.memberships.filter(is_active=True).count()


@admin.register(TeamMembership)
class TeamMembershipAdmin(admin.ModelAdmin):
    list_display = ["user", "organization", "role", "is_active", "created_at"]
    list_filter = ["role", "is_active", "organization"]
    search_fields = ["user__email", "organization__name"]
    raw_id_fields = ["user", "organization"]


@admin.register(OrgRepository)
class OrgRepositoryAdmin(admin.ModelAdmin):
    list_display = ["repository", "organization", "added_by", "created_at"]
    list_filter = ["organization"]
    raw_id_fields = ["repository", "organization", "added_by"]
