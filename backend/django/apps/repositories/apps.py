from django.apps import AppConfig


class RepositoriesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.repositories"
    verbose_name = "Repositories"

    def ready(self) -> None:
        import apps.repositories.signals  # noqa: F401 — registers signal handlers
