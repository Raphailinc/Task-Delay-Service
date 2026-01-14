import logging
from typing import Iterable, Set

from django.db.models import Q, QuerySet
from django.utils import timezone

from .models import Client, Newsletter

logger = logging.getLogger(__name__)


def _collect(value: Iterable) -> Set[str]:
    if not value:
        return set()
    if isinstance(value, str):
        return {value}
    return {str(item) for item in value if item}


def campaign_recipients(campaign: Newsletter) -> QuerySet:
    """Return a queryset of clients that match campaign filters and tag."""
    filters = Q()
    filter_data = campaign.client_filter or {}

    if isinstance(filter_data, list):
        aggregate = {"phone_numbers": [], "tags": [], "operator_codes": []}
        for item in filter_data:
            if isinstance(item, str):
                aggregate["phone_numbers"].append(item)
            elif isinstance(item, dict):
                aggregate["phone_numbers"].extend(_collect([item.get("phone_number"), item.get("phone")]))
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

    queryset = Client.objects.all()

    if tags:
        filters &= Q(tag__in=tags)
    if operator_codes:
        filters &= Q(mobile_operator_code__in=operator_codes)
    if filters:
        queryset = queryset.filter(filters)

    if phone_numbers:
        queryset = queryset | Client.objects.filter(phone_number__in=phone_numbers)

    return queryset.distinct()


def within_sending_window(campaign: Newsletter) -> bool:
    """Check if now is inside campaign dates and time interval."""
    now = timezone.localtime()
    if not (campaign.start_datetime <= now <= campaign.end_datetime):
        return False

    if campaign.time_interval_start <= campaign.time_interval_end:
        return campaign.time_interval_start <= now.time() <= campaign.time_interval_end

    # Handles overnight window (e.g., 22:00 - 06:00)
    return now.time() >= campaign.time_interval_start or now.time() <= campaign.time_interval_end
