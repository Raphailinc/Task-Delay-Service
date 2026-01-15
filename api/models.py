# models.py

from django.db import models
from django.db.models import JSONField
from django.utils import timezone


class Client(models.Model):
    id = models.AutoField(primary_key=True)
    phone_number = models.CharField(max_length=20)
    mobile_operator_code = models.CharField(max_length=3)
    tag = models.CharField(max_length=100)
    timezone = models.CharField(max_length=100)

    def __str__(self):
        return f"{self.phone_number} - {self.tag}"


class Newsletter(models.Model):
    id = models.AutoField(primary_key=True)
    start_datetime = models.DateTimeField()
    end_datetime = models.DateTimeField()
    text_message = models.TextField()
    time_interval_start = models.TimeField()
    time_interval_end = models.TimeField()
    tag = models.CharField(max_length=500, default="default_tag")
    client_filter = JSONField(default=list)
    is_active = models.BooleanField(default=False)

    def __str__(self):
        return f"Newsletter {self.id}"

    def is_within_time_interval(self):
        current_time = timezone.now().time()
        return self.time_interval_start <= current_time <= self.time_interval_end


class Message(models.Model):
    id = models.AutoField(primary_key=True)
    created_at = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=50, default="PENDING")
    campaign = models.ForeignKey(Newsletter, related_name="messages", on_delete=models.CASCADE)
    client = models.ForeignKey(Client, related_name="messages", on_delete=models.CASCADE)
    message_text = models.TextField()

    def __str__(self):
        return f"Message {self.id} - {self.status}"
