from django.urls import path

from .views import (
    ApiRoot,
    CampaignDetailView,
    CampaignListCreateView,
    CampaignStartView,
    CampaignStatsView,
    ClientDetailView,
    ClientListCreateView,
    MessageDetailView,
    MessageListCreateView,
)

urlpatterns = [
    path("", ApiRoot.as_view(), name="api-root"),
    path("clients/", ClientListCreateView.as_view(), name="client-list-create"),
    path("clients/<int:pk>/", ClientDetailView.as_view(), name="client-detail"),
    path("campaigns/", CampaignListCreateView.as_view(), name="campaign-list-create"),
    path("campaigns/<int:pk>/", CampaignDetailView.as_view(), name="campaign-detail"),
    path("campaigns/<int:pk>/start/", CampaignStartView.as_view(), name="campaign-start"),
    path("campaigns/stats/", CampaignStatsView.as_view(), name="campaign-stats"),
    path("campaigns/<int:pk>/stats/", CampaignStatsView.as_view(), name="campaign-stats-detail"),
    path("messages/", MessageListCreateView.as_view(), name="message-list-create"),
    path("messages/<int:pk>/", MessageDetailView.as_view(), name="message-detail"),
]
