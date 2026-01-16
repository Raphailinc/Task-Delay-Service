from datetime import time, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth.models import User
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from api.models import (
    CampaignRun,
    CampaignRunStatus,
    CampaignStatus,
    Client,
    Message,
    MessageStatus,
    Newsletter,
)
from api.serializers import ClientSerializer
from api.tasks import dispatch_due_messages, start_campaign_async
from api.utils import campaign_recipients


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_client():
    user = User.objects.create_user(username="tester", password="secret")
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def create_client(phone_number="79000000001", tag="vip", timezone_name="UTC", operator="900"):
    return Client.objects.create(
        phone_number=phone_number,
        mobile_operator_code=operator,
        tag=tag,
        timezone=timezone_name,
    )


def create_campaign(**kwargs):
    now = timezone.now()
    defaults = {
        "start_datetime": now - timedelta(minutes=1),
        "end_datetime": now + timedelta(hours=1),
        "text_message": "Hello",
        "time_interval_start": time(0, 0),
        "time_interval_end": time(23, 59),
        "tag": "vip",
        "client_filter": {},
    }
    defaults.update(kwargs)
    return Newsletter.objects.create(**defaults)


@pytest.mark.django_db
def test_client_serializer_validates_phone_length():
    serializer = ClientSerializer(
        data={
            "phone_number": "123",
            "mobile_operator_code": "999",
            "tag": "short",
            "timezone": "UTC",
        }
    )
    assert not serializer.is_valid()
    assert "phone_number" in serializer.errors


@pytest.mark.django_db
def test_permissions_required_for_create_and_start(api_client):
    now = timezone.now()
    campaign_payload = {
        "start_datetime": (now + timedelta(hours=1)).isoformat(),
        "end_datetime": (now + timedelta(hours=2)).isoformat(),
        "text_message": "Ping",
        "time_interval_start": time(9, 0).isoformat(),
        "time_interval_end": time(17, 0).isoformat(),
        "tag": "vip",
    }
    create_resp = api_client.post(reverse("campaign-list-create"), campaign_payload, format="json")
    assert create_resp.status_code in {status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN}

    campaign = create_campaign()
    start_resp = api_client.post(reverse("campaign-start", args=[campaign.id]), format="json")
    assert start_resp.status_code in {status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN}


@pytest.mark.django_db
def test_phone_numbers_only_are_used_when_provided():
    target = create_client(phone_number="79000000001", tag="vip")
    create_client(phone_number="79000000002", tag="vip")
    create_client(phone_number="79000000003", tag="other")

    campaign = create_campaign(tag="", client_filter={"phone_numbers": [target.phone_number]})
    recipients = campaign_recipients(campaign)

    assert set(recipients.values_list("id", flat=True)) == {target.id}


@pytest.mark.django_db
def test_tag_used_when_no_phone_numbers():
    vip1 = create_client(phone_number="79000000001", tag="vip")
    vip2 = create_client(phone_number="79000000002", tag="vip")
    create_client(phone_number="79000000003", tag="basic")

    campaign = create_campaign(tag="vip", client_filter={})
    recipients = campaign_recipients(campaign)

    assert set(recipients.values_list("id", flat=True)) == {vip1.id, vip2.id}


