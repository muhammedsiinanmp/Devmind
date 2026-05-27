from .base import *  # noqa: F401, F403

DEBUG = False

# Use faster password hasher in tests
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Disable Sentry in tests
SENTRY_DSN = ""

# Use in-memory celery for tests (synchronous execution)
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# Disable throttling in tests
REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"] = []  # noqa: F405

# Disable Kafka in tests
KAFKA_BOOTSTRAP_SERVERS = ""

# Use in-memory channel layer instead of Redis
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    },
}

# FastAPI settings for test environment
FASTAPI_BASE_URL = "http://localhost:8001"
FASTAPI_INTERNAL_SECRET = "test-secret"

# Disable Supabase in tests
SUPABASE_URL = ""
SUPABASE_SERVICE_KEY = ""
