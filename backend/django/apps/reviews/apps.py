from django.apps import AppConfig


class ReviewsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.reviews"

    def ready(self) -> None:
        from apps.reviews import checks  # noqa: F401  (registers the checks)
