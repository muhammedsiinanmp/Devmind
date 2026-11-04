import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "devmind.settings.development")

app = Celery("devmind")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
