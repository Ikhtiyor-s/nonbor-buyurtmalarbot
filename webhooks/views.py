"""
Webhook Views - API dan kelgan xabarlarni qabul qilish
"""
import json
import logging
import asyncio
from datetime import datetime

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET
from django.conf import settings

from bot.core import NotificationBot

logger = logging.getLogger('webhooks')


def run_async(coro):
    """
    Async funksiyani sync kontekstda ishga tushirish
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    if loop.is_running():
        # Agar loop allaqachon ishlayotgan bo'lsa
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result()
    else:
        return loop.run_until_complete(coro)


@csrf_exempt
@require_POST
def api_webhook(request):
    """
    Tashqi API'dan kelgan webhook'ni qabul qilish

    Expected JSON format:
    {
        "event": "order.created",  # yoki "order.updated"
        "order": {
            "id": "order_123",
            "seller_id": "seller_1",
            "status": "new",
            "customer": {
                "name": "Ali Valiyev",
                "phone": "+998901234567",
                "address": "Toshkent, Chilonzor"
            },
            "total": 150000,
            "items": [
                {"name": "iPhone 15", "price": 150000, "quantity": 1}
            ],
            "notes": "Tez yetkazib bering",
            "created_at": "2024-01-17T10:30:00Z"
        }
    }
    """
    try:
        # 1. JSON ni parse qilish
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            logger.error("Invalid JSON received")
            return JsonResponse(
                {'error': 'Invalid JSON format'},
                status=400
            )

        # 2. Ma'lumotlarni tekshirish
        event_type = data.get('event')
        order_data = data.get('order')

        if not order_data:
            return JsonResponse(
                {'error': 'Missing order data'},
                status=400
            )

        if not order_data.get('id'):
            return JsonResponse(
                {'error': 'Order ID is required'},
                status=400
            )

        logger.info(f"Received webhook: event={event_type}, order_id={order_data.get('id')}")

        # 3. Event turiga qarab ishlash
        if event_type == 'order.created':
            return handle_order_created(order_data)

        elif event_type == 'order.updated':
            return handle_order_updated(order_data)

        elif event_type == 'order.cancelled':
            return handle_order_cancelled(order_data)

        else:
            # Noma'lum event - baribir notification yuboramiz
            logger.warning(f"Unknown event type: {event_type}, treating as new order")
            return handle_order_created(order_data)

    except Exception as e:
        logger.exception(f"Unexpected error in webhook: {e}")
        return JsonResponse(
            {'error': 'Internal server error'},
            status=500
        )


def handle_order_created(order_data: dict) -> JsonResponse:
    """
    Yangi buyurtma - Telegram notification yuborish
    """
    try:
        bot = NotificationBot()
        success = run_async(bot.send_order_notification(order_data))

        if success:
            logger.info(f"Notification sent for order {order_data.get('id')}")
            return JsonResponse({
                'status': 'success',
                'message': 'Notification sent',
                'order_id': order_data.get('id')
            })
        else:
            logger.error(f"Failed to send notification for order {order_data.get('id')}")
            return JsonResponse({
                'status': 'failed',
                'message': 'Failed to send notification',
                'order_id': order_data.get('id')
            }, status=500)

    except Exception as e:
        logger.exception(f"Error handling order.created: {e}")
        return JsonResponse(
            {'error': str(e)},
            status=500
        )


def handle_order_updated(order_data: dict) -> JsonResponse:
    """
    Buyurtma yangilandi - status o'zgarishi haqida xabar yuborish
    """
    try:
        from bot.models import Order

        order_id = order_data.get('id')
        new_status = order_data.get('status')

        # Mavjud buyurtmani topish
        try:
            order = Order.objects.get(external_id=order_id)
            old_status = order.status

            # Agar status o'zgargan bo'lsa, xabar yuborish
            if old_status != new_status:
                bot = NotificationBot()
                success = run_async(
                    bot.send_status_update(order_id, new_status)
                )

                if success:
                    return JsonResponse({
                        'status': 'success',
                        'message': 'Status update sent',
                        'order_id': order_id,
                        'old_status': old_status,
                        'new_status': new_status
                    })
            else:
                return JsonResponse({
                    'status': 'success',
                    'message': 'No status change',
                    'order_id': order_id
                })

        except Order.DoesNotExist:
            # Buyurtma topilmasa, yangi qilib yaratish
            logger.warning(f"Order {order_id} not found, creating new")
            return handle_order_created(order_data)

    except Exception as e:
        logger.exception(f"Error handling order.updated: {e}")
        return JsonResponse(
            {'error': str(e)},
            status=500
        )

    return JsonResponse({'status': 'updated'})


def handle_order_cancelled(order_data: dict) -> JsonResponse:
    """
    Buyurtma bekor qilindi
    """
    try:
        order_id = order_data.get('id')

        bot = NotificationBot()
        success = run_async(
            bot.send_status_update(
                order_id,
                'cancelled',
                additional_text="Buyurtma bekor qilindi"
            )
        )

        return JsonResponse({
            'status': 'success' if success else 'failed',
            'message': 'Cancellation notification sent',
            'order_id': order_id
        })

    except Exception as e:
        logger.exception(f"Error handling order.cancelled: {e}")
        return JsonResponse(
            {'error': str(e)},
            status=500
        )


@require_GET
def health_check(request):
    """
    Health check endpoint - serverning ishlayotganini tekshirish
    """
    return JsonResponse({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'service': 'seller-bot'
    })


@csrf_exempt
@require_POST
def test_order(request):
    """
    Test buyurtma yuborish (development uchun)
    Debug=True bo'lgandagina ishlaydi
    """
    if not settings.DEBUG:
        return JsonResponse(
            {'error': 'Only available in DEBUG mode'},
            status=403
        )

    try:
        # Custom test data yoki default
        try:
            custom_data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            custom_data = {}

        # Default test order
        test_order_data = {
            "id": custom_data.get('id', f"test_{datetime.now().strftime('%Y%m%d%H%M%S')}"),
            "seller_id": custom_data.get('seller_id', ''),
            "status": "new",
            "customer": {
                "name": custom_data.get('customer_name', 'Test Mijoz'),
                "phone": custom_data.get('customer_phone', '+998901234567'),
                "address": custom_data.get('customer_address', 'Toshkent, Test manzil')
            },
            "total": custom_data.get('total', 150000),
            "items": custom_data.get('items', [
                {"name": "Test Mahsulot 1", "price": 100000, "quantity": 1},
                {"name": "Test Mahsulot 2", "price": 50000, "quantity": 1}
            ]),
            "notes": custom_data.get('notes', 'Bu test buyurtma'),
            "created_at": datetime.now().isoformat()
        }

        bot = NotificationBot()
        success = run_async(bot.send_order_notification(test_order_data))

        if success:
            return JsonResponse({
                'status': 'success',
                'message': 'Test order notification sent',
                'order': test_order_data
            })
        else:
            return JsonResponse({
                'status': 'failed',
                'message': 'Failed to send test notification'
            }, status=500)

    except Exception as e:
        logger.exception(f"Error sending test order: {e}")
        return JsonResponse(
            {'error': str(e)},
            status=500
        )
