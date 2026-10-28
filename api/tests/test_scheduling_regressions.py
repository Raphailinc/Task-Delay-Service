from datetime import datetime, time, timedelta
from datetime import timezone as dt_timezone
from unittest.mock import patch

import pytest

from api.serializers import ClientSerializer, NewsletterSerializer
from api.utils import calculate_planned_send_at

from .tests import create_campaign, create_client


@pytest.mark.django_db
def test_broker_publish_failure_leaves_message_dispatchable():
    from api.models import CampaignRun, Message, MessageStatus
    from api.tasks import dispatch_due_messages

    campaign = create_campaign()
    run = CampaignRun.objects.create(campaign=campaign)
    message = Message.objects.create(
        campaign=campaign,
        client=create_client(),
        run=run,
        message_text="Hello",
        status=MessageStatus.PENDING,
    )
    with patch("api.tasks.send_message_async.delay", side_effect=RuntimeError("broker offline")):
        with pytest.raises(RuntimeError, match="broker offline"):
            dispatch_due_messages()
    message.refresh_from_db()
    assert message.status == MessageStatus.PENDING


@pytest.mark.django_db
@pytest.mark.parametrize("now_hour, expected_hour", [(1, 1), (3, 22)])
def test_overnight_window_includes_previous_evening(now_hour, expected_hour):
    now = datetime(2030, 1, 2, now_hour, tzinfo=dt_timezone.utc)
    campaign = create_campaign(
        start_datetime=now - timedelta(days=1),
        end_datetime=now + timedelta(days=1),
        time_interval_start=time(22),
        time_interval_end=time(2),
    )
    client = create_client()
    with patch("api.utils.timezone.now", return_value=now):
        planned = calculate_planned_send_at(campaign, client)
    assert planned == now.replace(hour=expected_hour)


@pytest.mark.django_db
def test_overnight_window_does_not_skip_last_possible_slot():
    now = datetime(2030, 1, 2, 1, tzinfo=dt_timezone.utc)
    campaign = create_campaign(
        start_datetime=now,
        end_datetime=now + timedelta(minutes=30),
        time_interval_start=time(22),
        time_interval_end=time(2),
    )
    with patch("api.utils.timezone.now", return_value=now):
        assert calculate_planned_send_at(campaign, create_client()) == now


@pytest.mark.parametrize("tz_name", ["../UTC", "/etc/passwd", "Invalid/Timezone"])
def test_invalid_timezone_is_a_validation_error(tz_name):
    serializer = ClientSerializer(
        data={
            "phone_number": "79000000001",
            "mobile_operator_code": "900",
            "tag": "vip",
            "timezone": tz_name,
        }
    )
    assert not serializer.is_valid()
    assert "timezone" in serializer.errors


@pytest.mark.django_db
def test_partial_update_cannot_clear_the_entire_audience():
    campaign = create_campaign(tag="vip", client_filter={})
    serializer = NewsletterSerializer(campaign, data={"tag": ""}, partial=True)
    assert not serializer.is_valid()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "value",
    [
        {"phone_numbers": "79000000001"},
        {"tags": 42},
        {"phone_numbers": [{"unexpected": "object"}]},
        {"unknown": ["vip"]},
    ],
)
def test_malformed_filters_are_rejected_instead_of_widening_audience(value):
    campaign = create_campaign()
    serializer = NewsletterSerializer(campaign, data={"client_filter": value}, partial=True)
    assert not serializer.is_valid()
    assert "client_filter" in serializer.errors
