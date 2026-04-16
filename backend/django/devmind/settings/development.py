from .base import *  # noqa: F401, F403

DEBUG = True
INSTALLED_APPS += ["django_extensions"]  # type: ignore[name-defined]  # noqa: F405

# Allow all hosts in development
ALLOWED_HOSTS = ["*"]

# Disable throttling in development
REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"] = []  # type: ignore[index]  # noqa: F405
