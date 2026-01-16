import logging
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from typing import Iterable, Set
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db.models import QuerySet
from django.utils import timezone

from .models import Client, Newsletter

logger = logging.getLogger(__name__)


def _collect(value: Iterable) -> Set[str]:
    if not value:
        return set()
    if isinstance(value, str):
        return {value}
    return {str(item) for item in value if item}


def _as_zoneinfo(tz_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        logger.warning("Unknown timezone %s, falling back to settings.TIME_ZONE", tz_name)
        return timezone.get_default_timezone()


def campaign_recipients(campaign: Newsletter) -> QuerySet:
    """Return a queryset of clients that match campaign filters without widening the audience."""
    filter_data = campaign.client_filter or {}

    if isinstance(filter_data, list):
        aggregate = {"phone_numbers": [], "tags": [], "operator_codes": []}
        for item in filter_data:
            if isinstance(item, str):
                aggregate["phone_numbers"].append(item)
            elif isinstance(item, dict):
                aggregate["phone_numbers"].extend(
                    _collect([item.get("phone_number"), item.get("phone")])
                )
                aggregate["tags"].extend(_collect([item.get("tag")]))
                aggregate["operator_codes"].extend(
                    _collect([item.get("mobile_operator_code"), item.get("operator_code")])
                )
        filter_data = aggregate

    if not isinstance(filter_data, dict):
        filter_data = {}

    tags = _collect(filter_data.get("tags", []))
    operator_codes = _collect(filter_data.get("operator_codes", []))
    phone_numbers = _collect(filter_data.get("phone_numbers", []))

    if campaign.tag:
        tags.add(str(campaign.tag))

    if phone_numbers:
        queryset = Client.objects.filter(phone_number__in=phone_numbers)
        if tags:
            queryset = queryset.filter(tag__in=tags)
        if operator_codes:
            queryset = queryset.filter(mobile_operator_code__in=operator_codes)
        return queryset.distinct()

    if tags:
        queryset = Client.objects.filter(tag__in=tags)
        if operator_codes:
            queryset = queryset.filter(mobile_operator_code__in=operator_codes)
        return queryset.distinct()

    return Client.objects.none()


def calculate_planned_send_at(campaign: Newsletter, client: Client):
    """Calculate the first allowed send datetime for the client in their timezone."""
    tz = _as_zoneinfo(client.timezone)
    now_local = timezone.localtime(timezone.now(), tz)
    start_local = timezone.localtime(campaign.start_datetime, tz)
    start_from = max(start_local, now_local)
    end_local = timezone.localtime(campaign.end_datetime, tz)

    date_cursor = start_from.date()
    max_date = end_local.date() + timedelta(days=1)

    while date_cursor <= max_date:
        window_start_dt = datetime.combine(date_cursor, campaign.time_interval_start, tzinfo=tz)
        window_end_dt = datetime.combine(date_cursor, campaign.time_interval_end, tzinfo=tz)
        if campaign.time_interval_end < campaign.time_interval_start:
            window_end_dt += timedelta(days=1)

        if start_from > window_end_dt:
            date_cursor += timedelta(days=1)
            continue

        candidate = max(start_from, window_start_dt)
        if candidate <= window_end_dt and candidate <= end_local:
            return candidate.astimezone(dt_timezone.utc)

        date_cursor += timedelta(days=1)

    return None
