# models.py

import uuid

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


class CampaignStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    SCHEDULED = "SCHEDULED", "Scheduled"
    RUNNING = "RUNNING", "Running"
    FINISHED = "FINISHED", "Finished"
    PAUSED = "PAUSED", "Paused"
    FAILED = "FAILED", "Failed"


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
    status = models.CharField(
        max_length=20, choices=CampaignStatus.choices, default=CampaignStatus.DRAFT
    )
    active_run = models.ForeignKey(
        "api.CampaignRun", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    last_started_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Newsletter {self.id}"

    def is_within_time_interval(self):
        current_time = timezone.now().time()
        return self.time_interval_start <= current_time <= self.time_interval_end


class CampaignRunStatus(models.TextChoices):
    SCHEDULED = "SCHEDULED", "Scheduled"
    RUNNING = "RUNNING", "Running"
    FINISHED = "FINISHED", "Finished"
    FAILED = "FAILED", "Failed"


class CampaignRun(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    campaign = models.ForeignKey(Newsletter, related_name="runs", on_delete=models.CASCADE)
    status = models.CharField(
        max_length=20, choices=CampaignRunStatus.choices, default=CampaignRunStatus.SCHEDULED
    )
    force_resend = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"Run {self.id} ({self.status})"


class MessageStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    QUEUED = "QUEUED", "Queued"
    SENT = "SENT", "Sent"
    FAILED = "FAILED", "Failed"


class Message(models.Model):
    id = models.AutoField(primary_key=True)
    created_at = models.DateTimeField(default=timezone.now)
    planned_send_at = models.DateTimeField(default=timezone.now)
    status = models.CharField(
        max_length=20, choices=MessageStatus.choices, default=MessageStatus.PENDING
    )
    campaign = models.ForeignKey(Newsletter, related_name="messages", on_delete=models.CASCADE)
    client = models.ForeignKey(Client, related_name="messages", on_delete=models.CASCADE)
    run = models.ForeignKey(CampaignRun, related_name="messages", on_delete=models.CASCADE)
    message_text = models.TextField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["campaign", "client", "run"], name="unique_message_per_run_per_client"
            )
        ]

    def __str__(self):
        return f"Message {self.id} - {self.status}"
