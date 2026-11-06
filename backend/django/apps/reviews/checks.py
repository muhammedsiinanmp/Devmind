"""
System checks for the review pipeline settings.
"""

from django.conf import settings
from django.core.checks import Warning, register

# Seconds Django needs after FastAPI's deadline for anchoring, the response
# and the network.
TIMEOUT_MARGIN_SECONDS = 10


@register()
def check_fastapi_timeout_exceeds_review_deadline(app_configs, **kwargs):
    """Warn if the worker would stop waiting before FastAPI's review deadline."""
    timeout = float(getattr(settings, "FASTAPI_TIMEOUT_SECONDS", 120))
    deadline = float(getattr(settings, "REVIEW_DEADLINE_SECONDS", 100))
    if timeout >= deadline + TIMEOUT_MARGIN_SECONDS:
        return []
    return [
        Warning(
            f"FASTAPI_TIMEOUT_SECONDS ({timeout:g}) is not at least "
            f"{TIMEOUT_MARGIN_SECONDS} s above REVIEW_DEADLINE_SECONDS "
            f"({deadline:g}).",
            hint=(
                "Large reviews would time out in Django before FastAPI returns "
                "its partial result. Raise FASTAPI_TIMEOUT_SECONDS or lower "
                "REVIEW_DEADLINE_SECONDS."
            ),
            id="reviews.W001",
        )
    ]
