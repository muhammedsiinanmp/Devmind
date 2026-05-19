import logging

import httpx
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    autoretry_for=(httpx.HTTPError,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def send_invite_email_task(
    self,
    email: str,
    org_name: str,
    invite_url: str,
) -> None:
    subject = f"You've been invited to join {org_name} on DevMind"
    body = (
        f"You've been invited to join the organization '{org_name}' on DevMind.\n\n"
        f"Click the link below to accept the invitation:\n{invite_url}\n\n"
        f"This link expires in 72 hours."
    )

    from django.conf import settings

    if getattr(settings, "EMAIL_BACKEND", None):
        from django.core.mail import send_mail

        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=False,
        )
    else:
        logger.info(f"[DEV] Invite email to {email}: {subject}")


@shared_task(bind=True)
def sync_org_members_task(self, org_pk: int) -> dict:
    from django.conf import settings

    from apps.accounts.models import CustomUser
    from apps.organizations.models import Organization, TeamMembership

    try:
        org = Organization.objects.get(pk=org_pk)
    except Organization.DoesNotExist:
        return {"status": "error", "message": "Organization not found"}

    if not org.github_org_id:
        return {"status": "skipped", "message": "No github_org_id set"}

    owner_token = None
    if hasattr(org.owner, "github_token") and org.owner.github_token:
        owner_token = org.owner.github_token.access_token

    if not owner_token:
        return {"status": "error", "message": "Owner has no GitHub token"}

    headers = {
        "Authorization": f"Bearer {owner_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    members_added = 0
    members_updated = 0

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(
                f"https://api.github.com/orgs/{org.github_org_id}/public_members",
                headers=headers,
            )
            if response.status_code != 200:
                return {
                    "status": "error",
                    "message": f"GitHub API returned {response.status_code}",
                }

            github_members = response.json()
            for member in github_members:
                try:
                    user = CustomUser.objects.get(github_id=member["id"])
                except CustomUser.DoesNotExist:
                    continue

                membership, created = TeamMembership.objects.get_or_create(
                    organization=org,
                    user=user,
                    defaults={"role": "member"},
                )
                if created:
                    members_added += 1
                else:
                    members_updated += 1

    except httpx.HTTPError as e:
        logger.error(f"Failed to sync org members for org {org_pk}: {e}")
        raise self.retry(exc=e)

    return {
        "status": "ok",
        "members_added": members_added,
        "members_updated": members_updated,
    }
