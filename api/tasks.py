import logging
from typing import Iterable

from celery import shared_task
from django.db import transaction

from .models import Message, Newsletter
from .services import send_message_to_external_service
from .utils import campaign_recipients, within_sending_window

logger = logging.getLogger(__name__)


def _enqueue_messages(campaign: Newsletter, recipients: Iterable) -> list[Message]:
    created = []
    for client in recipients:
        created.append(
            Message.objects.create(
                campaign=campaign,
                client=client,
                message_text=campaign.text_message,
            )
        )
    return created


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def send_message_async(self, message_id: int) -> None:
    try:
        message = Message.objects.select_related("campaign", "client").get(pk=message_id)
    except Message.DoesNotExist:
        logger.warning("Message with id %s does not exist.", message_id)
        return

    send_message_to_external_service(message, message.campaign)


@shared_task(bind=True)
def start_campaign_async(self, campaign_id: int) -> None:
    try:
        campaign = Newsletter.objects.get(pk=campaign_id)
    except Newsletter.DoesNotExist:
        logger.error("Campaign with id %s does not exist.", campaign_id)
        return

    if not within_sending_window(campaign):
        logger.info("Campaign %s is outside active window.", campaign_id)
        return

    recipients = campaign_recipients(campaign)
    if not recipients.exists():
        logger.info("Campaign %s has no matching recipients.", campaign_id)
        return

    with transaction.atomic():
        campaign.is_active = True
        campaign.save(update_fields=["is_active"])
        messages = _enqueue_messages(campaign, recipients)

    for message in messages:
        send_message_async.delay(message.id)