@pytest.mark.django_db
def test_start_rejected_for_empty_audience(auth_client):
    campaign = create_campaign(tag="", client_filter={})
    response = auth_client.post(reverse("campaign-start", args=[campaign.id]), format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert Message.objects.count() == 0


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
@pytest.mark.django_db
def test_idempotent_start_conflict_without_force(auth_client):
    create_client(tag="vip")
    campaign = create_campaign()

    first = auth_client.post(reverse("campaign-start", args=[campaign.id]), format="json")
    assert first.status_code == status.HTTP_202_ACCEPTED
    start_campaign_async(first.json()["run_id"])
    assert Message.objects.count() == 1
    assert CampaignRun.objects.count() == 1

    second = auth_client.post(reverse("campaign-start", args=[campaign.id]), format="json")
    assert second.status_code == status.HTTP_409_CONFLICT
    assert Message.objects.count() == 1
    assert CampaignRun.objects.count() == 1


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
@pytest.mark.django_db
def test_update_active_campaign_does_not_restart(auth_client):
    create_client(tag="vip")
    campaign = create_campaign()

    start_resp = auth_client.post(reverse("campaign-start", args=[campaign.id]), format="json")
    assert start_resp.status_code == status.HTTP_202_ACCEPTED

    runs_before = CampaignRun.objects.count()
    messages_before = Message.objects.count()

    update_resp = auth_client.patch(
        reverse("campaign-detail", args=[campaign.id]),
        {"text_message": "Updated message"},
        format="json",
    )
    assert update_resp.status_code == status.HTTP_200_OK
    assert CampaignRun.objects.count() == runs_before
    assert Message.objects.count() == messages_before


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
@pytest.mark.django_db
def test_planned_send_respects_client_timezone(auth_client):
    tz = ZoneInfo("Europe/Moscow")
    now = timezone.now()
    start = now.replace(hour=5, minute=0, second=0, microsecond=0)
    if start < now:
        start += timedelta(days=1)
    end = start + timedelta(hours=18)

    create_client(phone_number="79000000007", tag="vip", timezone_name="Europe/Moscow")
    campaign = create_campaign(
        start_datetime=start,
        end_datetime=end,
        time_interval_start=time(9, 0),
        time_interval_end=time(17, 0),
    )

    response = auth_client.post(reverse("campaign-start", args=[campaign.id]), format="json")
    assert response.status_code == status.HTTP_202_ACCEPTED
    start_campaign_async(response.json()["run_id"])

    message = Message.objects.first()
    local_time = message.planned_send_at.astimezone(tz)
    assert time(9, 0) <= local_time.time() <= time(17, 0)
    assert local_time.date() == start.astimezone(tz).date()


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
@pytest.mark.django_db
def test_start_before_window_moves_to_next_slot(auth_client):
    tz = ZoneInfo("Europe/Moscow")
    now = timezone.now()
    start = now.replace(hour=18, minute=0, second=0, microsecond=0)
    if start < now:
        start += timedelta(days=1)
    end = start + timedelta(days=1)

    create_client(phone_number="79000000009", tag="vip", timezone_name="Europe/Moscow")
    campaign = create_campaign(
        start_datetime=start,
        end_datetime=end,
        time_interval_start=time(9, 0),
        time_interval_end=time(17, 0),
    )

    response = auth_client.post(reverse("campaign-start", args=[campaign.id]), format="json")
    assert response.status_code == status.HTTP_202_ACCEPTED
    start_campaign_async(response.json()["run_id"])

    message = Message.objects.first()
    local_time = message.planned_send_at.astimezone(tz)
    expected_date = start.astimezone(tz).date() + timedelta(days=1)
    assert local_time.date() == expected_date
    assert time(9, 0) <= local_time.time() <= time(17, 0)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=False)
@pytest.mark.django_db
def test_provider_failure_marks_failed_without_duplicates(auth_client):
    client = create_client(tag="vip")
    campaign = create_campaign()
    run = CampaignRun.objects.create(campaign=campaign, status=CampaignRunStatus.RUNNING)
    campaign.active_run = run
    campaign.status = CampaignStatus.RUNNING
    campaign.save(update_fields=["active_run", "status"])
    message = Message.objects.create(
        campaign=campaign,
        client=client,
        run=run,
        message_text="Boom",
        planned_send_at=timezone.now(),
        status=MessageStatus.PENDING,
    )

    from unittest import mock

    with mock.patch("api.tasks.send_message_to_external_service", side_effect=Exception("boom")):
        dispatch_due_messages()

    message.refresh_from_db()
    run.refresh_from_db()
    assert Message.objects.count() == 1
    assert message.status == MessageStatus.FAILED
    assert run.status in {CampaignRunStatus.FAILED, CampaignRunStatus.RUNNING}
