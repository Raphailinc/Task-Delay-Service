from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta
from datetime import timezone as dt_timezone
from threading import Event
from unittest.mock import patch

import pytest
from celery.exceptions import Retry
from django.contrib.auth.models import User
from django.db import close_old_connections, connection
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import (
    CampaignRun,
    CampaignRunStatus,
    CampaignStatus,
    Message,
    MessageStatus,
)
from api.tasks import send_message_async, start_campaign_async

from .tests import create_campaign, create_client


def queued_message(**campaign_fields):
    campaign = create_campaign(**campaign_fields)
    run = CampaignRun.objects.create(campaign=campaign, status=CampaignRunStatus.RUNNING)
    campaign.active_run = run
    campaign.status = CampaignStatus.RUNNING
    campaign.save(update_fields=["active_run", "status"])
    return Message.objects.create(
        campaign=campaign,
        client=create_client(),
        run=run,
        message_text="Demo",
        status=MessageStatus.QUEUED,
    )


@pytest.mark.django_db
def test_duplicate_delivery_cannot_enter_provider_during_an_active_send():
    message = queued_message()

    def provider(*args):
        message.refresh_from_db()
        assert message.status == MessageStatus.SENDING
        send_message_async.run(message.id)

    with patch("api.tasks.send_message_to_external_service", side_effect=provider) as send:
        send_message_async.run(message.id)
        send_message_async.run(message.id)
    assert send.call_count == 1
    message.refresh_from_db()
    message.run.refresh_from_db()
    assert message.status == MessageStatus.SENT
    assert message.run.status == CampaignRunStatus.FINISHED


@pytest.mark.django_db
@pytest.mark.parametrize("state", [MessageStatus.PENDING, MessageStatus.FAILED])
def test_late_broker_delivery_does_not_revive_unqueued_messages(state):
    message = queued_message()
    Message.objects.filter(pk=message.pk).update(status=state)
    with patch("api.tasks.send_message_to_external_service") as send:
        send_message_async.run(message.id)
    send.assert_not_called()
    message.refresh_from_db()
    assert message.status == state


@pytest.mark.django_db
def test_provider_retry_keeps_run_active_until_retry_budget_is_exhausted():
    message = queued_message()
    with (
        patch("api.tasks.send_message_to_external_service", side_effect=RuntimeError("offline")),
        patch.object(send_message_async, "retry", side_effect=Retry()) as retry,
    ):
        with pytest.raises(Retry):
            send_message_async.run(message.id)
    retry.assert_called_once()
    message.refresh_from_db()
    message.run.refresh_from_db()
    assert message.status == MessageStatus.QUEUED
    assert message.run.status == CampaignRunStatus.RUNNING
    assert message.run.finished_at is None


@pytest.mark.django_db
def test_retry_exhaustion_is_terminal_and_duplicate_delivery_cannot_restart_it():
    message = queued_message()
    send_message_async.push_request(retries=send_message_async.max_retries)
    try:
        with patch(
            "api.tasks.send_message_to_external_service", side_effect=RuntimeError("offline")
        ):
            with pytest.raises(RuntimeError, match="offline"):
                send_message_async.run(message.id)
    finally:
        send_message_async.pop_request()
    message.refresh_from_db()
    message.run.refresh_from_db()
    assert message.status == MessageStatus.FAILED
    assert message.run.status == CampaignRunStatus.FAILED
    assert message.run.finished_at is not None
    with patch("api.tasks.send_message_to_external_service") as send:
        send_message_async.run(message.id)
    send.assert_not_called()


@pytest.mark.django_db
def test_successful_retry_finishes_run():
    message = queued_message()
    with (
        patch("api.tasks.send_message_to_external_service", side_effect=RuntimeError("offline")),
        patch.object(send_message_async, "retry", side_effect=Retry()),
    ):
        with pytest.raises(Retry):
            send_message_async.run(message.id)
    with patch("api.tasks.send_message_to_external_service") as send:
        send_message_async.run(message.id)
    send.assert_called_once()
    message.run.refresh_from_db()
    assert message.run.status == CampaignRunStatus.FINISHED


