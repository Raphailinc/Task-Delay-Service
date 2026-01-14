import logging

from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Client, Message, Newsletter
from .serializers import ClientSerializer, MessageSerializer, NewsletterSerializer
from .tasks import start_campaign_async
from .utils import campaign_recipients, within_sending_window

logger = logging.getLogger(__name__)


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
        return Response({"message": "Client successfully deleted"}, status=status.HTTP_204_NO_CONTENT)


class CampaignListCreateView(generics.ListCreateAPIView):
    queryset = Newsletter.objects.all().order_by("-start_datetime")
    serializer_class = NewsletterSerializer

    def perform_create(self, serializer):
        campaign = serializer.save()
        self.schedule_campaign_start(campaign)

    def schedule_campaign_start(self, campaign: Newsletter) -> None:
        eta = campaign.start_datetime
        if eta <= timezone.now():
            start_campaign_async.delay(campaign.id)
        else:
            start_campaign_async.apply_async(args=[campaign.id], eta=eta)


class CampaignDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Newsletter.objects.all()
    serializer_class = NewsletterSerializer

    def perform_update(self, serializer):
        campaign = serializer.save()
        if campaign.is_active:
            start_campaign_async.delay(campaign.id)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return Response({"message": "Campaign successfully deleted"}, status=status.HTTP_204_NO_CONTENT)


class CampaignStartView(APIView):
    def post(self, request, pk, format=None):
        campaign = get_object_or_404(Newsletter, pk=pk)
        start_campaign_async.delay(campaign.id)
        campaign.is_active = True
        campaign.save(update_fields=["is_active"])
        return Response({"status": "scheduled"}, status=status.HTTP_202_ACCEPTED)


class MessageListCreateView(generics.ListCreateAPIView):
    queryset = Message.objects.all()
    serializer_class = MessageSerializer


class MessageDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Message.objects.all()
    serializer_class = MessageSerializer

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return Response({"message": "Message successfully deleted"}, status=status.HTTP_204_NO_CONTENT)


class CampaignStatsView(APIView):
    def get(self, request, pk=None, format=None):
        if pk is None:
            stats = Newsletter.objects.annotate(
                total_messages=Count("messages"),
                sent_messages=Count("messages", filter=Q(messages__status="SENT")),
                failed_messages=Count("messages", filter=Q(messages__status="FAILED")),
                recipients=Count("messages__client", distinct=True),
            ).values("id", "total_messages", "sent_messages", "failed_messages", "recipients")
            return Response(stats)

        campaign = get_object_or_404(Newsletter, pk=pk)
        if within_sending_window(campaign):
            eligible = campaign_recipients(campaign).count()
        else:
            eligible = 0

        stats = {
            "id": campaign.id,
            "total_messages": campaign.messages.count(),
            "sent_messages": campaign.messages.filter(status="SENT").count(),
            "failed_messages": campaign.messages.filter(status="FAILED").count(),
            "eligible_clients": eligible,
        }
        return Response(stats)
