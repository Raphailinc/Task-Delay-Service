import logging
from typing import Any, Dict

from django.db import transaction

from .models import Message

logger = logging.getLogger(__name__)


def _build_payload(message: Message) -> Dict[str, Any]:
    return {
        "client": message.client.phone_number,
        "text": message.message_text,
        "campaign_id": message.campaign_id,
        "message_id": message.id,
    }


def send_message_to_external_service(message: Message, campaign) -> None:
    """Simulate a send to an external provider and persist status."""
    payload = _build_payload(message)
    logger.info("Dispatching message %s to provider", message.id)

    try:
        with transaction.atomic():
            # Здесь можно разместить реальный HTTP-запрос (requests.post и т.п.)
            logger.debug("Payload: %s", payload)
            message.status = "SENT"
            message.save(update_fields=["status", "created_at"])
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to send message %s: %s", message.id, exc)
        message.status = "FAILED"
        message.save(update_fields=["status"])
        raise
