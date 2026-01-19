"""
Telegram Bot Callback Handlers
Handles inline keyboard button presses for orders
"""
import os
import logging
import requests
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import TelegramError
from asgiref.sync import sync_to_async
from django.utils import timezone

logger = logging.getLogger('bot')


async def handle_order_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Buyurtma tugmalari uchun callback handler
    """
    query = update.callback_query
    data = query.data
    user = query.from_user

    # Callback data formatini parse qilish
    # Format: action_orderid
    parts = data.split('_', 1)
    if len(parts) < 2:
        await query.answer("❌ Noto'g'ri buyruq", show_alert=True)
        return

    action = parts[0]
    order_id = parts[1]

    logger.info(f"Callback: action={action}, order_id={order_id}, user={user.id}")

    # Action ga qarab ishlov berish
    if action == 'accept':
        await accept_order(query, order_id, user)
    elif action == 'reject':
        await reject_order(query, order_id, user)
    elif action == 'call':
        await show_call_info(query, order_id)
    elif action == 'details':
        await show_order_details(query, order_id)
    elif action == 'status':
        await show_status_options(query, order_id)
    elif action == 'setstatus':
        # Format: setstatus_orderid_newstatus
        remaining = parts[1].rsplit('_', 1)
        if len(remaining) == 2:
            order_id, new_status = remaining
            await update_order_status(query, order_id, new_status, user)
    else:
        await query.answer("❓ Noma'lum buyruq", show_alert=True)


async def accept_order(query, order_id: str, user):
    """
    Buyurtmani qabul qilish
    """
    from .models import Order

    await query.answer()

    try:
        # Buyurtmani topish va yangilash
        order = await sync_to_async(
            lambda: Order.objects.select_related('seller').get(external_id=order_id)
        )()

        # Status tekshirish
        if order.status != 'new':
            await query.answer(
                f"⚠️ Buyurtma allaqachon {order.status_display} holatida!",
                show_alert=True
            )
            return

        # Yangilash
        order.status = 'accepted'
        order.accepted_by = f"{user.full_name} ({user.id})"
        order.accepted_at = timezone.now()
        await sync_to_async(order.save)()

        # Xabarni yangilash - mijoz ma'lumotlari bilan
        original_text = query.message.text or query.message.caption

        # Mijoz ma'lumotlari
        customer_phone = order.customer_phone or "Ko'rsatilmagan"
        customer_address = order.customer_address or "Ko'rsatilmagan"

        new_text = f"""
{original_text}

━━━━━━━━━━━━━━━━━━━━
✅ <b>QABUL QILINDI</b>

👤 <b>Mijoz ma'lumotlari:</b>
📞 Telefon: <code>{customer_phone}</code>
📍 Manzil: {customer_address}

🧑‍💼 Operator: {user.full_name}
🕐 Vaqt: {timezone.now().strftime('%H:%M %d.%m.%Y')}
        """

        # Yangi tugmalar - WhatsApp va telefon
        phone_clean = customer_phone.replace('+', '').replace(' ', '').replace('-', '')
        keyboard = [
            [
                InlineKeyboardButton("📱 WhatsApp", url=f"https://wa.me/{phone_clean}"),
                InlineKeyboardButton("📊 Status", callback_data=f"status_{order_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            await query.edit_message_text(
                text=new_text.strip(),
                parse_mode='HTML',
                reply_markup=reply_markup
            )
        except TelegramError:
            # Agar xabar o'zgartirib bo'lmasa, yangi xabar yuborish
            await query.message.reply_text(
                f"✅ Buyurtma #{order_id} qabul qilindi!\n"
                f"👤 Operator: {user.full_name}",
                parse_mode='HTML'
            )

        # External API ga xabar berish
        await notify_external_api(order_id, 'accepted', user.full_name)

        logger.info(f"Order {order_id} accepted by {user.id}")

    except Order.DoesNotExist:
        await query.answer("❌ Buyurtma topilmadi!", show_alert=True)
    except Exception as e:
        logger.error(f"Error accepting order {order_id}: {e}")
        await query.answer(f"❌ Xatolik: {str(e)}", show_alert=True)


async def reject_order(query, order_id: str, user):
    """
    Buyurtmani rad etish
    """
    from .models import Order

    await query.answer()

    try:
        order = await sync_to_async(
            lambda: Order.objects.select_related('seller').get(external_id=order_id)
        )()

        # Status tekshirish
        if order.status not in ['new', 'accepted']:
            await query.answer(
                f"⚠️ Buyurtma {order.status_display} holatida, rad etib bo'lmaydi!",
                show_alert=True
            )
            return

        # Yangilash
        old_status = order.status
        order.status = 'rejected'
        order.accepted_by = f"{user.full_name} ({user.id})"
        await sync_to_async(order.save)()

        # Xabarni yangilash
        original_text = query.message.text or query.message.caption
        new_text = f"""
{original_text}

