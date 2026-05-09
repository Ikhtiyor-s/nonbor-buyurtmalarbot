from django.urls import path
from . import api_views

urlpatterns = [
    # IP telefon: kim chaqirilishi kerakligini olish
    path('pending-calls/', api_views.pending_calls, name='pending_calls'),

    # IP telefon statistikasi (bugun)
    path('call-stats/', api_views.call_stats, name='call_stats'),

    # Barcha kutilayotgan buyurtmalar (umumiy holat)
    path('order-status/', api_views.order_status, name='order_status'),
]
