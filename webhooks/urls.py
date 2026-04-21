"""
Webhook URL Configuration
"""
from django.urls import path
from . import views

urlpatterns = [
    # Nonbor API webhook — yangi buyurtma kelganda push qiladi
    path('nonbor/', views.nonbor_webhook, name='nonbor_webhook'),

    # API webhook - tashqi API dan buyurtmalar qabul qilish
    path('api/', views.api_webhook, name='api_webhook'),

    # Health check endpoint
    path('health/', views.health_check, name='health_check'),

    # Manual order send (testing uchun)
    path('test-order/', views.test_order, name='test_order'),
]
