import os
import logging
import aiohttp
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError
from datetime import datetime, timedelta

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
            
            logger.info(f"Order {order_data.get('id')} sent to group {seller.group_chat_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error sending notification: {e}")
            return False
    
    async def _find_seller(self, order_data):
        """Sotuvchini topish"""
        from .models import Seller
        
        seller = None
        
        # 1. seller_id orqali
        seller_id = order_data.get('seller_id')
        if seller_id:
            seller = Seller.get(id=seller_id, is_active=True)
            if seller:
                return seller
        
        # 2. phone orqali
        phone = order_data.get('seller_phone')
        if phone:
            seller = Seller.get(phone=phone, is_active=True)
            if seller:
                return seller
        
        # 3. Birinchi faol sotuvchi
        sellers = Seller.filter(is_active=True)
        if sellers:
            return sellers[0]
        
        return None
    
    def _format_order_message(self, order_data, show_customer=False):
        """
        Xabar matnini formatlash

        Args:
            order_data: Buyurtma ma'lumotlari
            show_customer: True bo'lsa mijoz ma'lumotlarini ko'rsatadi (Tayyor bosilganda)
        """
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

        # Asosiy xabar - faqat buyurtma tafsilotlari
        message = f"""
🛍️ <b>YANGI BUYURTMA</b>

📦 <b>Buyurtma:</b> #{order_data.get('id', 'N/A')}

📋 <b>Mahsulotlar ({total_items} ta):</b>
{items_text}
💰 <b>Jami:</b> {order_data.get('total', 0):,} som
"""

        # Mijoz ma'lumotlari faqat "Tayyor" bosilganda ko'rsatiladi
        if show_customer:
            customer = order_data.get('customer', {})
            delivery_address = order_data.get('delivery_address', '')

            phone_display = customer.get('phone', '')
            if not phone_display or phone_display == 'Nomalum':
                phone_display = "Ko'rsatilmagan"

            message += f"""
━━━━━━━━━━━━━━━━━━━━
👤 <b>Mijoz:</b> {customer.get('name', 'Nomalum')}
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


async def fetch_and_send_orders():
    """API dan buyurtmalarni olish va tegishli do'konlarga yuborish"""
    global sent_orders
    from .models import Seller, Order

    api_url = os.getenv('EXTERNAL_API_URL')
    if not api_url:
        return

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as response:
                if response.status != 200:
                    logger.error(f"API error: {response.status}")
                    return

                data = await response.json()

        # API javob formati: {"success": true, "result": {"results": [...]}}
        if isinstance(data, dict):
            if 'result' in data and 'results' in data['result']:
                orders = data['result']['results']
            elif 'results' in data:
                orders = data['results']
            else:
                orders = data if isinstance(data, list) else []
        else:
            orders = data if isinstance(data, list) else []

        if not orders:
            return

        # Debug: barcha biznes nomlarini ko'rish
        business_names = set()
        max_order_id = 0
        for o in orders:
            b = o.get('business', {})
            bn = b.get('title', 'NO_TITLE')
            business_names.add(bn)
            oid = o.get('id', 0)
            if isinstance(oid, int) and oid > max_order_id:
                max_order_id = oid
        logger.info(f"API: {len(orders)} orders, max_id={max_order_id}")

        bot = NotificationBot()

        for order in orders:
            order_id = order.get('id')

            # Allaqachon yuborilgan bo'lsa, o'tkazib yubor
            if order_id in sent_orders:
                continue

            # AmoCRM da mavjud bo'lsa, o'tkazib yubor (allaqachon qayta ishlangan)
            amocrm_id = order.get('amocrm_id') or order.get('amo_id') or order.get('crm_id')
            if amocrm_id:
                sent_orders.add(order_id)
                continue

            # Faqat yangi buyurtmalarni yuborish (state = NEW yoki PENDING)
            state = order.get('state', '').upper()
            business = order.get('business', {})
            business_name = business.get('title', '')

            # Debug Milliy uchun
            if business_name == 'Milliy':
                logger.info(f"Milliy order {order_id}: state={state}, amocrm_id={order.get('amocrm_id')}, in_sent={order_id in sent_orders}")

            # Debug: 1700+ buyurtmalar
            if order_id > 1700:
                logger.info(f"Order {order_id}: business={business_name}, state={state}")

            # Faqat CHECKING statusidagi buyurtmalarni olish
            # CHECKING = to'lov qilingan, rasmiylashtirilgan buyurtmalar
            # NEW/PENDING = hali to'liq rasmiylashtirilmagan
            if state != 'CHECKING':
                sent_orders.add(order_id)
                continue

            # DB da borligini tekshirish
            existing = Order.get(external_id=str(order_id))
            if existing:
                sent_orders.add(order_id)
                continue

            # Biznesni topish
            business = order.get('business', {})
            business_name = business.get('title', '')

            # Sotuvchini topish (business nomi bo'yicha)
            sellers = Seller.filter(is_active=True)
            target_seller = None

            for seller in sellers:
                if seller.full_name == business_name:
                    target_seller = seller
                    break

            if not target_seller or not target_seller.group_chat_id:
                logger.warning(f"No seller/group for business: {business_name}")
                continue

            # Buyurtma ma'lumotlarini formatlash
            delivery = order.get('delivery', {})
            order_items = order.get('order_item', [])

            items = []
            for item in order_items:
                product = item.get('product', {})
                items.append({
                    'name': product.get('name', 'Nomalum'),
                    'price': product.get('price', 0),
                    'quantity': item.get('quantity', 1)
                })

            # Mijoz telefon raqamini olish
            customer_phone = delivery.get('phone', '') or delivery.get('customer_phone', '') or order.get('customer_phone', '')
            customer_name = delivery.get('name', '') or delivery.get('customer_name', '') or f"Mijoz #{order_id}"

            # delivery_method: PICKUP yoki DELIVERY
            delivery_method = order.get('delivery_method', 'DELIVERY').upper()
            delivery_type = 'pickup' if delivery_method == 'PICKUP' else 'delivery'

            order_data = {
                'id': order_id,
                'seller_id': target_seller.id,
                'status': 'new',
                'customer': {
                    'name': customer_name,
                    'phone': customer_phone,
                },
                'total': order.get('total_price', 0),
                'items': items,
                'delivery_address': delivery.get('address', ''),
                'delivery_type': delivery_type,
            }

            # Yuborish
            success = await bot.send_order_notification(order_data)
            if success:
                sent_orders.add(order_id)
                logger.info(f"Order {order_id} sent to {business_name}")

    except Exception as e:
        logger.error(f"Error fetching orders: {e}")


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
