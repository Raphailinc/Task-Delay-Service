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


class NewsletterSerializer(serializers.ModelSerializer):
    client_filter = serializers.JSONField(required=False)

    class Meta:
        model = Newsletter
        fields = "__all__"

    def validate(self, attrs):
        start = attrs.get("start_datetime") or getattr(self.instance, "start_datetime", None)
        end = attrs.get("end_datetime") or getattr(self.instance, "end_datetime", None)
        if start and end and start >= end:
            raise serializers.ValidationError("Время окончания должно быть больше времени начала.")
        return attrs

    def validate_client_filter(self, value):
        if value in (None, ""):
            return {}

        normalized = {"phone_numbers": [], "tags": [], "operator_codes": []}

        if isinstance(value, dict):
            for key in ("phone_numbers", "tags", "operator_codes"):
                if key in value and isinstance(value[key], (list, tuple)):
                    normalized[key] = [str(item) for item in value[key] if item]
            return normalized

        if isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    normalized["phone_numbers"].append(item)
                elif isinstance(item, dict):
                    phone = item.get("phone_number") or item.get("phone")
                    tag = item.get("tag")
                    operator = item.get("mobile_operator_code") or item.get("operator_code")
                    if phone:
                        normalized["phone_numbers"].append(str(phone))
                    if tag:
                        normalized["tags"].append(str(tag))
                    if operator:
                        normalized["operator_codes"].append(str(operator))
            return normalized

        raise serializers.ValidationError("client_filter должен быть словарем или списком.")


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = "__all__"