━━━━━━━━━━━━━━━━━━━━
❌ <b>RAD ETILDI</b>

👤 Operator: {user.full_name}
🕐 Vaqt: {timezone.now().strftime('%H:%M %d.%m.%Y')}
        """

        try:
            await query.edit_message_text(
                text=new_text.strip(),
                parse_mode='HTML',
                reply_markup=None  # Tugmalarni o'chirish
            )
        except TelegramError:
            await query.message.reply_text(
                f"❌ Buyurtma #{order_id} rad etildi!\n"
                f"👤 Operator: {user.full_name}",
                parse_mode='HTML'
            )

        # External API ga xabar berish
        await notify_external_api(order_id, 'rejected', user.full_name)

        logger.info(f"Order {order_id} rejected by {user.id}")

    except Order.DoesNotExist:
        await query.answer("❌ Buyurtma topilmadi!", show_alert=True)
    except Exception as e:
        logger.error(f"Error rejecting order {order_id}: {e}")
        await query.answer(f"❌ Xatolik: {str(e)}", show_alert=True)


async def show_call_info(query, order_id: str):
    """
    Mijoz telefon raqamini ko'rsatish
    """
    from .models import Order

    try:
        order = await sync_to_async(
            lambda: Order.objects.get(external_id=order_id)
        )()

        phone = order.customer_phone
        name = order.customer_name

        await query.answer()

        keyboard = [
            [
                InlineKeyboardButton(
                    f"📞 {phone}",
                    url=f"tel:{phone}"
                )
            ],
            [
                InlineKeyboardButton(
                    "📱 WhatsApp",
                    url=f"https://wa.me/{phone.replace('+', '').replace(' ', '')}"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 Orqaga",
                    callback_data=f"details_{order_id}"
                )
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.message.reply_text(
            f"📞 <b>Mijoz bilan bog'lanish</b>\n\n"
            f"👤 Ism: {name}\n"
            f"📱 Telefon: <code>{phone}</code>\n\n"
            f"<i>Telefon raqamini bosing yoki nusxa oling.</i>",
            parse_mode='HTML',
            reply_markup=reply_markup
        )

    except Order.DoesNotExist:
        await query.answer("❌ Buyurtma topilmadi!", show_alert=True)


async def show_order_details(query, order_id: str):
    """
    Buyurtma tafsilotlarini ko'rsatish
    """
    from .models import Order

    try:
        order = await sync_to_async(
            lambda: Order.objects.select_related('seller').get(external_id=order_id)
        )()

        await query.answer()

        # Mahsulotlar ro'yxati
        items_text = ""
        total_qty = 0
        for item in order.items:
            name = item.get('name', 'Nomalum')
            qty = item.get('quantity', 1)
            price = item.get('price', 0)
            total_qty += qty

            items_text += f"  - {name}\n"
            items_text += f"    {qty} x {price:,.0f} = {qty * price:,.0f} som\n"

        address_text = order.customer_address if order.customer_address else 'Korsatilmagan'
        notes_text = order.notes if order.notes else 'Yoq'

        message = f"""
📋 <b>BUYURTMA TAFSILOTLARI</b>

🆔 Buyurtma: #{order.external_id}
{order.status_emoji} Status: <b>{order.status_display}</b>

👤 <b>Mijoz:</b>
   Ism: {order.customer_name}
   Tel: <code>{order.customer_phone}</code>
   Manzil: {address_text}

📦 <b>Mahsulotlar ({total_qty} ta):</b>
{items_text}
💰 <b>Jami:</b> {order.total_amount:,.0f} som

📝 <b>Izoh:</b> {notes_text}