@pytest.mark.django_db
def test_expired_campaign_never_calls_provider():
    message = queued_message(end_datetime=timezone.now() - timedelta(seconds=1))
    with patch("api.tasks.send_message_to_external_service") as send:
        send_message_async.run(message.id)
    send.assert_not_called()
    message.refresh_from_db()
    assert message.status == MessageStatus.FAILED


@pytest.mark.django_db
def test_future_queued_message_cannot_be_sent_early():
    message = queued_message()
    Message.objects.filter(pk=message.pk).update(
        planned_send_at=timezone.now() + timedelta(hours=1)
    )
    with patch("api.tasks.send_message_to_external_service") as send:
        send_message_async.run(message.id)
    send.assert_not_called()


@pytest.mark.django_db
def test_delayed_broker_delivery_waits_for_the_next_daily_window():
    now = datetime(2030, 1, 2, 18, tzinfo=dt_timezone.utc)
    message = queued_message(
        start_datetime=now - timedelta(days=1),
        end_datetime=now + timedelta(days=1),
        time_interval_start=time(9),
        time_interval_end=time(17),
    )
    Message.objects.filter(pk=message.pk).update(planned_send_at=now - timedelta(hours=2))
    with (
        patch("api.tasks.timezone.now", return_value=now),
        patch("api.tasks.send_message_to_external_service") as send,
    ):
        send_message_async.run(message.id)
    send.assert_not_called()
    message.refresh_from_db()
    assert message.status == MessageStatus.PENDING
    assert message.planned_send_at == datetime(2030, 1, 3, 9, tzinfo=dt_timezone.utc)


@pytest.mark.django_db
def test_force_resend_cannot_overlap_an_active_run():
    auth_client = APIClient()
    auth_client.force_authenticate(user=User.objects.create_user(username="operator"))
    message = queued_message()
    response = auth_client.post(
        reverse("campaign-start", args=[message.campaign_id]),
        {"force_resend": True},
        format="json",
    )
    assert response.status_code == 409
    assert CampaignRun.objects.count() == 1


@pytest.mark.django_db
def test_duplicate_start_does_not_add_new_recipients_to_existing_run():
    message = queued_message()
    message.run.started_at = timezone.now()
    message.run.save(update_fields=["started_at"])
    create_client(phone_number="79000000002")
    with patch("api.tasks.dispatch_due_messages.delay") as dispatch:
        start_campaign_async.run(str(message.run_id))
    dispatch.assert_not_called()
    assert Message.objects.count() == 1


@pytest.mark.django_db
def test_superseded_run_cannot_replace_the_active_run():
    message = queued_message()
    newer = CampaignRun.objects.create(campaign=message.campaign)
    campaign = message.campaign
    campaign.active_run = newer
    campaign.save(update_fields=["active_run"])
    with patch("api.tasks.dispatch_due_messages.delay") as dispatch:
        start_campaign_async.run(str(message.run_id))
    dispatch.assert_not_called()
    campaign.refresh_from_db()
    assert campaign.active_run_id == newer.id


@pytest.mark.django_db(transaction=True)
def test_two_postgresql_workers_call_provider_once():
    if connection.vendor != "postgresql":
        pytest.skip("Real concurrent connections are exercised by PostgreSQL CI")
    message = queued_message()
    entered = Event()
    release = Event()

    def provider(*args):
        entered.set()
        assert release.wait(5), "Concurrent delivery test timed out"

    def worker():
        close_old_connections()
        try:
            send_message_async.run(message.id)
        finally:
            close_old_connections()

    with patch("api.tasks.send_message_to_external_service", side_effect=provider) as send:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(worker)
            try:
                assert entered.wait(5)
                pool.submit(worker).result(timeout=5)
                assert send.call_count == 1
            finally:
                release.set()
            first.result(timeout=5)
    message.refresh_from_db()
    assert message.status == MessageStatus.SENT
