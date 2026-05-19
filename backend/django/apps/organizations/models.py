from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.db import models
from django.utils.text import slugify


class Organization(models.Model):
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True, db_index=True)
    description = models.TextField(blank=True, default="")
    github_org_id = models.BigIntegerField(
        null=True,
        blank=True,
        unique=True,
        help_text="GitHub organization ID for syncing members.",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="owned_organizations",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "organizations_organization"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.name

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self.slug:
            self.slug = slugify(self.name)
            counter = 1
            while Organization.objects.filter(slug=self.slug).exists():
                self.slug = f"{slugify(self.name)}-{counter}"
                counter += 1
        super().save(*args, **kwargs)


class TeamMembership(models.Model):
    ROLE_CHOICES = [
        ("owner", "Owner"),
        ("admin", "Admin"),
        ("member", "Member"),
    ]

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="team_memberships",
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="member")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "organizations_teammembership"
        unique_together = [["organization", "user"]]

    def __str__(self) -> str:
        return f"{self.user.email} @ {self.organization.name} ({self.role})"

    @property
    def is_admin_or_owner(self) -> bool:
        return self.role in ("owner", "admin")


class OrgRepository(models.Model):
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="repositories",
    )
    repository = models.ForeignKey(
        "repositories.Repository",
        on_delete=models.CASCADE,
        related_name="org_links",
    )
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="added_org_repos",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "organizations_orgrepository"
        unique_together = [["organization", "repository"]]

    def __str__(self) -> str:
        return f"{self.repository.full_name} @ {self.organization.name}"