🕐 Yaratilgan: {order.created_at.strftime('%H:%M %d.%m.%Y')}
🔄 Yangilangan: {order.updated_at.strftime('%H:%M %d.%m.%Y')}
        """

        if order.accepted_by:
            message += f"\n👤 Operator: {order.accepted_by}"

        keyboard = [
            [
                InlineKeyboardButton("📞 Qo'ng'iroq", callback_data=f"call_{order_id}"),
                InlineKeyboardButton("📊 Status", callback_data=f"status_{order_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.message.reply_text(
            message.strip(),
            parse_mode='HTML',
            reply_markup=reply_markup
        )

    except Order.DoesNotExist:
        await query.answer("❌ Buyurtma topilmadi!", show_alert=True)


async def show_status_options(query, order_id: str):
    """
    Status o'zgartirish variantlarini ko'rsatish
    """
    from .models import Order

    await query.answer()

    try:
        order = await sync_to_async(
            lambda: Order.objects.get(external_id=order_id)
        )()

        current_status = order.status

        # Mumkin bo'lgan statuslar
        statuses = [
            ('processing', '⏳ Jarayonda'),
            ('shipped', '🚚 Yetkazilmoqda'),
            ('delivered', '📦 Yetkazildi'),
            ('completed', '🎉 Yakunlandi'),
            ('cancelled', '🚫 Bekor qilindi'),
        ]

        keyboard = []
        for status_value, status_label in statuses:
            if status_value != current_status:
                keyboard.append([
                    InlineKeyboardButton(
                        status_label,
                        callback_data=f"setstatus_{order_id}_{status_value}"
                    )
                ])

        keyboard.append([
            InlineKeyboardButton("🔙 Orqaga", callback_data=f"details_{order_id}")
        ])

        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.message.reply_text(
            f"📊 <b>Buyurtma #{order_id} statusini o'zgartirish</b>\n\n"
            f"Hozirgi status: {order.status_emoji} <b>{order.status_display}</b>\n\n"
            f"Yangi statusni tanlang:",
            parse_mode='HTML',
            reply_markup=reply_markup
        )

    except Order.DoesNotExist:
        await query.answer("❌ Buyurtma topilmadi!", show_alert=True)


async def update_order_status(query, order_id: str, new_status: str, user):
    """
    Buyurtma statusini yangilash
    """
    from .models import Order

    await query.answer()

    try:
        order = await sync_to_async(
            lambda: Order.objects.select_related('seller').get(external_id=order_id)
        )()

        old_status = order.status
        order.status = new_status
        await sync_to_async(order.save)()

        # Status emoji olish
        emoji_map = {
            'processing': '⏳',
            'shipped': '🚚',
            'delivered': '📦',
            'completed': '🎉',
            'cancelled': '🚫',
        }
        emoji = emoji_map.get(new_status, '📊')

        await query.message.reply_text(
            f"{emoji} <b>Status yangilandi!</b>\n\n"
            f"🆔 Buyurtma: #{order_id}\n"
            f"📊 Yangi status: <b>{new_status}</b>\n"
            f"👤 Operator: {user.full_name}\n"
            f"🕐 Vaqt: {timezone.now().strftime('%H:%M')}",
            parse_mode='HTML'
        )

        # External API ga xabar berish
        await notify_external_api(order_id, new_status, user.full_name)

        logger.info(f"Order {order_id} status changed to {new_status} by {user.id}")

    except Order.DoesNotExist:
        await query.answer("❌ Buyurtma topilmadi!", show_alert=True)
    except Exception as e:
        logger.error(f"Error updating order status: {e}")
        await query.answer(f"❌ Xatolik: {str(e)}", show_alert=True)


async def notify_external_api(order_id: str, status: str, operator: str = ""):
    """
    External API ga buyurtma statusi haqida xabar berish
    """
    api_url = os.getenv('EXTERNAL_API_URL')
    api_key = os.getenv('EXTERNAL_API_KEY')

    if not api_url or not api_key:
        logger.debug("External API not configured, skipping notification")
        return

    # API endpoint - bu sizning API'ingizga mos kelishi kerak
    endpoint = f"{api_url.rstrip('/')}/orders/{order_id}/status"

    try:
        response = requests.post(
            endpoint,
            json={
                "status": status,
                "operator": operator,
                "updated_at": datetime.now().isoformat()
            },
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            timeout=5
        )

        if response.status_code == 200:
            logger.info(f"External API notified: order={order_id}, status={status}")
        else:
            logger.warning(
                f"External API returned {response.status_code}: {response.text[:200]}"
            )

    except requests.Timeout:
        logger.warning(f"External API timeout for order {order_id}")
    except requests.RequestException as e:
        logger.error(f"External API error: {e}")
    except Exception as e:
        logger.error(f"Unexpected error notifying external API: {e}")
