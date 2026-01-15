from datetime import timedelta

import pytest
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from api.models import Client, Message, Newsletter
from api.serializers import ClientSerializer
from api.tasks import start_campaign_async
from api.utils import campaign_recipients


@pytest.fixture
def api_client():
    return APIClient()


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
def test_campaign_recipients_filters_by_tag_and_phone():
    tagged = Client.objects.create(
        phone_number="79000000001", mobile_operator_code="900", tag="vip", timezone="UTC"
    )
    tagged2 = Client.objects.create(
        phone_number="79000000002", mobile_operator_code="901", tag="vip", timezone="UTC"
    )
    other = Client.objects.create(
        phone_number="79000000003", mobile_operator_code="900", tag="common", timezone="UTC"
    )

    campaign = Newsletter.objects.create(
        start_datetime=timezone.now(),
        end_datetime=timezone.now() + timedelta(hours=1),
        text_message="Hello",
        time_interval_start=timezone.now().time(),
        time_interval_end=(timezone.now() + timedelta(minutes=30)).time(),
        tag="vip",
        client_filter={"phone_numbers": [other.phone_number]},
    )

    recipients = campaign_recipients(campaign)
    assert sorted(recipients.values_list("phone_number", flat=True)) == sorted(
        [tagged.phone_number, tagged2.phone_number, other.phone_number]
    )


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
@pytest.mark.django_db
def test_start_campaign_creates_messages_and_marks_sent():
    _client1 = Client.objects.create(
        phone_number="79000000001", mobile_operator_code="900", tag="vip", timezone="UTC"
    )
    _client2 = Client.objects.create(
        phone_number="79000000002", mobile_operator_code="901", tag="vip", timezone="UTC"
    )

    now = timezone.now()
    campaign = Newsletter.objects.create(
        start_datetime=now - timedelta(minutes=1),
        end_datetime=now + timedelta(hours=1),
        text_message="Ping",
        time_interval_start=(now - timedelta(minutes=5)).time(),
        time_interval_end=(now + timedelta(minutes=5)).time(),
        tag="vip",
    )

    start_campaign_async.delay(campaign.id)

    assert Message.objects.count() == 2
    assert set(Message.objects.values_list("status", flat=True)) == {"SENT"}


@pytest.mark.django_db
def test_campaign_stats_endpoint(api_client):
    now = timezone.now()
    campaign = Newsletter.objects.create(
        start_datetime=now,
        end_datetime=now + timedelta(hours=1),
        text_message="Hello",
        time_interval_start=now.time(),
        time_interval_end=(now + timedelta(minutes=10)).time(),
    )
    client = Client.objects.create(
        phone_number="79000000004", mobile_operator_code="902", tag="stats", timezone="UTC"
    )
    Message.objects.create(campaign=campaign, client=client, message_text="Hello", status="SENT")

    response = api_client.get(reverse("campaign-stats-detail", args=[campaign.id]))
    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["sent_messages"] == 1
