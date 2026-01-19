"""
URL configuration for seller-bot project.
"""
from django.urls import path, include

urlpatterns = [
    path('webhook/', include('webhooks.urls')),
]
