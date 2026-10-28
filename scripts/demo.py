"""Run an authenticated API-to-delivery demo in a disposable SQLite database."""

import json
import os
import secrets
import subprocess
import sys
from datetime import time, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    with TemporaryDirectory(prefix="task-delay-demo-") as temporary:
        os.environ.update(
            DJANGO_SETTINGS_MODULE="Work.settings",
            DATABASE_URL=f"sqlite:///{temporary}/demo.sqlite3",
            DJANGO_SECRET_KEY=secrets.token_hex(32),
            DJANGO_ALLOWED_HOSTS="testserver,localhost,127.0.0.1",
            CELERY_TASK_ALWAYS_EAGER="true",
            CELERY_TASK_EAGER_PROPAGATES="true",
            DJANGO_DEBUG="false",
        )
        subprocess.run(
            [sys.executable, str(root / "manage.py"), "migrate", "--verbosity", "0"],
            cwd=root,
            check=True,
        )
        import django

        django.setup()
        from django.contrib.auth import get_user_model
        from django.utils import timezone
        from rest_framework.test import APIClient

        from api.models import Message, MessageStatus
        from api.tasks import send_message_async

        password = secrets.token_urlsafe(24)
        get_user_model().objects.create_user(username="demo", password=password)
        api = APIClient()
        response = api.post(
            "/api/token/", {"username": "demo", "password": password}, format="json"
        )
        if response.status_code != 200:
            raise RuntimeError(f"Token request failed: {response.status_code}")
        api.credentials(HTTP_AUTHORIZATION=f"Bearer {response.json()['access']}")
        print("1. Authenticated with a short-lived demo JWT.")
        for phone, tag in [("79000000001", "demo"), ("79000000002", "excluded")]:
            response = api.post(
                "/api/clients/",
                {
                    "phone_number": phone,
                    "mobile_operator_code": "900",
                    "tag": tag,
                    "timezone": "UTC",
                },
                format="json",
            )
            if response.status_code != 201:
                raise RuntimeError(f"Client request failed: {response.data}")
        print("2. Created two synthetic recipients; only one matches the audience.")
        now = timezone.now()
        response = api.post(
            "/api/campaigns/",
            {
                "start_datetime": (now - timedelta(minutes=1)).isoformat(),
                "end_datetime": (now + timedelta(days=1)).isoformat(),
                "time_interval_start": time.min.isoformat(),
                "time_interval_end": time.max.isoformat(),
                "text_message": "Portfolio demo: simulated delivery only.",
                "tag": "demo",
                "client_filter": {},
            },
            format="json",
        )
        if response.status_code != 201:
            raise RuntimeError(f"Campaign request failed: {response.data}")
        campaign_id = response.json()["id"]
        message = Message.objects.get(campaign_id=campaign_id)
        if message.status != MessageStatus.SENT:
            raise RuntimeError(f"Unexpected delivery state: {message.status}")
        print("3. The API scheduled a run; eager Celery completed simulated delivery.")
        send_message_async.run(message.id)
        if Message.objects.filter(campaign_id=campaign_id).count() != 1:
            raise RuntimeError("Duplicate delivery created another journal record")
        print("4. Replayed delivery: the terminal message was skipped.")
        response = api.get(f"/api/campaigns/{campaign_id}/stats/")
        if response.status_code != 200:
            raise RuntimeError(f"Stats request failed: {response.status_code}")
        print("5. Campaign statistics:")
        print(json.dumps(response.json(), indent=2))
    print("Demo database removed. No broker, external provider or existing database was used.")


if __name__ == "__main__":
    main()
