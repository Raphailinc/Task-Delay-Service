import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from .models import (
    CampaignRun,
    CampaignRunStatus,
    CampaignStatus,
    Message,
    MessageStatus,
)
from .services import send_message_to_external_service
from .utils import calculate_planned_send_at, campaign_recipients

logger = logging.getLogger(__name__)


def _refresh_run_status(run: CampaignRun) -> None:
    pending_exists = run.messages.filter(
        status__in=[MessageStatus.PENDING, MessageStatus.QUEUED]
    ).exists()
    failed_exists = run.messages.filter(status=MessageStatus.FAILED).exists()

    if pending_exists:
        new_status = CampaignRunStatus.RUNNING
    elif failed_exists:
        new_status = CampaignRunStatus.FAILED
    else:
        new_status = CampaignRunStatus.FINISHED

    updates = []
    now = timezone.now()
    if run.status != new_status:
        run.status = new_status
        updates.append("status")
    if new_status in {CampaignRunStatus.FAILED, CampaignRunStatus.FINISHED}:
        if not run.finished_at:
            run.finished_at = now
            updates.append("finished_at")

    if updates:
        run.save(update_fields=updates)

    campaign = run.campaign
    if campaign.active_run_id != run.id:
        return

    campaign_updates = []
    if new_status == CampaignRunStatus.RUNNING:
        campaign.status = CampaignStatus.RUNNING
        campaign.is_active = True
        campaign_updates.extend(["status", "is_active"])
    elif new_status in {CampaignRunStatus.FINISHED, CampaignRunStatus.FAILED}:
        campaign.status = (
            CampaignStatus.FINISHED
            if new_status == CampaignRunStatus.FINISHED
            else CampaignStatus.FAILED
        )
        campaign.is_active = False
        campaign_updates.extend(["status", "is_active"])

    if campaign_updates:
        campaign.save(update_fields=campaign_updates)


@shared_task(bind=True)
def dispatch_due_messages(self) -> None:
    now = timezone.now()
    due_messages = (
        Message.objects.select_related("campaign", "run")
        .filter(status=MessageStatus.PENDING, planned_send_at__lte=now)
        .iterator()
    )

    for message in due_messages:
        with transaction.atomic():
            updated = Message.objects.filter(pk=message.id, status=MessageStatus.PENDING).update(
                status=MessageStatus.QUEUED
            )
            if not updated:
                continue
        send_message_async.delay(message.id)


@shared_task(
    bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3}
)
def send_message_async(self, message_id: int) -> None:
    try:
        message = Message.objects.select_related("campaign", "client", "run").get(pk=message_id)
    except Message.DoesNotExist:
        logger.warning("Message with id %s does not exist.", message_id)
        return

    with transaction.atomic():
        message = (
            Message.objects.select_for_update()
            .select_related("campaign", "client", "run")
            .get(pk=message_id)
        )
        if message.status == MessageStatus.SENT:
            _refresh_run_status(message.run)
            return
        if message.status != MessageStatus.QUEUED:
            message.status = MessageStatus.QUEUED
            message.save(update_fields=["status"])

    try:
        send_message_to_external_service(message, message.campaign)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to send message %s: %s", message.id, exc)
        message.status = MessageStatus.FAILED
        message.save(update_fields=["status"])
        raise
    else:
        message.status = MessageStatus.SENT
        message.save(update_fields=["status"])
    finally:
        _refresh_run_status(message.run)


@shared_task(bind=True)
def start_campaign_async(self, run_id: str) -> None:
    try:
        run = CampaignRun.objects.select_related("campaign").get(pk=run_id)
    except CampaignRun.DoesNotExist:
        logger.error("Campaign run %s does not exist.", run_id)
        return

    campaign = run.campaign
    recipients = campaign_recipients(campaign)

    with transaction.atomic():
        run = CampaignRun.objects.select_for_update().select_related("campaign").get(pk=run_id)
        campaign = run.campaign

        if run.status in {CampaignRunStatus.FINISHED, CampaignRunStatus.FAILED}:
            return

        now = timezone.now()
        for client in recipients:
            planned = calculate_planned_send_at(campaign, client)
            if planned is None:
                continue
            Message.objects.get_or_create(
                campaign=campaign,
                client=client,
                run=run,
                defaults={
                    "message_text": campaign.text_message,
                    "planned_send_at": planned,
                },
            )

        if not run.messages.exists():
            run.status = CampaignRunStatus.FAILED
            run.finished_at = now
            run.save(update_fields=["status", "finished_at"])
            if campaign.active_run_id == run.id:
                campaign.status = CampaignStatus.FAILED
                campaign.is_active = False
                campaign.save(update_fields=["status", "is_active"])
            return

        run.status = CampaignRunStatus.RUNNING
        run.started_at = run.started_at or now
        run.save(update_fields=["status", "started_at"])

        campaign.status = CampaignStatus.RUNNING
        campaign.is_active = True
        campaign.last_started_at = now
        campaign.active_run = run
        campaign.save(update_fields=["status", "is_active", "last_started_at", "active_run"])

    dispatch_due_messages.delay()
