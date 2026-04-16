from django.apps import AppConfig


class RepositoriesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.repositories"

    def ready(self):
        import apps.repositories.signals  # noqa: F401
