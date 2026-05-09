import os
import json
import logging
import aiohttp
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError
from datetime import datetime, timedelta

ALERT_TRACKER_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'alert_tracker.json')
SUMMARY_MSG_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'summary_msg.json')
CALL_LOG_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'call_log.json')
ORDER_HISTORY_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'order_history.json')
SENT_ORDERS_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'sent_orders.json')
MISSED_ORDER_MINUTES = int(os.getenv('MISSED_ORDER_MINUTES', 3))
WAIT_BEFORE_CALL = int(os.getenv('WAIT_BEFORE_CALL', 90))
MAX_CALL_ATTEMPTS = int(os.getenv('MAX_CALL_ATTEMPTS', 2))
RETRY_INTERVAL = int(os.getenv('RETRY_INTERVAL', 30))


def _load_alert_tracker():
    if os.path.exists(ALERT_TRACKER_FILE):
        with open(ALERT_TRACKER_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def _save_alert_tracker(data):
    os.makedirs(os.path.dirname(ALERT_TRACKER_FILE), exist_ok=True)
    with open(ALERT_TRACKER_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _load_summary_msg():
    if os.path.exists(SUMMARY_MSG_FILE):
        with open(SUMMARY_MSG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def _save_summary_msg(data):
    os.makedirs(os.path.dirname(SUMMARY_MSG_FILE), exist_ok=True)
    with open(SUMMARY_MSG_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _load_call_log():
    if os.path.exists(CALL_LOG_FILE):
        with open(CALL_LOG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []


def _save_call_log(data):
    os.makedirs(os.path.dirname(CALL_LOG_FILE), exist_ok=True)
    with open(CALL_LOG_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _archive_order(order_id, seller_id, seller_name, status, total, items, notified_at):
    """Buyurtmani tarixga yozish (statistika uchun, o'chmas)"""
    try:
        if os.path.exists(ORDER_HISTORY_FILE):
            with open(ORDER_HISTORY_FILE, 'r', encoding='utf-8') as f:
                history = json.load(f)
        else:
            history = []

        # Allaqachon bor bo'lsa update qilish
        for entry in history:
            if str(entry.get('order_id')) == str(order_id):
                entry['status'] = status
                break
        else:
            history.append({
                'order_id': str(order_id),
                'seller_id': str(seller_id),
                'seller_name': seller_name,
                'status': status,
                'total': total,
                'items': items or [],
                'notified_at': notified_at,
            })

        # 30 kundan eski yozuvlarni tozalash
        cutoff = (datetime.now() - timedelta(days=30)).isoformat()
        history = [e for e in history if e.get('notified_at', '') >= cutoff]

        os.makedirs(os.path.dirname(ORDER_HISTORY_FILE), exist_ok=True)
        with open(ORDER_HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"_archive_order xato: {e}")


def _archive_order_from_api(order: dict):
    """Nonbor API buyurtmasini tarixga yozish (barcha statuslar uchun)"""
    order_id = order.get('id')
    if not order_id:
        return
    business = order.get('business', {}) or {}
    seller_name = business.get('title', '') or business.get('name', '')
    seller_phone = business.get('phone', '')
    seller_id = f"biz_{seller_phone}" if seller_phone else f"biz_{str(order_id)}"

    # Seller modelidan ID ni topishga urinish
    try:
        from .models import Seller
        sellers = Seller.filter(is_active=True)
        for s in sellers:
            if s.business_phone and s.business_phone == seller_phone:
                seller_id = s.id
                if not seller_name:
                    seller_name = s.full_name
                break
            if s.full_name == seller_name:
                seller_id = s.id
                break
    except Exception:
        pass

    state = (order.get('state') or '').upper()
    STATUS_MAP = {
        # Yangi / aktiv
        'CHECKING': 'new', 'PENDING': 'new', 'NEW': 'new', 'CREATED': 'new',
        'CART': 'new',
        # Qabul qilingan / tayyorlanmoqda
        'ACCEPTED': 'accepted', 'PREPARING': 'accepted', 'READY': 'accepted',
        # Yetkazilmoqda
        'ON_DELIVERY': 'delivering', 'DELIVERING': 'delivering',
        # Yetkazildi / yakunlandi
        'COMPLETED': 'completed', 'FINISHED': 'done', 'DONE': 'done',
        # Bekor / rad
        'CANCELLED': 'rejected', 'REJECTED': 'rejected',
        'CANCELLED_BY_CLIENT': 'rejected', 'REJECTED_BY_SELLER': 'rejected',
        'EXPIRED': 'expired', 'PAYMENT_EXPIRED': 'expired',
    }
    status = STATUS_MAP.get(state, 'new')

    order_items = order.get('order_item', []) or []
    items = []
    for item in order_items:
        product = item.get('product', {}) or {}
        items.append({
            'name': product.get('name', ''),
            'price': product.get('price', 0),
            'quantity': item.get('quantity', 1),
        })

    created_at = order.get('created_at') or datetime.now().isoformat()
    _archive_order(order_id, seller_id, seller_name, status,
                   order.get('total_price', 0), items, created_at)


def _load_order_history():
    if os.path.exists(ORDER_HISTORY_FILE):
        with open(ORDER_HISTORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []


def log_ami_call(seller_id: str, seller_name: str, phone: str, success: bool):
    """AMI qo'ng'iroqni logga yozish (daily stats uchun)"""
    log = _load_call_log()
    log.append({
        'seller_id': seller_id,
        'seller_name': seller_name,
        'phone': phone,
        'called_at': datetime.now().isoformat(),
        'success': success,
    })
    # 7 kundan eski yozuvlarni tozalash
    cutoff = (datetime.now() - timedelta(days=7)).isoformat()
    log = [e for e in log if e.get('called_at', '') >= cutoff]
    _save_call_log(log)


# Oxirgi yuborilgan summary matni — o'zgarish bo'lmasa edit qilmaymiz
_last_summary_text = ''

# Bugun statistika yuborilganmi (ikki marta yuborilmasin)
_stats_sent_today: str = ''

# API health monitoring holati
_api_health = {
    'is_down': False,
    'down_since': None,
    'last_ok': None,
    'alert_messages': [],   # yuborilgan down xabarlar (o'chirish uchun)
}


async def update_admin_group_summary():
    """Admin guruhidagi yagona xabarni yangilash — faqat o'zgarish bo'lsa"""
    global _last_summary_text
    from .models import Order, AdminSettings

    admin_group_id = AdminSettings.get_admin_group_chat_id()
    if not admin_group_id:
        return

    all_orders = Order.load_all()
    now = datetime.now()
    threshold = timedelta(minutes=MISSED_ORDER_MINUTES)

    new_orders = [o for o in all_orders if o.get('status') == 'new']
    overdue = []
    waiting = []
    for o in new_orders:
        try:
            t = datetime.fromisoformat(o.get('notified_at', ''))
            if now - t >= threshold:
                overdue.append(o)
            else:
                waiting.append(o)
        except Exception:
            waiting.append(o)

    total_new = len(new_orders)
    # Vaqtsiz content — o'zgarish bormi shu bilan tekshiramiz
    content_key = f"{total_new}:{len(waiting)}:{len(overdue)}"

    if total_new == 0:
        text = "✅ <b>Kutilayotgan buyurtma yo'q</b>"
    else:
        text = (
            f"📋 <b>Kutilayotgan buyurtmalar: {total_new} ta</b>\n\n"
            f"⏳ Yangi: {len(waiting)} ta\n"
            f"🚨 {MISSED_ORDER_MINUTES} daqiqadan o'tgan: {len(overdue)} ta"
        )

    # O'zgarish bo'lmasa Telegram API ga murojaat qilmaymiz
    if content_key == _last_summary_text:
        return
    _last_summary_text = content_key

    tg_bot = NotificationBot().bot
    summary = _load_summary_msg()
    msg_id = summary.get('message_id')
    chat_id = int(admin_group_id)

    try:
        if msg_id:
            await tg_bot.edit_message_text(
                chat_id=chat_id,
                message_id=int(msg_id),
                text=text,
                parse_mode='HTML'
            )
        else:
            msg = await tg_bot.send_message(chat_id=chat_id, text=text, parse_mode='HTML')
            _save_summary_msg({'message_id': msg.message_id, 'chat_id': chat_id})
    except TelegramError as e:
        if 'message to edit not found' in str(e).lower() or 'message_id_invalid' in str(e).lower():
            try:
                msg = await tg_bot.send_message(chat_id=chat_id, text=text, parse_mode='HTML')
                _save_summary_msg({'message_id': msg.message_id, 'chat_id': chat_id})
                _last_summary_text = ''
            except Exception:
                pass
        elif 'message is not modified' in str(e).lower():
            pass
        else:
            logger.warning(f"update_admin_group_summary error: {e}")
    except Exception as e:
        logger.warning(f"update_admin_group_summary error: {e}")


logger = logging.getLogger(__name__)

# Buyurtma muddati (daqiqada) - shu vaqtdan keyin o'chiriladi
ORDER_EXPIRY_MINUTES = int(os.getenv('ORDER_EXPIRY_MINUTES', 30))

def _load_sent_orders() -> set:
    """Restart dan keyin ham sent_orders saqlanib qolsin"""
    if os.path.exists(SENT_ORDERS_FILE):
        try:
            with open(SENT_ORDERS_FILE, 'r') as f:
                return set(json.load(f))
        except Exception:
            pass
    return set()


def _save_sent_orders():
    try:
        os.makedirs(os.path.dirname(SENT_ORDERS_FILE), exist_ok=True)
        with open(SENT_ORDERS_FILE, 'w') as f:
            json.dump(list(sent_orders), f)
    except Exception as e:
        logger.warning(f"sent_orders saqlashda xato: {e}")


# Yuborilgan buyurtmalar — fayldan yuklanadi (restart da yo'qolmaydi)
sent_orders: set = _load_sent_orders()
# AmoCRM dan yuborilgan leadlar
sent_amocrm_leads = set()

# Global bot instance
bot_instance = None

def get_bot():
    global bot_instance
    if bot_instance is None:
        token = os.getenv('TELEGRAM_BOT_TOKEN')
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN muhit o'zgaruvchisi talab qilinadi!")
        bot_instance = Bot(token=token)
    return bot_instance


class NotificationBot:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._bot = None
        return cls._instance
    
    @property
    def bot(self):
        if not self._bot:
            self._bot = get_bot()
        return self._bot
    
    async def send_order_notification(self, order_data):
        """Asosiy notification yuborish funksiyasi"""
        try:
            from .models import Seller, Order
            
            # 1. Sotuvchini topish
            seller = await self._find_seller(order_data)
            if not seller or not seller.group_chat_id:
                logger.error(f"No active seller found for order {order_data.get('id')}")
                return False
            
            # 2. Xabar tayyorlash
            message_text = self._format_order_message(order_data)
            keyboard = self._create_order_keyboard(order_data, seller)
            
            # 3. Guruhga xabar yuborish
            message = await self.bot.send_message(
                chat_id=seller.group_chat_id,
                text=message_text,
                reply_markup=keyboard,
                parse_mode='HTML'
            )
            
            # 4. Database'ga saqlash
            await self._save_order(order_data, seller, message.message_id)

            # 5. Admin guruhga ham yuborish
            try:
                from .models import AdminSettings
                admin_group_id = AdminSettings.get_admin_group_chat_id()
                if admin_group_id and str(admin_group_id) != str(seller.group_chat_id):
                    admin_text = self._format_order_message(order_data, show_customer=True)
                    admin_text = f"📢 <b>[{seller.full_name}]</b>\n\n" + admin_text
                    await self.bot.send_message(
                        chat_id=int(admin_group_id),
                        text=admin_text,
                        parse_mode='HTML'
                    )
            except Exception as ae:
                logger.warning(f"Admin group notification failed: {ae}")

            logger.info(f"Order {order_data.get('id')} sent to group {seller.group_chat_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error sending notification: {e}")
            return False
    
    async def _find_seller(self, order_data):
        """Sotuvchini topish"""
        from .models import Seller

        sellers = Seller.filter(is_active=True)

        # 1. business_phone bo'yicha (asosiy usul)
        biz_phone = order_data.get('business_phone', '')
        if biz_phone:
            for s in sellers:
                if s.business_phone and s.business_phone == biz_phone:
                    return s

        # 2. seller_id orqali
        seller_id = order_data.get('seller_id')
        if seller_id:
            for s in sellers:
                if s.id == seller_id:
                    return s

        # 3. seller_phone orqali
        phone = order_data.get('seller_phone')
        if phone:
            for s in sellers:
                if s.phone == phone:
                    return s

        return None
    
    def _format_order_message(self, order_data, show_customer=True):
        """Xabar matnini formatlash — mijoz ma'lumotlari har doim ko'rsatiladi"""
        items = order_data.get('items', [])

        items_text = ""
        total_items = 0
        items_sum = 0
        for item in items:
            quantity = item.get('quantity', 1)
            total_items += quantity
            price_k = int(item.get('price', 0)) // 100
            item_total_k = price_k * quantity
            items_sum += item_total_k

            items_text += f"  • {item.get('name', 'Nomalum')}\n"
            if quantity > 1:
                items_text += f"    {quantity} x {price_k:,} = {item_total_k:,} so'm\n".replace(",", " ")
            else:
                items_text += f"    {price_k:,} so'm\n".replace(",", " ")

        order_total_k = int(order_data.get('total', 0)) // 100
        delivery_fee_k = order_total_k - items_sum
        delivery_line = f"🚴 <b>Yetkazib berish:</b> {delivery_fee_k:,} so'm\n".replace(",", " ") if delivery_fee_k > 0 else ""

        customer = order_data.get('customer', {})
        delivery_address = order_data.get('delivery_address', '')
        phone_display = customer.get('phone', '') or ''
        if not phone_display or phone_display == 'Nomalum':
            phone_display = "Ko'rsatilmagan"
        name_display = customer.get('name', '') or 'Nomalum'

        # Qo'shimcha maydonlar
        DELIVERY_LABELS = {
            'DELIVERY': '🚴 Yetkazib berish',
            'PICKUP': '🏪 Olib ketish',
        }
        PAYMENT_LABELS = {
            'CASH': '💵 Naqd',
            'CARD': '💳 Karta',
            'PAYME': '💳 Payme',
            'CLICK': '💳 Click',
            'UZUM': '💳 Uzum Bank',
            'HUMO': '💳 Humo',
            'UZCARD': '💳 Uzcard',
        }
        dm = (order_data.get('delivery_method') or '').upper()
        pm = (order_data.get('payment_method') or '').upper()
        delivery_label = DELIVERY_LABELS.get(dm, '')
        payment_label = PAYMENT_LABELS.get(pm, '')
        planned = order_data.get('planned_datetime') or ''
        source = order_data.get('source') or ''

        extra_lines = ''
        if delivery_label:
            extra_lines += f"🚚 <b>Yetkazish:</b> {delivery_label}\n"
        if payment_label:
            extra_lines += f"💰 <b>To'lov:</b> {payment_label}\n"
        if planned:
            try:
                from datetime import datetime as _dt
                pt = _dt.fromisoformat(planned[:19])
                extra_lines += f"📅 <b>Reja:</b> {pt.strftime('%d.%m.%Y %H:%M')}\n"
            except Exception:
                extra_lines += f"📅 <b>Reja:</b> {planned}\n"
        if source:
            extra_lines += f"📱 <b>Platforma:</b> {source}\n"

        message = f"""
🛍️ <b>YANGI BUYURTMA</b>

📦 <b>Buyurtma:</b> #{order_data.get('id', 'N/A')}

📋 <b>Mahsulotlar ({total_items} ta):</b>
{items_text}
📦 <b>Mahsulotlar summasi:</b> {items_sum:,} so'm
{delivery_line}💰 <b>Jami:</b> {order_total_k:,} so'm

━━━━━━━━━━━━━━━━━━━━
👤 <b>Mijoz:</b> {name_display}
📞 <b>Telefon:</b> <code>{phone_display}</code>
📍 <b>Manzil:</b> {delivery_address if delivery_address else "Ko'rsatilmagan"}
{extra_lines}""".replace(",", " ")

        message += "\n⚠️ <i>Faqat menejer qabul/rad qila oladi</i>"

        return message.strip()
    
    def _create_order_keyboard(self, order_data, seller):
        """Buyurtma uchun tugmalar"""
        order_id = order_data.get('id')

        keyboard = [
            [
                InlineKeyboardButton("✅ Qabul qilish",
                                   callback_data=f"accept_{order_id}"),
                InlineKeyboardButton("❌ Rad etish",
                                   callback_data=f"reject_{order_id}")
            ]
        ]

        return InlineKeyboardMarkup(keyboard)
    
    async def _save_order(self, order_data, seller, message_id):
        """Buyurtmani saqlash"""
        from .models import Order

        try:
            customer = order_data.get('customer', {})
            order = Order(
                external_id=str(order_data.get('id')),
                seller_id=seller.id,
                status=order_data.get('status', 'new'),
                customer_name=customer.get('name', ''),
                customer_phone=customer.get('phone', ''),
                total_amount=order_data.get('total', 0),
                items=order_data.get('items', []),
                telegram_message_id=str(message_id),
                notified_at=datetime.now().isoformat(),
                amocrm_lead_id=order_data.get('amocrm_lead_id'),
                delivery_address=order_data.get('delivery_address', ''),
                delivery_type=order_data.get('delivery_type', 'delivery')
            )
            order.save()
        except Exception as e:
            logger.error(f"Error saving order: {e}")


async def sync_businesses_from_api():
    """Nonbor API dan bizneslarni sellers.json ga avtomatik sync qilish"""
    from .models import Seller
    api_url = os.getenv('BUSINESSES_API_URL', 'https://prod.nonbor.uz/api/v2/telegram_bot/businesses/accepted/')
    api_secret = os.getenv('EXTERNAL_API_SECRET', 'nonbor-secret-key')
    try:
        headers = {'X-Telegram-Bot-Secret': api_secret}
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, headers=headers, timeout=timeout) as response:
                if response.status != 200:
                    logger.error(f"sync_businesses: API returned {response.status}")
                    return
                data = await response.json()

        items = data.get('result', data.get('results', [])) if isinstance(data, dict) else (data if isinstance(data, list) else [])

        added = 0
        updated = 0
        for b in items:
            phone = b.get('phone_number', '') or b.get('phone', '')
            if phone and not phone.startswith('+'):
                phone = '+' + phone
            if not phone:
                continue

            region = b.get('region_name_uz', '')
            district = b.get('district_name_uz', '')
            address = f"{region}, {district}".strip(', ') if region or district else ''
            title = b.get('title', '')
            api_id = str(b.get('id', ''))
            status = b.get('state', '')

            existing = Seller.get(phone=phone, is_active=True) or Seller.get(api_identifier=api_id, is_active=True)
            if existing:
                existing.full_name = title
                existing.address = address
                existing.region = region
                existing.district = district
                existing.api_identifier = api_id
                existing.business_phone = phone
                existing.business_status = status
                existing.save()
                updated += 1
            else:
                seller = Seller(
                    phone=phone,
                    full_name=title,
                    address=address,
                    region=region,
                    district=district,
                    api_identifier=api_id,
                    business_phone=phone,
                    business_status=status,
                    is_active=True,
                )
                seller.save()
                added += 1

        if added or updated:
            logger.info(f"sync_businesses: +{added} yangi, {updated} yangilandi")

    except Exception as e:
        logger.error(f"sync_businesses_from_api error: {e}")


async def _process_single_order(order: dict) -> bool:
    """
    Bitta Nonbor buyurtmasini qayta ishlash: sotuvchiga xabar yuborish yoki orders.json ga saqlash.
    Polling va webhook ikkalasidan chaqiriladi.
    """
    global sent_orders
    from .models import Seller, Order

    order_id = order.get('id')
    if not order_id:
        return False

    if order_id in sent_orders:
        return False

    amocrm_id = order.get('amocrm_id') or order.get('amo_id') or order.get('crm_id')
    if amocrm_id:
        sent_orders.add(order_id)
        return False

    state = (order.get('state') or '').upper()
    # Faqat CHECKING (rasmiylashtirilmoqda) holatidagi buyurtmalar
    # PENDING = Savatda — bu buyurtmalar guruhga yuborilmaydi
    if state != 'CHECKING':
        sent_orders.add(order_id)
        return False

    existing = Order.get(external_id=str(order_id))
    if existing:
        sent_orders.add(order_id)
        return False

    import json as _json
    logger.info(f"New order #{order_id} raw: {_json.dumps(order, ensure_ascii=False)[:600]}")

    business = order.get('business', {}) or {}
    business_name = business.get('title', '')
    business_phone = business.get('phone', '') or business.get('phone_number', '')
    business_id = str(business.get('id', ''))

    sellers = Seller.filter(is_active=True)
    target_seller = None
    # 1. api_identifier bo'yicha (eng ishonchli)
    for s in sellers:
        if business_id and getattr(s, 'api_identifier', '') == business_id:
            target_seller = s
            break
    # 2. business_phone bo'yicha
    if not target_seller:
        for s in sellers:
            if s.business_phone and s.business_phone == business_phone:
                target_seller = s
                break
    # 3. full_name bo'yicha
    if not target_seller:
        for s in sellers:
            if s.full_name == business_name:
                target_seller = s
                break

    delivery = order.get('delivery', {}) or {}
    client = order.get('client', {}) or {}
    user = order.get('user', {}) or {}
    order_items = order.get('order_item', [])

    items = []
    for item in order_items:
        product = item.get('product', {})
        items.append({
            'name': product.get('name', 'Nomalum'),
            'price': product.get('price', 0),
            'quantity': item.get('quantity', 1),
        })

    customer_phone = (
        delivery.get('phone') or delivery.get('phone_number') or
        delivery.get('customer_phone') or
        client.get('phone') or client.get('phone_number') or
        user.get('phone') or user.get('phone_number') or
        order.get('phone') or order.get('phone_number') or
        order.get('customer_phone') or ''
    )
    if customer_phone and not str(customer_phone).startswith('+'):
        customer_phone = '+' + str(customer_phone)

    customer_name = (
        delivery.get('name') or delivery.get('full_name') or
        delivery.get('customer_name') or
        client.get('name') or client.get('full_name') or
        f"{client.get('first_name', '')} {client.get('last_name', '')}".strip() or
        user.get('name') or user.get('full_name') or
        f"{user.get('first_name', '')} {user.get('last_name', '')}".strip() or
        order.get('customer_name') or f"Mijoz #{order_id}"
    )
    customer_name = customer_name.strip() or f"Mijoz #{order_id}"

    delivery_address = (
        delivery.get('address') or delivery.get('address_line') or
        delivery.get('full_address') or order.get('address') or ''
    )
    delivery_method = (order.get('delivery_method') or '').upper()
    delivery_type = 'pickup' if delivery_method == 'PICKUP' else 'delivery'
    payment_method = (order.get('payment_method') or '').upper()
    planned_datetime = order.get('planned_datetime') or order.get('plan') or ''
    source = order.get('source') or order.get('platform') or order.get('channel') or ''

    order_data = {
        'id': order_id,
        'seller_id': target_seller.id if target_seller else '',
        'business_phone': business_phone,
        'business_name': business_name,
        'status': 'new',
        'customer': {'name': customer_name, 'phone': customer_phone},
        'total': order.get('total_price', 0),
        'items': items,
        'delivery_address': delivery_address,
        'delivery_type': delivery_type,
        'delivery_method': delivery_method,
        'payment_method': payment_method,
        'planned_datetime': planned_datetime,
        'source': source,
    }

    # Buyurtmani tarixga yozish
    _archive_order(
        order_id=order_id,
        seller_id=target_seller.id if target_seller else f"biz_{business_phone}",
        seller_name=business_name or (target_seller.full_name if target_seller else ''),
        status='new',
        total=order.get('total_price', 0),
        items=items,
        notified_at=datetime.now().isoformat(),
    )

    bot = NotificationBot()
    if target_seller and target_seller.group_chat_id:
        success = await bot.send_order_notification(order_data)
        if success:
            sent_orders.add(order_id)
            logger.info(f"Order {order_id} sent to {business_name}")
        return success
    else:
        existing_order = Order.get(external_id=str(order_id))
        if not existing_order:
            dummy_seller_id = target_seller.id if target_seller else f"biz_{business_phone}"
            new_order = Order(
                external_id=str(order_id),
                seller_id=dummy_seller_id,
                status='new',
                customer_name=customer_name,
                customer_phone=customer_phone,
                total_amount=order_data.get('total', 0),
                items=items,
                telegram_message_id='0',
                notified_at=datetime.now().isoformat(),
                delivery_address=delivery_address,
                delivery_type=delivery_type,
                order_delivery_method=order_data.get('delivery_method', ''),
                payment_method=order_data.get('payment_method', ''),
                planned_datetime=order_data.get('planned_datetime', ''),
                source=order_data.get('source', ''),
                seller_name=business_name,
            )
            new_order.save()
            logger.info(f"Order {order_id} saved (no group, awaiting 3-min alert)")
        sent_orders.add(order_id)
        return True


async def fetch_and_send_orders():
    """Fallback polling: API dan buyurtmalarni olish (webhook ishlamasa uchun)"""
    global sent_orders
    from .models import Seller, Order

    api_url = os.getenv('EXTERNAL_API_URL')
    if not api_url:
        return

    # state parametri qo'shsak API barcha statuslarni qaytaradi
    if '?' not in api_url:
        api_url += '?state=PENDING'
    elif 'state=' not in api_url:
        api_url += '&state=PENDING'

    try:
        api_secret = os.getenv('EXTERNAL_API_SECRET', 'nonbor-secret-key')
        headers = {"X-Telegram-Bot-Secret": api_secret}

        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(api_url, headers=headers) as response:
                if response.status != 200:
                    logger.error(f"API error: {response.status}")
                    return
                data = await response.json()

        if isinstance(data, dict):
            if 'result' in data and isinstance(data['result'], dict) and 'results' in data['result']:
                orders = data['result']['results']
                total_count = data['result'].get('total_count', len(orders))
            elif 'results' in data:
                orders = data['results']
                total_count = len(orders)
            else:
                orders = data if isinstance(data, list) else []
                total_count = len(orders)
        else:
            orders = data if isinstance(data, list) else []
            total_count = len(orders)

        states_found = {o.get('state', '') for o in orders}
        logger.info(f"Orders API: total={total_count}, fetched={len(orders)}, states={states_found}")

        for order in orders:
            _archive_order_from_api(order)
            await _process_single_order(order)

        # CHECKING dan chiqib ketgan buyurtmalar xabarini o'chirish
        # Faqat API muvaffaqiyatli ishlaganda (exception bo'lmagan) ishlaydi
        active_api_ids = {
            str(o.get('id')) for o in orders
            if (o.get('state') or '').upper() == 'CHECKING'
        }
        await _delete_finished_order_messages(active_api_ids)

        _save_sent_orders()

    except Exception as e:
        logger.exception(f"Error fetching orders: {e}")


async def _delete_finished_order_messages(active_api_ids: set):
    """
    API dan CHECKING/PENDING holatida bo'lmagan buyurtmalarning
    Telegram guruh xabarini avtomatik o'chirish.
    """
    from .models import Order, Seller

    all_orders = Order.load_all()
    bot = NotificationBot().bot

    for od in all_orders:
        if od.get('status') != 'new':
            continue
        ext_id = str(od.get('external_id', ''))
        if not ext_id or ext_id in active_api_ids:
            continue

        # Bu order endi API da aktiv emas — xabarni o'chirish
        msg_id = od.get('telegram_message_id', '0')
        seller_id = od.get('seller_id', '')

        if msg_id and msg_id != '0':
            seller = Seller.get(id=seller_id)
            if seller and seller.group_chat_id:
                try:
                    await bot.delete_message(
                        chat_id=int(seller.group_chat_id),
                        message_id=int(msg_id)
                    )
                    logger.info(f"Order #{ext_id} xabari o'chirildi (CHECKING dan chiqdi)")
                except TelegramError:
                    pass

        # Statusni yangilash
        order_obj = Order.from_dict(od)
        order_obj.status = 'accepted'
        order_obj.save()
        sent_orders.discard(int(ext_id) if ext_id.isdigit() else ext_id)

        # Alert ham o'chirish
        try:
            await clear_seller_alert(seller_id, bot)
        except Exception:
            pass


async def fetch_and_send_amocrm_orders():
    """AmoCRM dan TEKSHIRILMOQDA statusidagi buyurtmalarni olish va yuborish"""
    global sent_amocrm_leads
    from .models import Seller, Order
    from .services.amocrm import AmoCRMService

    amocrm = AmoCRMService()
    if not amocrm.is_configured():
        return

    try:
        # Faol sotuvchilarni olish
        sellers = Seller.filter(is_active=True)
        if not sellers:
            logger.warning("No active sellers found")
            return

        bot = NotificationBot()

        # Har bir sotuvchi uchun uning biznesiga tegishli buyurtmalarni olish
        for seller in sellers:
            if not seller.group_chat_id:
                continue

            # Sotuvchi biznes nomini olish (full_name = biznes nomi)
            business_name = seller.full_name

            # Faqat shu biznesga tegishli buyurtmalarni olish
            orders = await amocrm.get_orders_for_notification(business_filter=business_name)

            if orders:
                logger.info(f"AmoCRM: {len(orders)} orders for '{business_name}'")

            for order_data in orders:
                lead_id = order_data.get('amocrm_lead_id')
                order_id = order_data.get('id')

                # Allaqachon yuborilgan bo'lsa, o'tkazib yubor
                if lead_id in sent_amocrm_leads:
                    continue

                # DB da borligini tekshirish
                existing = Order.get(external_id=str(order_id))
                if existing:
                    sent_amocrm_leads.add(lead_id)
                    continue

                # Seller ID ni qo'shish
                order_data['seller_id'] = seller.id

                # Yuborish
                success = await bot.send_order_notification(order_data)
                if success:
                    sent_amocrm_leads.add(lead_id)
                    logger.info(f"AmoCRM order #{order_id} (lead {lead_id}) sent to '{business_name}' group")

    except Exception as e:
        logger.error(f"Error fetching AmoCRM orders: {e}")


async def cleanup_expired_orders():
    """
    Qabul qilinmagan va muddati o'tgan buyurtmalarni guruhdan o'chirish.
    Faqat 'new' statusidagi buyurtmalar tekshiriladi.
    """
    from .models import Seller, Order

    try:
        bot = NotificationBot()
        now = datetime.now()
        deleted_count = 0

        # Barcha buyurtmalarni olish
        orders = Order.load_all()

        for order_data in orders:
            order = Order.from_dict(order_data)

            # Faqat 'new' statusidagi buyurtmalarni tekshirish
            if order.status != 'new':
                continue

            # notified_at vaqtini tekshirish
            if not order.notified_at:
                continue

            try:
                # ISO format: 2026-01-17T02:46:21.445684
                notified_time = datetime.fromisoformat(order.notified_at)
                expiry_time = notified_time + timedelta(minutes=ORDER_EXPIRY_MINUTES)

                # Muddat o'tganmi?
                if now > expiry_time:
                    # Sotuvchini topish
                    seller = Seller.get(id=order.seller_id)

                    if seller and seller.group_chat_id and order.telegram_message_id:
                        try:
                            # Telegram dan xabarni o'chirish
                            await bot.bot.delete_message(
                                chat_id=int(seller.group_chat_id),
                                message_id=int(order.telegram_message_id)
                            )
                            logger.info(f"Deleted expired order message #{order.external_id} from group {seller.group_chat_id}")
                        except TelegramError as te:
                            # Xabar allaqachon o'chirilgan bo'lishi mumkin
                            logger.warning(f"Could not delete message for order #{order.external_id}: {te}")

                    # Buyurtma statusini 'expired' ga o'zgartirish
                    order.status = 'expired'
                    order.save()
                    deleted_count += 1
                    logger.info(f"Order #{order.external_id} marked as expired")

            except ValueError as ve:
                logger.warning(f"Invalid notified_at format for order #{order.external_id}: {ve}")
                continue

        if deleted_count > 0:
            logger.info(f"Cleanup completed: {deleted_count} expired orders processed")

    except Exception as e:
        logger.error(f"Error cleaning up expired orders: {e}")


def _format_missed_alert(seller, missed_orders, call_count=0):
    """Admin guruhiga yuboriladigan alert xabari"""
    count = len(missed_orders)
    total_sum = sum(o.total_amount for o in missed_orders)

    lines = [f"🚨 <b>DIQQAT! {count} ta buyurtma qabul qilinmadi!</b>\n\n"]
    lines.append(
        f"<b>SOTUVCHI:</b>\n"
        f"  Nomi: {seller.full_name}\n"
        f"  Tel: {seller.phone}\n"
        f"  Manzil: {seller.address or '—'}\n"
    )
    lines.append("\n<b>━━━ BUYURTMALAR ━━━</b>\n\n")
    for i, o in enumerate(missed_orders, 1):
        DELIVERY_LABELS = {'DELIVERY': '🚴 Yetkazib berish', 'PICKUP': '🏪 Olib ketish'}
        PAYMENT_LABELS = {
            'CASH': '💵 Naqd', 'CARD': '💳 Karta',
            'PAYME': '💳 Payme', 'CLICK': '💳 Click',
            'UZUM': '💳 Uzum Bank', 'HUMO': '💳 Humo', 'UZCARD': '💳 Uzcard',
        }
        dm = (getattr(o, 'order_delivery_method', '') or '').upper()
        pm = (getattr(o, 'payment_method', '') or '').upper()
        planned = getattr(o, 'planned_datetime', '') or ''
        source = getattr(o, 'source', '') or ''

        items_text = ""
        items_total = 0
        item_list = o.items or []
        for idx, item in enumerate(item_list, 1):
            item_price = int(item.get('price', 0)) // 100
            qty = item.get('quantity', 1)
            line_total = item_price * qty
            items_total += line_total
            if qty > 1:
                items_text += f"   {idx}. {item.get('name', '?')} x{qty} = {line_total:,} so'm\n"
            else:
                items_text += f"   {idx}. {item.get('name', '?')} — {item_price:,} so'm\n"
        order_total = int(o.total_amount) // 100
        delivery_fee = order_total - items_total
        if delivery_fee > 0:
            delivery_fee_line = f"   🚴 Yetkazib berish: {delivery_fee:,} so'm\n"
        else:
            delivery_fee_line = "   🚴 Yetkazib berish: 0 so'm\n"

        extra = ''
        if dm and dm in DELIVERY_LABELS:
            extra += f"   🚚 Yetkazish: {DELIVERY_LABELS[dm]}\n"
        if pm and pm in PAYMENT_LABELS:
            extra += f"   💰 To'lov: {PAYMENT_LABELS[pm]}\n"
        if planned:
            try:
                pt = datetime.fromisoformat(planned[:19])
                extra += f"   📅 Reja: {pt.strftime('%d.%m.%Y %H:%M')}\n"
            except Exception:
                extra += f"   📅 Reja: {planned}\n"
        if source:
            extra += f"   📱 Platforma: {source}\n"

        lines.append(
            f"{i}. Buyurtma <b>#{o.external_id}</b>\n"
            f"   Mijoz: {o.customer_name or '—'}\n"
            f"   Tel: {o.customer_phone or '—'}\n"
            f"{items_text}"
            f"   📦 Mahsulotlar: {items_total:,} so'm\n"
            f"{delivery_fee_line}"
            f"   💰 Jami: {order_total:,} so'm\n"
            f"{extra}\n"
        )
    crm_url = os.getenv('CRM_ORDERS_URL', '')
    crm_line = f"\n📱 Buyurtmalarni ko'rish ({crm_url})" if crm_url else ""
    call_line = f"📞 {call_count} marta qo'ng'iroq qilindi.\n" if call_count > 0 else ""
    lines.append(
        f"<b>━━━━━━━━━━━━━━━━━━━━━</b>\n"
        f"📦 Jami buyurtmalar: <b>{count} ta</b>\n"
        f"💰 Umumiy: <b>{int(total_sum) // 100:,} so'm</b>\n\n"
        f"❌ Buyurtmalarni qabul qilmayapti!\n"
        f"{call_line}"
        f"🔴 Zudlik bilan bog'laning!"
        f"{crm_line}"
    )
    return "".join(lines).replace(",", " ")


async def clear_seller_alert(seller_id, bot):
    """Sotuvchining alert xabarini o'chirish (buyurtma qabul/rad qilinanda)"""
    try:
        tracker = _load_alert_tracker()
        entry = tracker.get(str(seller_id))
        if not entry:
            return
        try:
            await bot.delete_message(
                chat_id=int(entry['chat_id']),
                message_id=int(entry['message_id'])
            )
        except TelegramError:
            pass
        tracker.pop(str(seller_id), None)
        _save_alert_tracker(tracker)
    except Exception as e:
        logger.warning(f"clear_seller_alert error: {e}")




async def check_missed_orders():
    """3 daqiqadan ortiq qabul qilinmagan buyurtmalarni admin guruhga xabar yuborish"""
    from .models import Seller, Order, AdminSettings

    admin_group_id = AdminSettings.get_admin_group_chat_id()
    if not admin_group_id:
        return

    now = datetime.now()
    threshold = timedelta(minutes=MISSED_ORDER_MINUTES)
    all_orders = Order.load_all()
    bot = NotificationBot().bot
    tracker = _load_alert_tracker()
    tracker_updated = False

    # Seller bo'yicha 'new' statusdagi, 3 daqiqadan o'tgan buyurtmalar
    seller_missed: dict = {}
    for od in all_orders:
        if od.get('status') != 'new':
            continue
        notified_at = od.get('notified_at')
        if not notified_at:
            continue
        try:
            t = datetime.fromisoformat(notified_at)
        except ValueError:
            continue
        if now - t < threshold:
            continue
        sid = od.get('seller_id', '')
        if sid not in seller_missed:
            seller_missed[sid] = []
        seller_missed[sid].append(Order.from_dict(od))

    # Alert yuborish yoki mavjud xabarni edit qilish
    for seller_id, missed in seller_missed.items():
        seller = Seller.get(id=seller_id)
        if not seller:
            from .models import Seller as SellerModel
            # seller_name ni birinchi missed orderdan olish
            seller_name = getattr(missed[0], 'seller_name', '') if missed else ''
            seller = SellerModel(id=seller_id, full_name=seller_name or 'Noma\'lum biznes', phone='')

        old_entry = tracker.get(str(seller_id))
        order_count = len(missed)
        call_count = old_entry.get('call_count', 0) if old_entry else 0

        prev_order_count = old_entry.get('order_count', -1) if old_entry else -1
        prev_call_count = old_entry.get('call_count', -1) if old_entry else -1
        content_changed = (prev_order_count != order_count or prev_call_count != call_count)

        if old_entry and old_entry.get('chat_id') and old_entry.get('message_id'):
            if not content_changed:
                continue
            alert_text = _format_missed_alert(seller, missed, call_count=call_count)
            try:
                await bot.edit_message_text(
                    chat_id=int(old_entry['chat_id']),
                    message_id=int(old_entry['message_id']),
                    text=alert_text,
                    parse_mode='HTML'
                )
                tracker[str(seller_id)]['order_count'] = order_count
                tracker_updated = True
                continue
            except TelegramError as e:
                if 'message is not modified' in str(e).lower():
                    continue
                tracker.pop(str(seller_id), None)

        # Yangi alert yuborish (birinchi marta yoki xabar o'chirilgan)
        alert_text = _format_missed_alert(seller, missed, call_count=call_count)
        try:
            msg = await bot.send_message(
                chat_id=int(admin_group_id),
                text=alert_text,
                parse_mode='HTML'
            )
            tracker[str(seller_id)] = {
                'message_id': msg.message_id,
                'chat_id': int(admin_group_id),
                'order_count': order_count,
                'call_count': call_count,
            }
            tracker_updated = True
            logger.info(f"Missed order alert sent: {seller.full_name} ({order_count} orders)")
        except Exception as e:
            logger.error(f"Failed to send missed order alert: {e}")

    # Faqat 'new' orderlari yo'q sellerlarning alertlarini o'chirish
    active_seller_ids = {
        od.get('seller_id', '')
        for od in all_orders
        if od.get('status') == 'new' and od.get('seller_id')
    }
    for seller_id in list(tracker.keys()):
        if seller_id not in active_seller_ids:
            entry = tracker[seller_id]
            if entry.get('chat_id') and entry.get('message_id'):
                try:
                    await bot.delete_message(
                        chat_id=int(entry['chat_id']),
                        message_id=int(entry['message_id'])
                    )
                except TelegramError:
                    pass
            tracker.pop(seller_id)
            tracker_updated = True

    if tracker_updated:
        _save_alert_tracker(tracker)


async def check_and_call_sellers():
    """WAIT_BEFORE_CALL sekunddan keyin Asterisk AMI orqali qo'ng'iroq (faqat CHECKING buyurtmalar)"""
    from .models import Seller, Order
    from .services.asterisk import ami_make_call

    now = datetime.now()
    call_threshold = timedelta(seconds=WAIT_BEFORE_CALL)
    all_orders = Order.load_all()
    tracker = _load_alert_tracker()
    tracker_updated = False

    seller_orders: dict = {}
    for od in all_orders:
        if od.get('status') != 'new':
            continue
        notified_at = od.get('notified_at')
        if not notified_at:
            continue
        try:
            t = datetime.fromisoformat(notified_at)
        except ValueError:
            continue
        if now - t < call_threshold:
            continue
        sid = od.get('seller_id', '')
        seller_orders.setdefault(sid, []).append(od)

    for seller_id, orders in seller_orders.items():
        seller = Seller.get(id=seller_id)
        if not seller or not seller.phone:
            continue

        entry = tracker.get(str(seller_id), {})
        call_count = entry.get('call_count', 0)
        last_call_at = entry.get('last_call_at')

        if call_count >= MAX_CALL_ATTEMPTS:
            continue

        if last_call_at:
            try:
                elapsed = (now - datetime.fromisoformat(last_call_at)).total_seconds()
                if elapsed < RETRY_INTERVAL:
                    continue
            except ValueError:
                pass

        logger.info(f"Qo'ng'iroq: {seller.full_name} ({seller.phone}), urinish #{call_count + 1}")
        success = await ami_make_call(seller.phone)
        log_ami_call(str(seller_id), seller.full_name, seller.phone, success)

        if success:
            call_count += 1
            tracker.setdefault(str(seller_id), {})
            tracker[str(seller_id)]['call_count'] = call_count
            tracker[str(seller_id)]['last_call_at'] = now.isoformat()
            tracker_updated = True

            if tracker[str(seller_id)].get('message_id') and tracker[str(seller_id)].get('chat_id'):
                try:
                    from .models import AdminSettings
                    admin_group_id = AdminSettings.get_admin_group_chat_id()
                    if admin_group_id:
                        from .models import Order as OrderModel
                        missed = [OrderModel.from_dict(o) for o in orders]
                        seller_obj = seller
                        alert_text = _format_missed_alert(seller_obj, missed, call_count=call_count)
                        tg_bot = NotificationBot().bot
                        await tg_bot.edit_message_text(
                            chat_id=int(tracker[str(seller_id)]['chat_id']),
                            message_id=int(tracker[str(seller_id)]['message_id']),
                            text=alert_text,
                            parse_mode='HTML'
                        )
                except TelegramError as e:
                    if 'message is not modified' not in str(e).lower():
                        logger.warning(f"Alert yangilashda xato: {e}")
                except Exception as e:
                    logger.warning(f"Alert yangilashda xato: {e}")
        else:
            logger.warning(f"Qo'ng'iroq muvaffaqiyatsiz: {seller.full_name} ({seller.phone})")

    if tracker_updated:
        _save_alert_tracker(tracker)


async def _send_stats_now():
    """Admin so'rovi bilan darhol tungi statistika yuborish (sozlangan davr)"""
    from .models import AdminSettings
    cfg = AdminSettings.get_stats_config()
    await _build_and_send_stats(
        period_start_str=cfg['period_start'],
        period_end_str=cfg['period_end'],
        label="TUNGI STATISTIKA"
    )


async def _build_and_send_stats(period_start_str: str, period_end_str: str, label: str = "KUNLIK STATISTIKA"):
    """Statistikani yaratib yuborish — asosiy logika"""
    from .models import Seller, AdminSettings

    now = datetime.now()

    def parse_hm(s):
        h, m = map(int, s.split(':'))
        return h * 60 + m

    start_min = parse_hm(period_start_str)
    end_min = parse_hm(period_end_str)

    period_end_dt = now.replace(
        hour=int(period_end_str.split(':')[0]),
        minute=int(period_end_str.split(':')[1]),
        second=59, microsecond=999999
    )
    if start_min > end_min:
        period_start_dt = (period_end_dt - timedelta(days=1)).replace(
            hour=int(period_start_str.split(':')[0]),
            minute=int(period_start_str.split(':')[1]),
            second=0, microsecond=0
        )
    else:
        period_start_dt = period_end_dt.replace(
            hour=int(period_start_str.split(':')[0]),
            minute=int(period_start_str.split(':')[1]),
            second=0, microsecond=0
        )

    # Tarixdan o'qish
    all_history = _load_order_history()
    period_orders = []
    for od in all_history:
        notified_at = od.get('notified_at', '')
        if not notified_at:
            continue
        try:
            t = datetime.fromisoformat(notified_at[:19])
            if period_start_dt <= t <= period_end_dt:
                period_orders.append(od)
        except ValueError:
            continue

    # Call logi
    call_log = _load_call_log()
    period_calls = []
    for c in call_log:
        cat = c.get('called_at', '')
        try:
            t = datetime.fromisoformat(cat[:19])
            if period_start_dt <= t <= period_end_dt:
                period_calls.append(c)
        except ValueError:
            continue

    total = len(period_orders)
    accepted  = sum(1 for o in period_orders if o.get('status') == 'accepted')
    rejected  = sum(1 for o in period_orders if o.get('status') == 'rejected')
    expired   = sum(1 for o in period_orders if o.get('status') == 'expired')
    new_count = sum(1 for o in period_orders if o.get('status') == 'new')

    seller_stats: dict = {}
    for od in period_orders:
        sid = od.get('seller_id', 'unknown')
        if sid not in seller_stats:
            name = od.get('seller_name', '')
            if not name:
                s = Seller.get(id=sid)
                name = s.full_name if s else sid[:12]
            seller_stats[sid] = {
                'name': name, 'total': 0,
                'accepted': 0, 'rejected': 0, 'expired': 0, 'new': 0,
                'calls': 0, 'calls_success': 0,
            }
        seller_stats[sid]['total'] += 1
        st = od.get('status', 'new')
        if st in seller_stats[sid]:
            seller_stats[sid][st] += 1
        else:
            seller_stats[sid]['new'] += 1

    for c in period_calls:
        sid = c.get('seller_id', '')
        if sid in seller_stats:
            seller_stats[sid]['calls'] += 1
            if c.get('success'):
                seller_stats[sid]['calls_success'] += 1

    date_label = (period_start_dt.strftime('%d.%m.%Y %H:%M') +
                  ' — ' + period_end_dt.strftime('%d.%m.%Y %H:%M'))
    lines = [
        f"📊 <b>{label}</b>\n"
        f"🕐 {date_label}\n\n"
        f"📦 Jami: <b>{total} ta</b>\n"
        f"✅ Qabul qilingan: <b>{accepted} ta</b>\n"
        f"❌ Rad etilgan: <b>{rejected} ta</b>\n"
        f"⏰ Muddati o'tgan: <b>{expired} ta</b>\n"
        f"⏳ Kutilmoqda: <b>{new_count} ta</b>\n"
    ]

    if seller_stats:
        lines.append("\n<b>━━━ RESTORANLAR ━━━</b>\n")
        for i, (sid, s) in enumerate(seller_stats.items(), 1):
            call_info = ''
            if s['calls'] > 0:
                result = "javob berdi ✅" if s['calls_success'] > 0 else "javob bermadi ❌"
                call_info = f"   📞 {s['calls']} marta qo'ng'iroq — {result}\n"
            lines.append(
                f"{i}. <b>{s['name']}</b>\n"
                f"   📦 {s['total']} ta | ✅{s['accepted']} ❌{s['rejected']} ⏰{s['expired']} ⏳{s['new']}\n"
                f"{call_info}"
            )

    text = "".join(lines)
    admin_group_id = AdminSettings.get_admin_group_chat_id()
    admin_ids = [a.strip() for a in os.getenv('ADMIN_IDS', '').split(',') if a.strip()]
    tg_bot = NotificationBot().bot

    if admin_group_id:
        try:
            await tg_bot.send_message(chat_id=int(admin_group_id), text=text, parse_mode='HTML')
        except TelegramError as e:
            logger.error(f"Stats guruhga yuborishda xato: {e}")
    for admin_id in admin_ids:
        try:
            await tg_bot.send_message(chat_id=int(admin_id), text=text, parse_mode='HTML')
        except TelegramError as e:
            logger.error(f"Stats adminga yuborishda xato: {e}")

    logger.info(f"Statistika yuborildi: {total} buyurtma ({period_start_str}—{period_end_str})")


async def generate_and_send_daily_stats():
    """Kunlik statistikani yaratib admin va admin guruhga yuborish"""
    global _stats_sent_today
    from .models import AdminSettings

    config = AdminSettings.get_stats_config()
    period_start_str = config.get('period_start', '22:30')
    period_end_str = config.get('period_end', '08:00')
    send_time_str = config.get('send_time', '08:05')

    now = datetime.now()
    current_time_str = now.strftime('%H:%M')

    # Bugun allaqachon yuborilganmi
    today_key = now.strftime('%Y-%m-%d') + '_' + send_time_str
    if _stats_sent_today == today_key:
        return

    if current_time_str != send_time_str:
        return

    await _build_and_send_stats(period_start_str, period_end_str)
    _stats_sent_today = today_key
    logger.info(f"Kunlik statistika yuborildi ({period_start_str}-{period_end_str})")


async def check_api_health():
    """
    API health monitoring — har daqiqa tekshiriladi.
    Ishlamasa: admin + guruhga xabar. Har daqiqa eski xabar o'chirib yangi yuboradi.
    Ishlasa: down xabarlar o'chiriladi, recovery xabari keladi.
    """
    global _api_health
    from .models import AdminSettings

    cfg = AdminSettings.get_health_config()
    url = cfg['url']
    if not url:
        return

    now = datetime.now()
    api_secret = os.getenv('EXTERNAL_API_SECRET', 'nonbor-secret-key')
    headers = {"X-Telegram-Bot-Secret": api_secret}

    success = False
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as resp:
                success = resp.status < 500
    except Exception:
        success = False

    tg_bot = NotificationBot().bot
    admin_ids = [a.strip() for a in os.getenv('ADMIN_IDS', '').split(',') if a.strip()]
    admin_group_id = AdminSettings.get_admin_group_chat_id()

    async def _delete_health_alerts():
        """Barcha yuborilgan down xabarlarini o'chirish"""
        for item in _api_health.get('alert_messages', []):
            try:
                await tg_bot.delete_message(
                    chat_id=item['chat_id'],
                    message_id=item['message_id']
                )
            except TelegramError:
                pass
        _api_health['alert_messages'] = []

    async def _send_to_all(text: str, save=False):
        """Admin va guruhga xabar yuborish, ixtiyoriy message_id saqlanadi"""
        messages = []
        for chat_id in ([int(a) for a in admin_ids] +
                        ([int(admin_group_id)] if admin_group_id else [])):
            try:
                msg = await tg_bot.send_message(chat_id=chat_id, text=text, parse_mode='HTML')
                if save:
                    messages.append({'chat_id': chat_id, 'message_id': msg.message_id})
            except TelegramError as e:
                logger.error(f"Health xabar yuborishda xato ({chat_id}): {e}")
        if save:
            _api_health['alert_messages'] = messages

    if success:
        _api_health['last_ok'] = now.isoformat()
        if _api_health.get('is_down'):
            # Tiklandi
            down_since = _api_health.get('down_since', now.isoformat())
            try:
                mins = int((now - datetime.fromisoformat(down_since)).total_seconds() / 60)
                duration = f"{mins} daqiqa" if mins > 0 else "bir necha soniya"
            except Exception:
                duration = "noma'lum"

            await _delete_health_alerts()
            text = (
                f"✅ <b>API tiklandi!</b>\n\n"
                f"⏱ Ishlamagan vaqt: <b>{duration}</b>\n"
                f"🕐 {now.strftime('%H:%M:%S')}"
            )
            await _send_to_all(text)
            logger.info(f"API tiklandi: {url} ({duration})")

        _api_health['is_down'] = False
        _api_health['down_since'] = None
        return

    # API ishlamayapti
    if not _api_health.get('is_down'):
        _api_health['is_down'] = True
        _api_health['down_since'] = now.isoformat()
        _api_health['alert_messages'] = []

    down_since = _api_health.get('down_since', now.isoformat())
    last_ok = _api_health.get('last_ok', '')
    try:
        mins = int((now - datetime.fromisoformat(down_since)).total_seconds() / 60)
        since_str = datetime.fromisoformat(down_since).strftime('%H:%M:%S')
        duration = f"{mins} daqiqa" if mins > 0 else "hozirgina"
    except Exception:
        since_str = '—'
        duration = 'noma\'lum'

    last_ok_str = ''
    if last_ok:
        try:
            last_ok_str = datetime.fromisoformat(last_ok).strftime('%H:%M:%S')
        except Exception:
            pass

    text = (
        f"🔴 <b>API ISHLAMAYAPTI!</b>\n\n"
        f"🕐 {since_str} dan beri ishlamayapti ({duration})\n"
        f"✅ Oxirgi muvaffaqiyatli: {last_ok_str or '—'}\n"
        f"🔗 <code>{url[:60]}</code>"
    )

    # Eski xabarni o'chirib, yangi xabar yuborish
    await _delete_health_alerts()
    await _send_to_all(text, save=True)
    logger.warning(f"API down: {url} — {duration}")
