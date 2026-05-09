from django.urls import path
from . import api_views

urlpatterns = [
    # IP telefon: kim chaqirilishi kerakligini olish
    path('pending-calls/', api_views.pending_calls, name='pending_calls'),

    # IP telefon statistikasi (bugun)
    path('call-stats/', api_views.call_stats, name='call_stats'),

    # Barcha kutilayotgan buyurtmalar (umumiy holat)
    path('order-status/', api_views.order_status, name='order_status'),

    # Server ishlamasa admin chaqirish signali
    path('admin-alert/', api_views.admin_alert, name='admin_alert'),

    # Signal qabul qilindi (Asterisk chaqirganini bildiradi)
    path('admin-alert/ack/', api_views.admin_alert_ack, name='admin_alert_ack'),
]
