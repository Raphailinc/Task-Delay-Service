from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from rest_framework import serializers

from .models import Client, Message, Newsletter


class ClientSerializer(serializers.ModelSerializer):
    class Meta:
        model = Client
        fields = "__all__"

    def validate_phone_number(self, value):
        digits = "".join(filter(str.isdigit, value))
        if len(digits) < 10:
            raise serializers.ValidationError("Телефон должен содержать не менее 10 цифр.")
        return value

    def validate_timezone(self, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise serializers.ValidationError("Неизвестный часовой пояс.") from None
        return value


class NewsletterSerializer(serializers.ModelSerializer):
    client_filter = serializers.JSONField(required=False)

    class Meta:
        model = Newsletter
        fields = "__all__"
        read_only_fields = ("status", "is_active", "last_started_at", "active_run")

    def validate(self, attrs):
        start = attrs.get("start_datetime") or getattr(self.instance, "start_datetime", None)
        end = attrs.get("end_datetime") or getattr(self.instance, "end_datetime", None)
        if start and end and start >= end:
            raise serializers.ValidationError("Время окончания должно быть больше времени начала.")

        client_filter = (
            attrs.get("client_filter", getattr(self.instance, "client_filter", {})) or {}
        )
        tag = attrs.get("tag", getattr(self.instance, "tag", ""))
        phone_numbers = []
        tags = []
        if isinstance(client_filter, dict):
            phone_numbers = client_filter.get("phone_numbers") or []
            tags = client_filter.get("tags") or []

        if not tag and not phone_numbers and not tags:
            raise serializers.ValidationError(
                "Аудитория не задана: укажите tag или phone_numbers в client_filter."
            )
        return attrs

    def validate_client_filter(self, value):
        if value in (None, ""):
            return {}

        normalized = {"phone_numbers": [], "tags": [], "operator_codes": []}

        def normalize_item(item):
            if not isinstance(item, (str, int)) or isinstance(item, bool):
                raise serializers.ValidationError(
                    "Значения фильтра должны быть строками или числами."
                )
            return str(item).strip()

        if isinstance(value, dict):
            if set(value) - set(normalized):
                raise serializers.ValidationError("Неизвестное поле client_filter.")
            for key in ("phone_numbers", "tags", "operator_codes"):
                if key in value:
                    if not isinstance(value[key], (list, tuple)):
                        raise serializers.ValidationError(f"{key} должен быть списком.")
                    normalized[key] = [normalize_item(item) for item in value[key] if item]
            return normalized

        if isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    if item.strip():
                        normalized["phone_numbers"].append(item.strip())
                elif isinstance(item, dict):
                    if set(item) - {
                        "phone_number",
                        "phone",
                        "tag",
                        "mobile_operator_code",
                        "operator_code",
                    }:
                        raise serializers.ValidationError("Неизвестное поле client_filter.")
                    phone = item.get("phone_number") or item.get("phone")
                    tag = item.get("tag")
                    operator = item.get("mobile_operator_code") or item.get("operator_code")
                    if phone:
                        normalized["phone_numbers"].append(normalize_item(phone))
                    if tag:
                        normalized["tags"].append(normalize_item(tag))
                    if operator:
                        normalized["operator_codes"].append(normalize_item(operator))
                else:
                    raise serializers.ValidationError(
                        "Элементы client_filter должны быть строками или объектами."
                    )
            return normalized

        raise serializers.ValidationError("client_filter должен быть словарем или списком.")


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = "__all__"
        read_only_fields = ("status", "planned_send_at", "created_at")


class CampaignStartSerializer(serializers.Serializer):
    force_resend = serializers.BooleanField(default=False)
