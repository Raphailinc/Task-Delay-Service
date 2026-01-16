import logging

from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    CampaignRun,
    CampaignRunStatus,
    CampaignStatus,
    Client,
    Message,
    MessageStatus,
    Newsletter,
)
from .serializers import (
    CampaignStartSerializer,
    ClientSerializer,
    MessageSerializer,
    NewsletterSerializer,
)
from .tasks import start_campaign_async
from .utils import campaign_recipients

logger = logging.getLogger(__name__)


def _schedule_campaign_run(campaign: Newsletter, *, force_resend: bool) -> CampaignRun:
    now = timezone.now()
    start_at = campaign.start_datetime
    run_status = CampaignRunStatus.SCHEDULED if start_at > now else CampaignRunStatus.RUNNING
    run = CampaignRun.objects.create(
        campaign=campaign,
        status=run_status,
        force_resend=force_resend,
    )
    campaign.active_run = run
    campaign.status = (
        CampaignStatus.SCHEDULED
        if run_status == CampaignRunStatus.SCHEDULED
        else CampaignStatus.RUNNING
    )
    campaign.is_active = run_status == CampaignRunStatus.RUNNING
    if campaign.is_active:
        campaign.last_started_at = now
    campaign.save(update_fields=["status", "is_active", "last_started_at", "active_run"])
    if run_status == CampaignRunStatus.SCHEDULED:
        transaction.on_commit(
            lambda: start_campaign_async.apply_async(args=[str(run.id)], eta=start_at)
        )
    else:
        transaction.on_commit(lambda: start_campaign_async.delay(str(run.id)))
    return run


class ApiRoot(APIView):
    def get(self, request, format=None):
        return Response(
            {
                "clients": reverse("client-list-create"),
                "campaigns": reverse("campaign-list-create"),
            },
            content_type="application/json",
        )


class ClientListCreateView(generics.ListCreateAPIView):
    queryset = Client.objects.all()
    serializer_class = ClientSerializer


class ClientDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Client.objects.all()
    serializer_class = ClientSerializer

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return Response(
            {"message": "Client successfully deleted"}, status=status.HTTP_204_NO_CONTENT
        )


class CampaignListCreateView(generics.ListCreateAPIView):
    queryset = Newsletter.objects.all().order_by("-start_datetime")
    serializer_class = NewsletterSerializer

    def perform_create(self, serializer):
        campaign = serializer.save()
        _schedule_campaign_run(campaign, force_resend=False)


class CampaignDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Newsletter.objects.all()
    serializer_class = NewsletterSerializer

    def perform_update(self, serializer):
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return Response(
            {"message": "Campaign successfully deleted"}, status=status.HTTP_204_NO_CONTENT
        )


class CampaignStartView(APIView):
    def post(self, request, pk, format=None):
        payload = request.data or request.query_params
        start_serializer = CampaignStartSerializer(data=payload)
        start_serializer.is_valid(raise_exception=True)
        force_resend = start_serializer.validated_data.get("force_resend", False)

        with transaction.atomic():
            campaign = get_object_or_404(Newsletter.objects.select_for_update(), pk=pk)
            if (
                campaign.status
                in {CampaignStatus.RUNNING, CampaignStatus.SCHEDULED, CampaignStatus.FINISHED}
                and not force_resend
            ):
                return Response(
                    {"detail": "Campaign is already scheduled or running."},
                    status=status.HTTP_409_CONFLICT,
                )

            recipients = campaign_recipients(campaign)
            if not recipients.exists():
                return Response(
                    {"detail": "Аудитория пуста, запуск невозможен."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            run = _schedule_campaign_run(campaign, force_resend=force_resend)

        return Response(
            {"status": "scheduled", "run_id": str(run.id)}, status=status.HTTP_202_ACCEPTED
        )


class MessageListCreateView(generics.ListCreateAPIView):
    queryset = Message.objects.all()
    serializer_class = MessageSerializer


class MessageDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Message.objects.all()
    serializer_class = MessageSerializer

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return Response(
            {"message": "Message successfully deleted"}, status=status.HTTP_204_NO_CONTENT
        )


class CampaignStatsView(APIView):
    def get(self, request, pk=None, format=None):
        if pk is None:
            stats = Newsletter.objects.annotate(
                total_messages=Count("messages"),
                sent_messages=Count("messages", filter=Q(messages__status=MessageStatus.SENT)),
                failed_messages=Count("messages", filter=Q(messages__status=MessageStatus.FAILED)),
                recipients=Count("messages__client", distinct=True),
            ).values(
                "id", "total_messages", "sent_messages", "failed_messages", "recipients", "status"
            )
            return Response(stats)

        campaign = get_object_or_404(Newsletter, pk=pk)
        eligible = campaign_recipients(campaign).count()

        stats = {
            "id": campaign.id,
            "total_messages": campaign.messages.count(),
            "sent_messages": campaign.messages.filter(status=MessageStatus.SENT).count(),
            "failed_messages": campaign.messages.filter(status=MessageStatus.FAILED).count(),
            "eligible_clients": eligible,
            "status": campaign.status,
        }
        return Response(stats)
