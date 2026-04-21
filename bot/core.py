import os
import json
import logging
import aiohttp
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError
from datetime import datetime, timedelta

ALERT_TRACKER_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'alert_tracker.json')
SUMMARY_MSG_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'summary_msg.json')
MISSED_ORDER_MINUTES = int(os.getenv('MISSED_ORDER_MINUTES', 3))

# Asterisk autodialer sozlamalari
WAIT_BEFORE_CALL = int(os.getenv('WAIT_BEFORE_CALL', 90))       # sekund
MAX_CALL_ATTEMPTS = int(os.getenv('MAX_CALL_ATTEMPTS', 2))
RETRY_INTERVAL = int(os.getenv('RETRY_INTERVAL', 30))            # sekund


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


# Oxirgi yuborilgan summary matni — o'zgarish bo'lmasa edit qilmaymiz
_last_summary_text = ''


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

# Yuborilgan buyurtmalar (qayta yuborilmasligi uchun)
sent_orders = set()
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
        for item in items:
            quantity = item.get('quantity', 1)
            total_items += quantity
            item_total = item.get('price', 0) * quantity

            items_text += f"  • {item.get('name', 'Nomalum')}\n"
            if quantity > 1:
                items_text += f"    {quantity} x {item.get('price', 0):,} = {item_total:,} som\n"
            else:
                items_text += f"    {item.get('price', 0):,} som\n"

        customer = order_data.get('customer', {})
        delivery_address = order_data.get('delivery_address', '')
        phone_display = customer.get('phone', '') or ''
        if not phone_display or phone_display == 'Nomalum':
            phone_display = "Ko'rsatilmagan"
        name_display = customer.get('name', '') or 'Nomalum'

        message = f"""
🛍️ <b>YANGI BUYURTMA</b>

📦 <b>Buyurtma:</b> #{order_data.get('id', 'N/A')}

📋 <b>Mahsulotlar ({total_items} ta):</b>
{items_text}
💰 <b>Jami:</b> {order_data.get('total', 0):,} som

━━━━━━━━━━━━━━━━━━━━
👤 <b>Mijoz:</b> {name_display}
📞 <b>Telefon:</b> <code>{phone_display}</code>
📍 <b>Manzil:</b> {delivery_address if delivery_address else "Ko'rsatilmagan"}
"""

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
    NEW_ORDER_STATES = {'CHECKING', 'PENDING', 'NEW', 'CREATED'}
    if state and state not in NEW_ORDER_STATES:
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
    business_phone = business.get('phone', '')

    sellers = Seller.filter(is_active=True)
    target_seller = None
    for s in sellers:
        if s.business_phone and s.business_phone == business_phone:
            target_seller = s
            break
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
    delivery_method = (order.get('delivery_method') or 'DELIVERY').upper()
    delivery_type = 'pickup' if delivery_method == 'PICKUP' else 'delivery'

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
    }

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
            await _process_single_order(order)

    except Exception as e:
        logger.exception(f"Error fetching orders: {e}")


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
        items_text = ""
        for item in (o.items or []):
            items_text += (
                f"   Mahsulot: {item.get('name', '?')}\n"
                f"   Miqdor: {item.get('quantity', 1)} ta\n"
                f"   Narx: {item.get('price', 0):,} so'm\n"
            )
        lines.append(
            f"{i}. Buyurtma <b>#{o.external_id}</b>\n"
            f"   Mijoz: {o.customer_name or '—'}\n"
            f"   Tel: {o.customer_phone or '—'}\n"
            f"{items_text}\n"
        )
    crm_url = os.getenv('CRM_ORDERS_URL', '')
    crm_line = f"\n📱 Buyurtmalarni ko'rish ({crm_url})" if crm_url else ""
    call_line = f"📞 {call_count} marta qo'ng'iroq qilindi.\n" if call_count > 0 else ""
    lines.append(
        f"\n<b>━━━━━━━━━━━━━━━━━━━━━</b>\n"
        f"📦 Jami: <b>{count} ta buyurtma</b>\n"
        f"💰 Umumiy: <b>{total_sum:,} so'm</b>\n\n"
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


async def check_and_call_sellers():
    """WAIT_BEFORE_CALL sekunddan keyin sotuvchiga Asterisk AMI orqali qo'ng'iroq qilish"""
    from .models import Seller, Order
    from .services.asterisk import ami_make_call

    now = datetime.now()
    call_threshold = timedelta(seconds=WAIT_BEFORE_CALL)
    all_orders = Order.load_all()
    tracker = _load_alert_tracker()
    tracker_updated = False

    # Seller bo'yicha kutilayotgan buyurtmalarni guruhlash
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

        # MAX urinishga yetgan bo'lsa o'tkazib yuborish
        if call_count >= MAX_CALL_ATTEMPTS:
            continue

        # Retry interval tekshirish
        if last_call_at:
            try:
                elapsed = (now - datetime.fromisoformat(last_call_at)).total_seconds()
                if elapsed < RETRY_INTERVAL:
                    continue
            except ValueError:
                pass

        # Qo'ng'iroq qilish
        logger.info(f"Qo'ng'iroq qilinmoqda: {seller.full_name} ({seller.phone}), urinish #{call_count + 1}")
        success = await ami_make_call(seller.phone)

        if success:
            call_count += 1
            tracker.setdefault(str(seller_id), {})
            tracker[str(seller_id)]['call_count'] = call_count
            tracker[str(seller_id)]['last_call_at'] = now.isoformat()
            tracker_updated = True
            logger.info(f"Qo'ng'iroq muvaffaqiyatli: {seller.full_name}, jami: {call_count} ta")

            # Agar admin alerti yuborilgan bo'lsa — xabarni yangilash
            if tracker[str(seller_id)].get('message_id') and tracker[str(seller_id)].get('chat_id'):
                try:
                    from .models import AdminSettings
                    admin_group_id = AdminSettings.get_admin_group_chat_id()
                    if admin_group_id:
                        missed = [Order.from_dict(o) for o in orders]
                        alert_text = _format_missed_alert(seller, missed, call_count=call_count)
                        bot = NotificationBot().bot
                        await bot.edit_message_text(
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
            seller = SellerModel(id=seller_id, full_name='Noma\'lum biznes', phone='')

        old_entry = tracker.get(str(seller_id))
        call_count = old_entry.get('call_count', 0) if old_entry else 0
        order_count = len(missed)

        # Faqat o'zgarish bo'lsa yangilash
        prev_order_count = old_entry.get('order_count', -1) if old_entry else -1
        prev_call_count = old_entry.get('call_count', -1) if old_entry else -1
        content_changed = (prev_order_count != order_count or prev_call_count != call_count)

        if old_entry and old_entry.get('chat_id') and old_entry.get('message_id'):
            if not content_changed:
                continue  # Hech narsa o'zgarmagan — API chaqirmaymiz
            alert_text = _format_missed_alert(seller, missed, call_count=call_count)
            try:
                await bot.edit_message_text(
                    chat_id=int(old_entry['chat_id']),
                    message_id=int(old_entry['message_id']),
                    text=alert_text,
                    parse_mode='HTML'
                )
                tracker[str(seller_id)]['order_count'] = order_count
                tracker[str(seller_id)]['call_count'] = call_count
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

    # Endi missed bo'lmagan sellerlarning alertlarini o'chirish
    for seller_id in list(tracker.keys()):
        if seller_id not in seller_missed:
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
