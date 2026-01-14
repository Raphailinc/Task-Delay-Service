import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Work.settings")

app = Celery("Work")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@app.task(bind=True)
def healthcheck(self):
    return "ok"
