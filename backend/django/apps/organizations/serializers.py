from typing import Any

from rest_framework import serializers

from apps.accounts.serializers import UserSerializer
from apps.organizations.models import OrgRepository, Organization, TeamMembership


class OrganizationSerializer(serializers.ModelSerializer):
    member_count = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = [
            "id",
            "name",
            "slug",
            "description",
            "github_org_id",
            "owner",
            "member_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "slug", "owner", "created_at", "updated_at"]

    def get_member_count(self, obj: Organization) -> int:
        return obj.memberships.filter(is_active=True).count()


class TeamMembershipSerializer(serializers.ModelSerializer):
    user_detail = UserSerializer(source="user", read_only=True)

    class Meta:
        model = TeamMembership
        fields = [
            "id",
            "organization",
            "user",
            "user_detail",
            "role",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class OrganizationDetailSerializer(OrganizationSerializer):
    memberships = TeamMembershipSerializer(many=True, read_only=True)

    class Meta(OrganizationSerializer.Meta):
        fields = OrganizationSerializer.Meta.fields + ["memberships"]


class OrgRepositorySerializer(serializers.ModelSerializer):
    class Meta:
        model = OrgRepository
        fields = ["id", "organization", "repository", "added_by", "created_at"]
        read_only_fields = ["id", "added_by", "created_at"]


class InviteSerializer(serializers.Serializer):
    email = serializers.EmailField(help_text="Email address to invite")


class InviteAcceptSerializer(serializers.Serializer):
    role = serializers.ChoiceField(
        choices=["admin", "member"],
        default="member",
        required=False,
    )
