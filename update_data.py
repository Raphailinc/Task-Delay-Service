# update_data.py
import json
import logging
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Work.settings")
django.setup()

from api.models import Newsletter  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

newsletters = Newsletter.objects.all()

for newsletter in newsletters:
    raw_value = newsletter.client_filter
    parsed = raw_value

    if isinstance(raw_value, str):
        try:
            parsed = json.loads(raw_value)
        except (json.JSONDecodeError, TypeError, ValueError):
            logger.warning(
                "Failed to parse client_filter for newsletter %s, keeping empty dict", newsletter.id
            )
            parsed = {}

    if parsed is None:
        parsed = {}

    if not isinstance(parsed, (dict, list)):
        logger.warning(
            "Unexpected client_filter type for newsletter %s: %s", newsletter.id, type(parsed)
        )
        parsed = {}

    newsletter.client_filter = parsed
    newsletter.save(update_fields=["client_filter"])
