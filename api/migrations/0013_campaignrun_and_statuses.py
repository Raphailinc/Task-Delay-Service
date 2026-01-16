import uuid

import django.db.models.deletion
from django.db import migrations, models
from django.utils import timezone


def backfill_runs(apps, schema_editor):
    Newsletter = apps.get_model("api", "Newsletter")
    CampaignRun = apps.get_model("api", "CampaignRun")
    Message = apps.get_model("api", "Message")
    now = timezone.now()

    for campaign in Newsletter.objects.all():
        run_status = "RUNNING" if campaign.is_active else "FINISHED"
        campaign_status = "RUNNING" if campaign.is_active else (campaign.status or "DRAFT")

        run = CampaignRun.objects.create(
            id=uuid.uuid4(),
            campaign=campaign,
            status=run_status,
            force_resend=False,
            started_at=now if campaign.is_active else None,
        )

        for message in Message.objects.filter(campaign=campaign, run__isnull=True):
            message.run = run
            message.planned_send_at = message.planned_send_at or message.created_at or now
            message.save(update_fields=["run", "planned_send_at"])

        campaign.active_run = run
        campaign.status = campaign_status
        campaign.save(update_fields=["active_run", "status"])


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0012_newsletter_is_active"),
    ]

    operations = [
        migrations.CreateModel(
            name="CampaignRun",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("SCHEDULED", "Scheduled"),
                            ("RUNNING", "Running"),
                            ("FINISHED", "Finished"),
                            ("FAILED", "Failed"),
                        ],
                        default="SCHEDULED",
                        max_length=20,
                    ),
                ),
                ("force_resend", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                (
                    "campaign",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="runs",
                        to="api.newsletter",
                    ),
                ),
            ],
        ),
        migrations.AddField(
            model_name="newsletter",
            name="active_run",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="api.campaignrun",
            ),
        ),
        migrations.AddField(
            model_name="newsletter",
            name="last_started_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="newsletter",
            name="status",
            field=models.CharField(
                choices=[
                    ("DRAFT", "Draft"),
                    ("SCHEDULED", "Scheduled"),
                    ("RUNNING", "Running"),
                    ("FINISHED", "Finished"),
                    ("PAUSED", "Paused"),
                    ("FAILED", "Failed"),
                ],
                default="DRAFT",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="message",
            name="planned_send_at",
            field=models.DateTimeField(default=timezone.now),
        ),
        migrations.AddField(
            model_name="message",
            name="run",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="messages",
                to="api.campaignrun",
            ),
        ),
        migrations.AlterField(
            model_name="message",
            name="status",
            field=models.CharField(
                choices=[
                    ("PENDING", "Pending"),
                    ("QUEUED", "Queued"),
                    ("SENT", "Sent"),
                    ("FAILED", "Failed"),
                ],
                default="PENDING",
                max_length=20,
            ),
        ),
        migrations.RunPython(backfill_runs, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="message",
            name="run",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="messages",
                to="api.campaignrun",
            ),
        ),
        migrations.AddConstraint(
            model_name="message",
            constraint=models.UniqueConstraint(
                fields=("campaign", "client", "run"), name="unique_message_per_run_per_client"
            ),
        ),
    ]
