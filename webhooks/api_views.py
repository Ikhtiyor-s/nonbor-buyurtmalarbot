"""
IP telefon (Asterisk autodialer) uchun REST API.
Barcha endpointlar X-Telegram-Bot-Secret header bilan himoyalangan.
"""
import os
import json
import logging
from datetime import datetime, timedelta

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

logger = logging.getLogger('webhooks')


def _check_auth(request) -> bool:
    expected = os.getenv('EXTERNAL_API_SECRET', 'nonbor-secret-key')
    return request.headers.get('X-Telegram-Bot-Secret', '') == expected


@require_GET
def pending_calls(request):
    """
    Asterisk autodialer uchun: kimga qo'ng'iroq qilish kerak?

    GET /api/pending-calls/
    Header: X-Telegram-Bot-Secret: nonbor-secret-key

    Javob:
    {
      "pending": [
        {
          "seller_id": "...",
          "seller_name": "Restoran nomi",
          "phone": "+998...",
          "waiting_minutes": 5,
          "order_count": 2,
          "order_ids": ["36718", "36720"]
        }
      ],
      "total": 1,
      "checked_at": "2026-05-09T22:00:00"
    }

    WAIT_BEFORE_CALL (default 90s) dan ko'proq kutgan buyurtmalar qaytariladi.
    """
    if not _check_auth(request):
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    try:
        from bot.models import Order, Seller
        from bot.core import WAIT_BEFORE_CALL, MAX_CALL_ATTEMPTS, _load_alert_tracker, _load_call_log

        now = datetime.now()
        call_threshold = timedelta(seconds=WAIT_BEFORE_CALL)
        all_orders = Order.load_all()
        tracker = _load_alert_tracker()
        call_log = _load_call_log()

        # Seller bo'yicha kutilayotgan buyurtmalar
        seller_orders: dict = {}
        for od in all_orders:
            if od.get('status') != 'new':
                continue
            notified_at = od.get('notified_at')
            if not notified_at:
                continue
            try:
                t = datetime.fromisoformat(notified_at[:19])
                if now - t < call_threshold:
                    continue
                sid = od.get('seller_id', '')
                if sid not in seller_orders:
                    seller_orders[sid] = []
                seller_orders[sid].append(od)
            except ValueError:
                continue

        pending = []
        for seller_id, orders in seller_orders.items():
            seller = Seller.get(id=seller_id)
            if not seller or not seller.phone:
                continue

            # Bu seller uchun bugungi qo'ng'iroqlar soni
            today = now.strftime('%Y-%m-%d')
            seller_calls_today = [
                c for c in call_log
                if c.get('seller_id') == seller_id
                and c.get('called_at', '')[:10] == today
            ]
            calls_made = len(seller_calls_today)

            # MAX urinishga yetganmi
            if calls_made >= MAX_CALL_ATTEMPTS:
                continue

            # Qancha vaqt kutgan
            earliest = min(
                datetime.fromisoformat(o.get('notified_at', now.isoformat())[:19])
                for o in orders
            )
            waiting_minutes = int((now - earliest).total_seconds() / 60)

            pending.append({
                'seller_id': seller_id,
                'seller_name': seller.full_name,
                'phone': seller.phone,
                'waiting_minutes': waiting_minutes,
                'order_count': len(orders),
                'order_ids': [o.get('external_id', '') for o in orders],
                'calls_already_made': calls_made,
                'max_attempts': MAX_CALL_ATTEMPTS,
            })

        return JsonResponse({
            'pending': pending,
            'total': len(pending),
            'checked_at': now.isoformat(),
        })

    except Exception as e:
        logger.exception(f"pending_calls API xato: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@require_GET
def call_stats(request):
    """
    Bugungi qo'ng'iroq statistikasi.

    GET /api/call-stats/
    GET /api/call-stats/?date=2026-05-09

    Javob:
    {
      "date": "2026-05-09",
      "total_calls": 13,
      "answered": 10,
      "unanswered": 3,
      "by_seller": [
        {"seller_name": "...", "phone": "...", "calls": 3, "answered": 2}
      ]
    }
    """
    if not _check_auth(request):
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    try:
        from bot.core import _load_call_log

        date_str = request.GET.get('date', datetime.now().strftime('%Y-%m-%d'))
        call_log = _load_call_log()

        day_calls = [c for c in call_log if c.get('called_at', '')[:10] == date_str]

        total = len(day_calls)
        answered = sum(1 for c in day_calls if c.get('success'))
        unanswered = total - answered

        # Seller bo'yicha
        by_seller: dict = {}
        for c in day_calls:
            key = c.get('phone', '—')
            if key not in by_seller:
                by_seller[key] = {
                    'seller_name': c.get('seller_name', '—'),
                    'phone': key,
                    'calls': 0,
                    'answered': 0,
                }
            by_seller[key]['calls'] += 1
            if c.get('success'):
                by_seller[key]['answered'] += 1

        return JsonResponse({
            'date': date_str,
            'total_calls': total,
            'answered': answered,
            'unanswered': unanswered,
            'by_seller': list(by_seller.values()),
        })

    except Exception as e:
        logger.exception(f"call_stats API xato: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@require_GET
def order_status(request):
    """
    Umumiy buyurtma holati (real-time).

    GET /api/order-status/

    Javob:
    {
      "new": 3,       -- qabul qilinmagan
      "accepted": 12,
      "expired": 5,
      "total_today": 20,
      "orders": [...]  -- faqat 'new' statusdagilar
    }
    """
    if not _check_auth(request):
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    try:
        from bot.models import Order

        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        all_orders = Order.load_all()

        today_orders = []
        for o in all_orders:
            created = o.get('created_at', o.get('notified_at', ''))
            if created:
                try:
                    t = datetime.fromisoformat(created[:19])
                    if t >= today_start:
                        today_orders.append(o)
                except ValueError:
                    pass

        new_orders = [o for o in today_orders if o.get('status') == 'new']

        return JsonResponse({
            'new': len(new_orders),
            'accepted': sum(1 for o in today_orders if o.get('status') == 'accepted'),
            'expired': sum(1 for o in today_orders if o.get('status') == 'expired'),
            'rejected': sum(1 for o in today_orders if o.get('status') in ('rejected', 'cancelled')),
            'total_today': len(today_orders),
            'checked_at': now.isoformat(),
            'pending_orders': [
                {
                    'order_id': o.get('external_id'),
                    'seller_id': o.get('seller_id'),
                    'customer_name': o.get('customer_name'),
                    'total_amount': int(o.get('total_amount', 0)) // 100,
                    'notified_at': o.get('notified_at', ''),
                    'waiting_minutes': int(
                        (now - datetime.fromisoformat(o.get('notified_at', now.isoformat())[:19])).total_seconds() / 60
                    ),
                }
                for o in new_orders
            ],
        })

    except Exception as e:
        logger.exception(f"order_status API xato: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@require_GET
def admin_alert(request):
    """
    Server (Nonbor API) ishlamayotganda Asterisk adminga qo'ng'iroq qilishi kerakmi?

    GET /api/admin-alert/
    Header: X-Telegram-Bot-Secret: nonbor-secret-key

    Javob (normal holat):
    {
      "call_admin": false,
      "reason": null,
      "admin_phone": "+998..."
    }

    Javob (API ishlamayotganda):
    {
      "call_admin": true,
      "reason": "Nonbor API 15 daqiqadan beri ishlamayapti",
      "admin_phone": "+998948679300",
      "down_since": "2026-05-09T22:00:00",
      "already_acked": false
    }

    Asterisk bu endpointni har daqiqada so'raydi.
    call_admin=true bo'lsa adminni chaqiradi, keyin /api/admin-alert/ack/ ga POST yuboradi.
    """
    if not _check_auth(request):
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    try:
        from bot.core import _api_health
        from bot.models import AdminSettings

        cfg = AdminSettings.get_health_config()
        admin_phone = cfg.get('phone', '')

        is_down = _api_health.get('is_down', False)
        down_since = _api_health.get('down_since')
        acked = _api_health.get('admin_call_acked', False)

        if not is_down:
            return JsonResponse({
                'call_admin': False,
                'reason': None,
                'admin_phone': admin_phone,
            })

        reason = 'Nonbor API ishlamayapti'
        if down_since:
            try:
                mins = int((datetime.now() - datetime.fromisoformat(down_since)).total_seconds() / 60)
                reason = f"Nonbor API {mins} daqiqadan beri ishlamayapti"
            except Exception:
                pass

        return JsonResponse({
            'call_admin': True,
            'reason': reason,
            'admin_phone': admin_phone,
            'down_since': down_since,
            'already_acked': acked,
        })

    except Exception as e:
        logger.exception(f"admin_alert API xato: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_POST
def admin_alert_ack(request):
    """
    Asterisk adminga qo'ng'iroq qilganini bildiradi (acknowledgment).

    POST /api/admin-alert/ack/
    Header: X-Telegram-Bot-Secret: nonbor-secret-key
    Body: {"answered": true, "duration": 30}

    Bu qayta call_admin=false qilib qo'yadi (30 daqiqaga).
    """
    if not _check_auth(request):
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    try:
        data = {}
        try:
            data = json.loads(request.body)
        except Exception:
            pass

        answered = bool(data.get('answered', True))
        duration = int(data.get('duration', 0))

        from bot.core import _api_health, log_ami_call
        from bot.models import AdminSettings

        cfg = AdminSettings.get_health_config()
        admin_phone = cfg.get('phone', '')

        # Qo'ng'iroqni logga yozish
        if admin_phone:
            log_ami_call(
                seller_id='admin',
                seller_name='ADMIN',
                phone=admin_phone,
                success=answered,
            )

        # 30 daqiqaga yana chaqirmaslik uchun flag
        _api_health['admin_call_acked'] = True
        _api_health['admin_call_acked_at'] = datetime.now().isoformat()

        logger.info(f"Admin alert ACK: answered={answered}, duration={duration}s")

        return JsonResponse({
            'status': 'ok',
            'answered': answered,
            'next_check_in_minutes': 30,
        })

    except Exception as e:
        logger.exception(f"admin_alert_ack API xato: {e}")
        return JsonResponse({'error': str(e)}, status=500)
