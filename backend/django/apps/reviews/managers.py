from django.db import models
from django.utils import timezone


class ReviewQuerySet(models.QuerySet):
    """
    Custom QuerySet for Review model with chainable filter methods.
    """

    def pending(self):
        """Return reviews with status='pending'."""
        return self.filter(status="pending")

    def processing(self):
        """Return reviews with status='processing'."""
        return self.filter(status="processing")

    def completed(self):
        """Return reviews with status='completed'."""
        return self.filter(status="completed")

    def failed(self):
        """Return reviews with status='failed'."""
        return self.filter(status="failed")

    def by_repository(self, repository):
        """Filter by repository."""
        return self.filter(repository=repository)

    def by_repo(self, repository):
        """Alias for by_repository."""
        return self.by_repository(repository)

    def processing_too_long(self):
        """
        Return reviews stuck in 'processing' state for more than 10 minutes.
        Used by cleanup_stale_reviews Beat task.
        """
        ten_minutes_ago = timezone.now() - timezone.timedelta(minutes=10)
        return self.filter(
            status="processing",
            created_at__lt=ten_minutes_ago,
        )

    def high_risk(self):
        """Return reviews with risk_score >= 70."""
        return self.filter(risk_score__gte=70)

    def low_risk(self):
        """Return reviews with risk_score < 30."""
        return self.filter(risk_score__lt=30)


class ReviewManager(models.Manager):
    """Manager for Review model."""

    def get_queryset(self):
        return ReviewQuerySet(self.model, using=self._db)

    def pending(self):
        return self.get_queryset().pending()

    def processing(self):
        return self.get_queryset().processing()

    def completed(self):
        return self.get_queryset().completed()

    def failed(self):
        return self.get_queryset().failed()

    def by_repository(self, repository):
        return self.get_queryset().by_repository(repository)

    def processing_too_long(self):
        return self.get_queryset().processing_too_long()

    def high_risk(self):
        return self.get_queryset().high_risk()

    def low_risk(self):
        return self.get_queryset().low_risk()
