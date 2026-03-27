import os
import re
import logging
import time
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ContextTypes
from .otp_manager import OTPManager, AdminOTPMonitor

logger = logging.getLogger(__name__)

# OTP Manager instance
otp_manager = OTPManager()

# Global dictionary - chat_data o'rniga (context.chat_data har safar yo'qoladi)
PENDING_REGISTRATIONS = {}


async def is_admin(user_id: int) -> bool:
    """Admin tekshirish - Telegram ID yoki telefon raqam orqali"""
    from .models import PhoneRegistry

    # 1. Telegram ID bo'yicha tekshirish
    admin_ids = os.getenv('ADMIN_IDS', '').split(',')
    if str(user_id) in admin_ids:
        return True

    # 2. Telefon raqam bo'yicha tekshirish
    allowed_phones = os.getenv('ALLOWED_PHONES', '').split(',')
    allowed_phones = [p.strip() for p in allowed_phones if p.strip()]

    if allowed_phones:
        # Foydalanuvchining ro'yxatdan o'tgan telefon raqamini tekshirish
        phone_registry = PhoneRegistry.get_by_telegram_id(str(user_id))
        if phone_registry and phone_registry.phone in allowed_phones:
            return True

    return False


async def is_seller(user_id: int):
    """Foydalanuvchi seller ekanligini tekshirish - telefon raqam orqali.
    Agar seller bo'lsa, Seller obyektini qaytaradi, aks holda None."""
    from .models import PhoneRegistry, Seller

    phone_registry = PhoneRegistry.get_by_telegram_id(str(user_id))
    if phone_registry:
        seller = Seller.get(phone=phone_registry.phone, is_active=True)
        if seller:
            return seller

    # Telegram user ID orqali ham tekshirish
    sellers = Seller.filter(is_active=True)
    for seller in sellers:
        if seller.telegram_user_id == str(user_id):
            return seller

    return None


async def is_allowed_user(user_id: int) -> bool:
    """Admin yoki seller ekanligini tekshirish"""
    if await is_admin(user_id):
        return True
    seller = await is_seller(user_id)
    return seller is not None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from .models import PhoneRegistry, Seller

    user = update.effective_user
    chat = update.effective_chat

    logger.info(f"START command: user_id={user.id}, chat_type={chat.type}")

    # Guruhdan /start bosilganda - sotuvchi ro'yxatdan o'tishi
    if chat.type in ['group', 'supergroup']:
        await handle_group_start(update, context)
        return

    # Deep link tekshirish - manage_{seller_id}
    if context.args and len(context.args) > 0:
        arg = context.args[0]
        if arg.startswith("manage_"):
            seller_id = arg.replace("manage_", "")
            await show_seller_management_panel(update, context, seller_id)
            return

    # Shaxsiy chatda
    # Adminlar uchun admin panel
    is_admin_user = await is_admin(user.id)
    logger.info(f"is_admin_user: {is_admin_user}")

    if is_admin_user:
        keyboard = [
            [InlineKeyboardButton("📊 Statistika", callback_data="admin_stats")],
            [InlineKeyboardButton("📋 Sotuvchilar ro'yxati", callback_data="admin_sellers")],
            [InlineKeyboardButton("🔍 Buyurtma qidirish", callback_data="admin_search")],
            [InlineKeyboardButton("🧪 Test buyurtma", callback_data="admin_test")],
            [InlineKeyboardButton("📢 Xabarnoma yuborish", callback_data="admin_notify")]
        ]
        message = (
            f"👨‍💼 <b>ADMIN PANEL</b>\n\n"
            f"Salom, <b>{user.first_name}</b>!\n\n"
            f"🤖 Nonbor Buyurtmalar Bot - bizneslar uchun buyurtma notification tizimi.\n\n"
            f"Quyidagi tugmalardan foydalaning:"
        )
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='HTML')
        return

    # Oddiy foydalanuvchi uchun - telefon raqam so'rash
    # Avval ro'yxatdan o'tganmi tekshirish
    existing = PhoneRegistry.get_by_telegram_id(str(user.id))
    logger.info(f"PhoneRegistry check: user_id={user.id}, existing={existing}")

    if existing:
        logger.info(f"Found registration: phone={existing.phone}")
        # Allaqachon ro'yxatdan o'tgan - ulangan guruhni tekshirish
        from .models import Seller
        my_seller = Seller.get(phone=existing.phone, is_active=True)

        keyboard = []

        if my_seller and my_seller.group_chat_id:
            # Guruh ulangan - dashboard tugmalarini ko'rsatish
            keyboard.append([
                InlineKeyboardButton("📊 Statistika", callback_data=f"seller_stats_{my_seller.id}"),
                InlineKeyboardButton("👥 Xodimlar", callback_data=f"seller_staff_{my_seller.id}")
            ])
            keyboard.append([InlineKeyboardButton("📝 Raqamni o'zgartirish", callback_data="change_phone")])

            await update.message.reply_text(
                f"👋 <b>Xush kelibsiz!</b>\n\n"
                f"🏪 <b>Biznes:</b> {my_seller.full_name}\n"
                f"📞 <b>Telefon:</b> {existing.phone}\n"
                f"👥 <b>Guruh:</b> {my_seller.group_title or 'Ulangan'}\n\n"
                f"Quyidagi tugmalardan foydalaning:",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            # Guruh ulanmagan
            keyboard.append([InlineKeyboardButton("📝 Raqamni o'zgartirish", callback_data="change_phone")])
            await update.message.reply_text(
                f"👋 <b>Xush kelibsiz!</b>\n\n"
                f"Siz allaqachon ro'yxatdan o'tgansiz.\n\n"
                f"📞 <b>Telefon:</b> {existing.phone}\n\n"
                f"Agar guruhingizni ulash kerak bo'lsa:\n"
                f"1️⃣ Guruh yarating va botni qo'shing\n"
                f"2️⃣ Guruhda /start bosing\n"
                f"3️⃣ Telefon raqamingizni yuboring\n"
                f"4️⃣ OTP kodi shu chatga keladi",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    else:
        # Yangi foydalanuvchi - telefon so'rash
        # Context ga kutish holatini saqlash
        context.user_data['waiting_phone_registration'] = True

        await update.message.reply_text(
            f"👋 <b>Salom, {user.first_name}!</b>\n\n"
            f"Bu bot orqali guruhingizni Nonbor buyurtma tizimiga ulashingiz mumkin.\n\n"
            f"📱 <b>Ro'yxatdan o'tish uchun Nonbor platformasida ro'yxatdan o'tgan telefon raqamingizni yuboring:</b>\n\n"
            f"<i>Masalan: +998901234567</i>",
            parse_mode='HTML'
        )


async def show_seller_management_panel(update: Update, context: ContextTypes.DEFAULT_TYPE, seller_id: str):
    """Sotuvchi uchun boshqaruv panelini ko'rsatish (faqat shaxsiy chatda)"""
    from .models import Seller, PhoneRegistry

    user = update.effective_user

    # Sotuvchini topish
    seller = Seller.get(id=seller_id)
    if not seller:
        await update.message.reply_text(
            "❌ Biznes topilmadi.",
            parse_mode='HTML'
        )
        return

    # Foydalanuvchi biznes egasimi tekshirish
    is_owner = False

    # 1. Telefon orqali tekshirish
    phone_registry = PhoneRegistry.get_by_telegram_id(str(user.id))
    if phone_registry and phone_registry.phone == seller.phone:
        is_owner = True

    # 2. Telegram user ID orqali tekshirish
    if seller.telegram_user_id == str(user.id):
        is_owner = True

    if not is_owner:
        await update.message.reply_text(
            "⛔ Siz bu biznesning egasi emassiz.",
            parse_mode='HTML'
        )
        return

    # Boshqaruv tugmalarini ko'rsatish
    keyboard = [
        [
            InlineKeyboardButton("📊 Statistika", callback_data=f"seller_stats_{seller.id}"),
            InlineKeyboardButton("👥 Xodimlar", callback_data=f"seller_staff_{seller.id}")
        ],
        [
            InlineKeyboardButton("⚙️ Sozlamalar", callback_data=f"seller_settings_{seller.id}")
        ]
    ]

    await update.message.reply_text(
        f"🔐 <b>Boshqaruv paneli</b>\n\n"
        f"🏪 <b>Biznes:</b> {seller.full_name}\n"
        f"📞 <b>Telefon:</b> {seller.phone}\n"
        f"👥 <b>Guruh:</b> {seller.group_title or 'Ulanmagan'}\n\n"
        f"Quyidagi tugmalardan foydalaning:",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def handle_group_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Guruhdan /start bosilganda - sotuvchi ro'yxatdan o'tishi"""
    from .models import Seller, PhoneRegistry

    chat = update.effective_chat
    user = update.effective_user

    # Bu guruh allaqachon ulangan bo'lsa
    sellers = Seller.filter(is_active=True)
    for seller in sellers:
        if seller.group_chat_id == str(chat.id):
            # Biznes egasimi tekshirish
            is_owner = False

            # 1. Telefon orqali tekshirish
            phone_registry = PhoneRegistry.get_by_telegram_id(str(user.id))
            if phone_registry and phone_registry.phone == seller.phone:
                is_owner = True

            # 2. Telegram user ID orqali tekshirish
            if seller.telegram_user_id == str(user.id):
                is_owner = True

            if is_owner:
                # Biznes egasi - boshqaruv paneli uchun botga yo'naltirish
                bot_info = await context.bot.get_me()
                bot_username = bot_info.username

                keyboard = [
                    [
                        InlineKeyboardButton(
                            "🔐 Boshqaruv paneli",
                            url=f"https://t.me/{bot_username}?start=manage_{seller.id}"
                        )
                    ]
                ]

                await update.message.reply_text(
                    f"👋 <b>Xush kelibsiz, {user.first_name}!</b>\n\n"
                    f"🏪 <b>Biznes:</b> {seller.full_name}\n"
                    f"📞 <b>Telefon:</b> {seller.phone}\n"
                    f"👥 <b>Guruh:</b> {chat.title}\n\n"
                    f"📊 Statistika, xodimlar va sozlamalarni ko'rish uchun quyidagi tugmani bosing:",
                    parse_mode='HTML',
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                # Oddiy a'zo
                await update.message.reply_text(
                    f"✅ Bu guruh <b>{seller.full_name}</b> ga ulangan.\n\n"
                    f"Buyurtmalar shu guruhga keladi.",
                    parse_mode='HTML'
                )
            return

    # Guruh ma'lumotlarini GLOBAL dictionary'ga saqlash
    chat_id = str(chat.id)
    PENDING_REGISTRATIONS[chat_id] = {
        'pending_group_id': chat_id,
        'pending_group_title': chat.title,
        'waiting_phone': True,
        'user_id': user.id
    }

    logger.info(f"Group {chat_id} started registration, saved to PENDING_REGISTRATIONS")

    await update.message.reply_text(
        f"👋 <b>Xush kelibsiz!</b>\n\n"
        f"👥 Guruh: <b>{chat.title}</b>\n\n"
        f"Buyurtmalarni qabul qilish uchun ro'yxatdan o'ting.\n\n"
        f"📱 Iltimos, <b>Nonbor platformasida ro'yxatdan o'tgan</b> telefon raqamingizni yuboring:\n\n"
        f"<i>Masalan: +998901234567</i>",
        parse_mode='HTML'
    )


async def add_seller(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if not await is_admin(user.id):
        return

    args = context.args

    if len(args) < 2:
        await update.message.reply_text(
            "➕ <b>Sotuvchi qo'shish</b>\n\n"
            "📝 <b>Format:</b>\n"
            "<code>/add_seller +998XXXXXXXXX Ism Familya</code>\n\n"
            "📌 <b>Misol:</b>\n"
            "<code>/add_seller +998901234567 Ali Valiyev</code>",
            parse_mode='HTML'
        )
        return

    phone = args[0]
    full_name = ' '.join(args[1:])

    if not re.match(r'^\+998\d{9}$', phone):
        await update.message.reply_text(
            "❌ <b>Noto'g'ri telefon formati!</b>\n\n"
            "✅ To'g'ri format: <code>+998901234567</code>",
            parse_mode='HTML'
        )
        return

    from .models import Seller

    existing = Seller.get(phone=phone)
    if existing:
        await update.message.reply_text(
            f"⚠️ <b>Bu telefon allaqachon mavjud!</b>\n\n"
            f"👤 Sotuvchi: {existing.full_name}\n"
            f"🆔 ID: <code>{existing.id}</code>",
            parse_mode='HTML'
        )
        return

    seller = Seller(
        phone=phone,
        full_name=full_name,
        telegram_user_id=str(user.id),
        group_chat_id="",
        is_active=True
    )
    seller.save()

    await update.message.reply_text(
        f"✅ <b>Sotuvchi muvaffaqiyatli qo'shildi!</b>\n\n"
        f"👤 <b>Ism:</b> {full_name}\n"
        f"📞 <b>Telefon:</b> {phone}\n"
        f"🆔 <b>ID:</b> <code>{seller.id}</code>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 <b>Keyingi qadam:</b>\n"
        f"Guruh chat ID qo'shish:\n"
        f"<code>/set_group {seller.id} CHAT_ID</code>\n\n"
        f"💡 Chat ID olish uchun guruhda /get_chat_id yozing",
        parse_mode='HTML'
    )


async def set_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        return

    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "🔗 <b>Guruh ulash</b>\n\n"
            "📝 <b>Format:</b>\n"
            "<code>/set_group SELLER_ID CHAT_ID</code>\n\n"
            "📌 <b>Misol:</b>\n"
            "<code>/set_group abc-123 -1001234567890</code>\n\n"
            "💡 Chat ID olish uchun guruhda /get_chat_id yozing",
            parse_mode='HTML'
        )
        return

    seller_id = args[0]
    chat_id = args[1]

    from .models import Seller
    seller = Seller.get(id=seller_id)

    if not seller:
        await update.message.reply_text("❌ Sotuvchi topilmadi!")
        return

    seller.group_chat_id = chat_id
    seller.save()

    await update.message.reply_text(
        f"✅ <b>Guruh muvaffaqiyatli ulandi!</b>\n\n"
        f"👤 <b>Sotuvchi:</b> {seller.full_name}\n"
        f"👥 <b>Guruh ID:</b> <code>{chat_id}</code>\n\n"
        f"🧪 Test qilish: <code>/test_order {seller.id}</code>",
        parse_mode='HTML'
    )


async def list_sellers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        return

    from .models import Seller
    sellers = Seller.filter(is_active=True)

    if not sellers:
        keyboard = [[InlineKeyboardButton("➕ Sotuvchi qo'shish", callback_data="menu_add_seller")]]
        await update.message.reply_text(
            "📭 <b>Hozircha sotuvchilar yo'q</b>\n\n"
            "Yangi sotuvchi qo'shish uchun tugmani bosing yoki:\n"
            "<code>/add_seller +998XXXXXXXXX Ism</code>",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    message = f"📋 <b>Faol sotuvchilar</b> ({len(sellers)} ta)\n\n"

    for i, seller in enumerate(sellers, 1):
        status = "✅" if seller.group_chat_id else "⚠️"
        message += f"{status} <b>{i}. {seller.full_name}</b>\n"
        message += f"    📞 {seller.phone}\n"
        if hasattr(seller, 'address') and seller.address:
            message += f"    📍 {seller.address}\n"
        message += f"    🆔 <code>{seller.id[:8]}...</code>\n"
        if seller.group_chat_id:
            message += f"    👥 Guruh ulangan\n"
        else:
            message += f"    ⚠️ <i>Guruh ulanmagan</i>\n"
        message += "\n"

    message += "━━━━━━━━━━━━━━━━━━━━\n"
    message += "✅ - Guruh ulangan | ⚠️ - Guruh ulanmagan"

    await update.message.reply_text(message, parse_mode='HTML')


async def delete_seller(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            "🗑 <b>Sotuvchini o'chirish</b>\n\n"
            "📝 <b>Format:</b>\n"
            "<code>/delete_seller SELLER_ID</code>\n\n"
            "💡 ID ni /list_sellers orqali olishingiz mumkin",
            parse_mode='HTML'
        )
        return

    seller_id = args[0]

    from .models import Seller
    seller = Seller.get(id=seller_id)

    if not seller:
        await update.message.reply_text("❌ Sotuvchi topilmadi!")
        return

    seller.is_active = False
    seller.save()

    await update.message.reply_text(
        f"🗑 <b>Sotuvchi o'chirildi</b>\n\n"
        f"👤 {seller.full_name}\n"
        f"📞 {seller.phone}",
        parse_mode='HTML'
    )


async def test_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        return

    args = context.args

    from .models import Seller

    if len(args) < 1:
        sellers = Seller.filter(is_active=True)
        if not sellers:
            await update.message.reply_text(
                "❌ <b>Faol sotuvchi yo'q!</b>\n\n"
                "Avval sotuvchi qo'shing:\n"
                "<code>/add_seller +998XXXXXXXXX Ism</code>",
                parse_mode='HTML'
            )
            return
        seller = sellers[0]
    else:
        seller_id = args[0]
        seller = Seller.get(id=seller_id, is_active=True)
        if not seller:
            await update.message.reply_text("❌ Sotuvchi topilmadi yoki faol emas!")
            return

    if not seller.group_chat_id:
        await update.message.reply_text(
            f"⚠️ <b>{seller.full_name}</b> uchun guruh ulanmagan!\n\n"
            f"Guruh ulash:\n"
            f"<code>/set_group {seller.id} CHAT_ID</code>",
            parse_mode='HTML'
        )
        return

    # Yuborish jarayoni haqida xabar
    status_msg = await update.message.reply_text("⏳ Test buyurtma yuborilmoqda...")

    test_order_data = {
        "id": f"TEST-{int(time.time())}",
        "seller_id": seller.id,
        "status": "new",
        "customer": {
            "name": "Test Mijoz",
            "phone": "+998901112233"
        },
        "total": 150000,
        "items": [
            {"name": "Pizza Margarita", "price": 65000, "quantity": 1},
            {"name": "Coca-Cola 1L", "price": 15000, "quantity": 2},
            {"name": "Lavash", "price": 55000, "quantity": 1}
        ],
        "created_at": datetime.now().isoformat()
    }

    from .core import NotificationBot
    bot = NotificationBot()
    success = await bot.send_order_notification(test_order_data)

    if success:
        await status_msg.edit_text(
            f"✅ <b>Test buyurtma yuborildi!</b>\n\n"
            f"👤 Sotuvchi: {seller.full_name}\n"
            f"📦 Buyurtma: #{test_order_data['id']}\n"
            f"💰 Summa: {test_order_data['total']:,} so'm",
            parse_mode='HTML'
        )
    else:
        await status_msg.edit_text(
            "❌ <b>Xatolik!</b>\n\n"
            "Test buyurtma yuborishda muammo yuz berdi.\n"
            "Guruh ID to'g'riligini tekshiring.",
            parse_mode='HTML'
        )


async def get_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    chat_types = {
        'private': '👤 Shaxsiy chat',
        'group': '👥 Guruh',
        'supergroup': '👥 Superguruh',
        'channel': '📢 Kanal'
    }

    await update.message.reply_text(
        f"📍 <b>Chat ma'lumotlari</b>\n\n"
        f"🆔 <b>Chat ID:</b> <code>{chat.id}</code>\n"
        f"📝 <b>Turi:</b> {chat_types.get(chat.type, chat.type)}\n"
        f"📛 <b>Nomi:</b> {chat.title or chat.first_name or 'N/A'}\n\n"
        f"👤 <b>Sizning ID:</b> <code>{user.id}</code>",
        parse_mode='HTML'
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        return

    await update.message.reply_text(
        "📚 <b>Yordam - Barcha buyruqlar</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "👥 <b>Sotuvchilar boshqaruvi:</b>\n\n"
        "➕ /add_seller <code>+998XX XXXXXX Ism</code>\n"
        "    <i>Yangi sotuvchi qo'shish</i>\n\n"
        "📋 /list_sellers\n"
        "    <i>Barcha sotuvchilar ro'yxati</i>\n\n"
        "🔗 /set_group <code>ID CHAT_ID</code>\n"
        "    <i>Sotuvchiga guruh ulash</i>\n\n"
        "🗑 /delete_seller <code>ID</code>\n"
        "    <i>Sotuvchini o'chirish</i>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🧪 <b>Test va ma'lumot:</b>\n\n"
        "🧪 /test_order <code>[ID]</code>\n"
        "    <i>Test buyurtma yuborish</i>\n\n"
        "📍 /get_chat_id\n"
        "    <i>Joriy chat ID ni olish</i>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "💡 <b>Maslahat:</b> Guruhga botni qo'shib, /get_chat_id yozing",
        parse_mode='HTML'
    )


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        return

    from .models import Seller, Order

    sellers = Seller.filter(is_active=True)
    all_orders = Order.load_all()

    # Vaqt filtrlash
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    year_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)

    def filter_orders_by_date(orders, start_date):
        filtered = []
        for o in orders:
            created = o.get('created_at', '')
            if created:
                try:
                    order_date = datetime.fromisoformat(created.replace('Z', '+00:00'))
                    if order_date.replace(tzinfo=None) >= start_date:
                        filtered.append(o)
                except:
                    pass
        return filtered

    daily_orders = filter_orders_by_date(all_orders, today_start)
    monthly_orders = filter_orders_by_date(all_orders, month_start)
    yearly_orders = filter_orders_by_date(all_orders, year_start)

    total_sellers = len(sellers)
    connected_sellers = len([s for s in sellers if s.group_chat_id])

    # Kunlik statistika
    daily_total = len(daily_orders)
    daily_accepted = len([o for o in daily_orders if o.get('status') == 'accepted'])
    daily_amount = sum(o.get('total_amount', 0) for o in daily_orders)

    # Oylik statistika
    monthly_total = len(monthly_orders)
    monthly_accepted = len([o for o in monthly_orders if o.get('status') == 'accepted'])
    monthly_amount = sum(o.get('total_amount', 0) for o in monthly_orders)

    # Yillik statistika
    yearly_total = len(yearly_orders)
    yearly_accepted = len([o for o in yearly_orders if o.get('status') == 'accepted'])
    yearly_amount = sum(o.get('total_amount', 0) for o in yearly_orders)

    # Tugmalar
    keyboard = [
        [
            InlineKeyboardButton("📅 Kunlik", callback_data="stats_daily"),
            InlineKeyboardButton("📆 Oylik", callback_data="stats_monthly"),
        ],
        [
            InlineKeyboardButton("📊 Yillik", callback_data="stats_yearly"),
            InlineKeyboardButton("📋 Barchasi", callback_data="stats_all"),
        ]
    ]

    await update.message.reply_text(
        "📊 <b>Statistika</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "👥 <b>Sotuvchilar:</b>\n"
        f"    Jami: {total_sellers} ta\n"
        f"    Guruh ulangan: {connected_sellers} ta\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📅 <b>Bugungi:</b>\n"
        f"    Buyurtmalar: {daily_total} ta\n"
        f"    ✅ Qabul: {daily_accepted} ta\n"
        f"    💰 Summa: {daily_amount:,.0f} so'm\n\n".replace(",", " ") +
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📆 <b>Oylik:</b>\n"
        f"    Buyurtmalar: {monthly_total} ta\n"
        f"    ✅ Qabul: {monthly_accepted} ta\n"
        f"    💰 Summa: {monthly_amount:,.0f} so'm\n\n".replace(",", " ") +
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📊 <b>Yillik:</b>\n"
        f"    Buyurtmalar: {yearly_total} ta\n"
        f"    ✅ Qabul: {yearly_accepted} ta\n"
        f"    💰 Summa: {yearly_amount:,.0f} so'm".replace(",", " "),
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def handle_group_id_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Guruh ID xabarini qabul qilish"""
    if not await is_admin(update.effective_user.id):
        return False

    # Tekshirish: foydalanuvchi guruh ID kutayaptimi?
    seller_id = context.user_data.get('waiting_group_id')
    if not seller_id:
        return False

    text = update.message.text.strip()

    # Guruh ID formatini tekshirish (odatda manfiy raqam)
    if not text.lstrip('-').isdigit():
        await update.message.reply_text(
            "❌ <b>Noto'g'ri format!</b>\n\n"
            "Guruh ID raqam bo'lishi kerak.\n"
            "Masalan: <code>-1001234567890</code>",
            parse_mode='HTML'
        )
        return True

    from .models import Seller

    seller = Seller.get(id=seller_id)
    if not seller:
        await update.message.reply_text("❌ Sotuvchi topilmadi!")
        context.user_data.pop('waiting_group_id', None)
        return True

    # Guruh ID ni saqlash
    seller.group_chat_id = text

    # Guruh nomini olishga harakat qilish
    try:
        chat = await context.bot.get_chat(int(text))
        seller.group_title = chat.title or ""
        if chat.invite_link:
            seller.group_invite_link = chat.invite_link
    except Exception:
        pass  # Guruh nomi olinmasa ham davom etamiz

    seller.save()

    # Kutish holatini tozalash
    context.user_data.pop('waiting_group_id', None)

    keyboard = [
        [InlineKeyboardButton("🧪 Test xabar yuborish", callback_data=f"testorder_{seller.id}")],
        [InlineKeyboardButton("◀️ Ortga", callback_data="menu_back")]
    ]

    group_info = f"👥 <b>Guruh:</b> {seller.group_title}\n" if seller.group_title else ""

    await update.message.reply_text(
        f"✅ <b>Guruh muvaffaqiyatli ulandi!</b>\n\n"
        f"👤 <b>Sotuvchi:</b> {seller.full_name}\n"
        f"{group_info}"
        f"🆔 <b>Guruh ID:</b> <code>{text}</code>\n\n"
        f"Test buyurtma yuborish uchun tugmani bosing.",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return True


async def handle_new_phone_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Yangi telefon raqamini qabul qilish"""
    if not await is_admin(update.effective_user.id):
        return False

    # Tekshirish: foydalanuvchi yangi telefon kutayaptimi?
    seller_id = context.user_data.get('waiting_new_phone')
    if not seller_id:
        return False

    text = update.message.text.strip()

    # Telefon raqam formatini tekshirish
    import re
    phone_pattern = re.compile(r'^[\+]?[0-9]{9,15}$')
    clean_phone = re.sub(r'[\s\-\(\)]', '', text)

    if not phone_pattern.match(clean_phone):
        await update.message.reply_text(
            "❌ <b>Noto'g'ri format!</b>\n\n"
            "Telefon raqam to'g'ri formatda bo'lishi kerak.\n"
            "Masalan: <code>+998901234567</code>",
            parse_mode='HTML'
        )
        return True

    from .models import Seller

    seller = Seller.get(id=seller_id)
    if not seller:
        await update.message.reply_text("❌ Sotuvchi topilmadi!")
        context.user_data.pop('waiting_new_phone', None)
        return True

    old_phone = seller.phone
    seller.phone = clean_phone
    seller.save()

    # Kutish holatini tozalash
    context.user_data.pop('waiting_new_phone', None)

    keyboard = [
        [InlineKeyboardButton("◀️ Ortga", callback_data=f"setgroup_{seller.id}")]
    ]

    await update.message.reply_text(
        f"✅ <b>Telefon raqam o'zgartirildi!</b>\n\n"
        f"👤 <b>Sotuvchi:</b> {seller.full_name}\n"
        f"📞 <b>Eski raqam:</b> {old_phone}\n"
        f"📞 <b>Yangi raqam:</b> {clean_phone}",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return True


async def handle_group_phone_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Guruhdan telefon raqamini qabul qilish - sotuvchi ro'yxatdan o'tishi uchun"""
    import aiohttp
    import random
    from .models import Seller

    chat = update.effective_chat
    user = update.effective_user

    # Faqat guruhdan kelgan xabarlar
    if chat.type not in ['group', 'supergroup']:
        return False

    chat_id = str(chat.id)

    # GLOBAL dictionary'dan tekshirish
    registration = PENDING_REGISTRATIONS.get(chat_id, {})
    waiting_phone = registration.get('waiting_phone')

    logger.info(f"handle_group_phone_message: chat_id={chat_id}, registration={registration}")

    # Agar waiting_phone bo'lmasa, avval telefon raqam formatini tekshiramiz
    text = update.message.text.strip() if update.message.text else ""
    phone_pattern = re.compile(r'^[\+]?998[0-9]{9}$')
    clean_phone = re.sub(r'[\s\-\(\)]', '', text)

    # Agar + bilan boshlanmasa, qo'shish
    if clean_phone and not clean_phone.startswith('+'):
        clean_phone = '+' + clean_phone

    is_phone_number = phone_pattern.match(clean_phone) if clean_phone else False

    if not waiting_phone:
        # Agar telefon raqam yuborilgan bo'lsa, lekin /start bosilmagan bo'lsa
        if is_phone_number:
            await update.message.reply_text(
                f"⚠️ <b>Avval /start bosing!</b>\n\n"
                f"Ro'yxatdan o'tish uchun quyidagi ketma-ketlikda amal qiling:\n\n"
                f"1️⃣ Shu guruhda /start buyrug'ini yuboring\n"
                f"2️⃣ So'ng telefon raqamingizni yuboring\n\n"
                f"<i>Guruhda /start bosing va qaytadan urinib ko'ring.</i>",
                parse_mode='HTML'
            )
            return True
        return False

    # Telefon raqam formatini yuqorida tekshirib bo'ldik
    if not is_phone_number:
        return False  # Telefon raqam emas, boshqa xabar

    logger.info(f"Phone received: {clean_phone}")

    # Nonbor API'dan biznes ma'lumotlarini olish
    try:
        api_url = os.getenv('EXTERNAL_API_URL', 'https://test.nonbor.uz/api/v2/telegram_bot/get-order-for-courier/')

        found_business = None
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as response:
                if response.status == 200:
                    orders = await response.json()

                    # Bizneslarni yig'ish va telefon orqali qidirish
                    for order in orders:
                        business = order.get('business', {})
                        business_phone = business.get('phone', '')

                        # Telefon raqamni solishtirish
                        if business_phone:
                            clean_business_phone = re.sub(r'[\s\-\(\)]', '', business_phone)
                            if not clean_business_phone.startswith('+'):
                                clean_business_phone = '+' + clean_business_phone

                            if clean_business_phone == clean_phone:
                                found_business = {
                                    'name': business.get('title', 'Nomalum'),
                                    'phone': clean_phone,
                                    'address': business.get('address', '')
                                }
                                break

        # Agar API'dan topilmasa, sellers.json dan tekshirish
        if not found_business:
            sellers = Seller.load_all()
            for s in sellers:
                seller = Seller.from_dict(s)
                if seller.phone == clean_phone:
                    found_business = {
                        'name': seller.full_name,
                        'phone': clean_phone,
                        'seller_id': seller.id
                    }
                    break

        if found_business:
            from .models import PhoneRegistry

            # Telefon raqam egasini PhoneRegistry dan topish
            phone_owner = PhoneRegistry.get_by_phone(clean_phone)

            if not phone_owner:
                # Telefon raqam ro'yxatdan o'tmagan
                bot_username = (await context.bot.get_me()).username
                await update.message.reply_text(
                    f"✅ <b>Telefon raqam Nonbor da topildi!</b>\n\n"
                    f"🏪 <b>Biznes:</b> {found_business['name']}\n"
                    f"📞 <b>Telefon:</b> {clean_phone}\n\n"
                    f"⚠️ <b>Lekin bu telefon botda ro'yxatdan o'tmagan!</b>\n\n"
                    f"OTP kodni olish uchun avval telefon egasi @{bot_username} botiga "
                    f"shaxsiy chatda /start bosib, telefon raqamini ro'yxatdan o'tkazishi kerak.\n\n"
                    f"<b>Qadamlar:</b>\n"
                    f"1️⃣ Telefon egasi @{bot_username} ga o'tsin\n"
                    f"2️⃣ /start bossin\n"
                    f"3️⃣ Telefon raqamini yuborsin: <code>{clean_phone}</code>\n"
                    f"4️⃣ Keyin shu guruhda qaytadan telefon yuborsin",
                    parse_mode='HTML'
                )
                return True

            # OTP Manager orqali tasdiqlash kodi yaratish (rate limit bilan)
            success, message = await otp_manager.send_otp(clean_phone, phone_owner.telegram_user_id)

            if not success:
                # Rate limit yoki boshqa xato
                await update.message.reply_text(
                    f"⚠️ <b>Xato!</b>\n\n{message}",
                    parse_mode='HTML'
                )
                return True

            # Faol OTP ni olish (kod ni saqlash uchun)
            pending_otp = otp_manager.get_pending_otp(clean_phone)
            verification_code = pending_otp.otp_code if pending_otp else ''

            # GLOBAL dictionary'ga saqlash
            PENDING_REGISTRATIONS[chat_id] = {
                'verification_code': verification_code,
                'verified_phone': clean_phone,
                'business_name': found_business['name'],
                'pending_group_id': chat_id,
                'pending_group_title': chat.title,
                'user_id': user.id,
                'phone_owner_telegram_id': phone_owner.telegram_user_id,
                'waiting_phone': False,  # Endi kod kutamiz
                'waiting_code': True
            }

            if 'seller_id' in found_business:
                PENDING_REGISTRATIONS[chat_id]['seller_id'] = found_business['seller_id']

            logger.info(f"OTP created for phone {clean_phone}, sending to telegram_user_id: {phone_owner.telegram_user_id}")

            # OTP kodni telefon egasiga yuborish
            try:
                await context.bot.send_message(
                    chat_id=int(phone_owner.telegram_user_id),
                    text=f"🔐 <b>Tasdiqlash kodi</b>\n\n"
                         f"📞 Telefon: <code>{clean_phone}</code>\n"
                         f"🏪 Biznes: {found_business['name']}\n"
                         f"👥 Guruh: {chat.title}\n\n"
                         f"🔑 Kod: <code>{verification_code}</code>\n\n"
                         f"⏱ Kod 5 daqiqa amal qiladi.\n"
                         f"<i>Ushbu kodni guruhga yuboring.</i>",
                    parse_mode='HTML'
                )
                otp_sent = True
                logger.info(f"OTP sent to phone owner: {phone_owner.telegram_user_id}")
            except Exception as e:
                logger.error(f"Failed to send OTP to phone owner: {e}")
                otp_sent = False

            if otp_sent:
                # Guruhga javob
                owner_name = phone_owner.full_name or phone_owner.telegram_username or "telefon egasi"
                await update.message.reply_text(
                    f"✅ <b>Telefon raqam topildi!</b>\n\n"
                    f"🏪 <b>Biznes:</b> {found_business['name']}\n"
                    f"📞 <b>Telefon:</b> {clean_phone}\n\n"
                    f"📲 Tasdiqlash kodi <b>{owner_name}</b> ning shaxsiy chatiga yuborildi.\n"
                    f"⏱ Kod 5 daqiqa amal qiladi.\n\n"
                    f"🔐 Iltimos, <b>6 xonali kodni</b> shu yerga yozing:",
                    parse_mode='HTML'
                )
            else:
                bot_username = (await context.bot.get_me()).username
                await update.message.reply_text(
                    f"✅ <b>Telefon raqam topildi!</b>\n\n"
                    f"🏪 <b>Biznes:</b> {found_business['name']}\n"
                    f"📞 <b>Telefon:</b> {clean_phone}\n\n"
                    f"⚠️ Tasdiqlash kodini yuborishda xatolik.\n"
                    f"Telefon egasi @{bot_username} botiga /start bosib, qaytadan urinib ko'rsin.",
                    parse_mode='HTML'
                )
            return True

        else:
            # Ro'yxatda yo'q
            await update.message.reply_text(
                f"❌ <b>Telefon raqam topilmadi!</b>\n\n"
                f"📞 <code>{clean_phone}</code> raqami Nonbor platformasida ro'yxatdan o'tmagan.\n\n"
                f"Iltimos, avval Nonbor platformasida ro'yxatdan o'ting:\n"
                f"🌐 https://business.nonbor.uz/\n\n"
                f"Ro'yxatdan o'tgandan so'ng, qaytadan telefon raqamingizni yuboring.",
                parse_mode='HTML'
            )
            return True

    except Exception as e:
        logger.error(f"Error checking phone in Nonbor: {e}")
        await update.message.reply_text(
            "❌ Xatolik yuz berdi. Iltimos, keyinroq urinib ko'ring.",
            parse_mode='HTML'
        )
        return True

    return False


async def handle_verification_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tasdiqlash kodini tekshirish - OTP Manager bilan"""
    from .models import Seller
    import uuid

    chat = update.effective_chat
    user = update.effective_user

    # Faqat guruhdan
    if chat.type not in ['group', 'supergroup']:
        return False

    chat_id = str(chat.id)

    # GLOBAL dictionary'dan tekshirish
    registration = PENDING_REGISTRATIONS.get(chat_id, {})
    waiting_code = registration.get('waiting_code')
    verified_phone = registration.get('verified_phone')

    if not waiting_code or not verified_phone:
        return False

    text = update.message.text.strip()

    # 6 xonali raqam
    if not text.isdigit() or len(text) != 6:
        return False

    logger.info(f"Verification code received: {text} for phone {verified_phone}")

    # OTP Manager orqali tekshirish (urinishlar soni va muddati bilan)
    is_valid, message = otp_manager.verify_otp(verified_phone, text, str(user.id))

    if is_valid:
        # Kod to'g'ri - sotuvchini yaratish yoki yangilash
        seller_id = registration.get('seller_id')
        pending_group_id = registration.get('pending_group_id')
        pending_group_title = registration.get('pending_group_title')
        business_name = registration.get('business_name', 'Nomalum')

        # Mavjud sotuvchini topish yoki yangisini yaratish
        seller = None
        if seller_id:
            seller = Seller.get(id=seller_id)

        if not seller:
            # Yangi sotuvchi yaratish
            seller = Seller(
                id=str(uuid.uuid4())[:8],
                phone=verified_phone,
                full_name=business_name,
                telegram_user_id=str(user.id),
                group_chat_id=pending_group_id,
                group_title=pending_group_title or "",
                is_active=True
            )
        else:
            # Mavjud sotuvchini yangilash
            seller.group_chat_id = pending_group_id
            seller.group_title = pending_group_title or ""
            seller.telegram_user_id = str(user.id)

        # Invite link olish
        try:
            invite_link = await context.bot.export_chat_invite_link(int(pending_group_id))
            seller.group_invite_link = invite_link
        except Exception:
            pass

        seller.save()

        # GLOBAL dictionary'dan tozalash
        PENDING_REGISTRATIONS.pop(chat_id, None)

        logger.info(f"Seller registered: {seller.full_name} for group {pending_group_id}")

        await update.message.reply_text(
            f"🎉 <b>Tabriklaymiz!</b>\n\n"
            f"Ro'yxatdan muvaffaqiyatli o'tdingiz!\n\n"
            f"🏪 <b>Biznes:</b> {business_name}\n"
            f"📞 <b>Telefon:</b> {verified_phone}\n"
            f"👥 <b>Guruh:</b> {pending_group_title}\n\n"
            f"✅ Endi barcha buyurtmalar shu guruhga keladi!\n\n"
            f"<i>Buyurtmalarni qabul qilish yoki rad etish uchun tugmalardan foydalaning.</i>",
            parse_mode='HTML'
        )
        return True
    else:
        await update.message.reply_text(
            f"❌ <b>Xato!</b>\n\n{message}",
            parse_mode='HTML'
        )
        return True

    return False


# ==========================================
# OTP Admin Commands
# ==========================================

async def otp_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """OTP statistikasi - faqat adminlar uchun"""
    if not await is_admin(update.effective_user.id):
        return

    monitor = AdminOTPMonitor()
    stats_message = monitor.format_stats_message()

    keyboard = [
        [
            InlineKeyboardButton("🔄 Yangilash", callback_data="otp_refresh_stats"),
            InlineKeyboardButton("⚠️ Xavfsizlik", callback_data="otp_security")
        ],
        [InlineKeyboardButton("◀️ Ortga", callback_data="menu_back")]
    ]

    await update.message.reply_text(
        stats_message,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def otp_security(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """OTP xavfsizlik hisoboti - faqat adminlar uchun"""
    if not await is_admin(update.effective_user.id):
        return

    monitor = AdminOTPMonitor()
    report = monitor.format_security_report()

    keyboard = [
        [
            InlineKeyboardButton("📊 Statistika", callback_data="otp_stats"),
            InlineKeyboardButton("🔄 Yangilash", callback_data="otp_refresh_security")
        ],
        [InlineKeyboardButton("◀️ Ortga", callback_data="menu_back")]
    ]

    await update.message.reply_text(
        report,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def handle_otp_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """OTP callback handler"""
    query = update.callback_query
    await query.answer()

    if not await is_admin(query.from_user.id):
        return

    data = query.data
    monitor = AdminOTPMonitor()

    if data == "otp_refresh_stats" or data == "otp_stats":
        stats_message = monitor.format_stats_message()
        keyboard = [
            [
                InlineKeyboardButton("🔄 Yangilash", callback_data="otp_refresh_stats"),
                InlineKeyboardButton("⚠️ Xavfsizlik", callback_data="otp_security")
            ],
            [InlineKeyboardButton("◀️ Ortga", callback_data="menu_back")]
        ]
        await query.edit_message_text(
            stats_message,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data == "otp_refresh_security" or data == "otp_security":
        report = monitor.format_security_report()
        keyboard = [
            [
                InlineKeyboardButton("📊 Statistika", callback_data="otp_stats"),
                InlineKeyboardButton("🔄 Yangilash", callback_data="otp_refresh_security")
            ],
            [InlineKeyboardButton("◀️ Ortga", callback_data="menu_back")]
        ]
        await query.edit_message_text(
            report,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


async def handle_private_otp_verification(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Private chatda OTP tekshirish - boshqa raqamdan kirishga uringan foydalanuvchi uchun.
    Agar foydalanuvchi boshqa biznes raqamini kiritgan bo'lsa va OTP kodi yuborilgan bo'lsa,
    bu handler OTP kodni tekshiradi va ro'yxatdan o'tkazadi.
    """
    from .models import PhoneRegistry, Seller

    chat = update.effective_chat
    user = update.effective_user

    # Faqat shaxsiy chatda
    if chat.type != 'private':
        return False

    # OTP kutilayaptimi tekshirish
    waiting_phone = context.user_data.get('waiting_private_otp_phone')
    if not waiting_phone:
        return False

    text = update.message.text.strip() if update.message.text else ""

    # 6 xonali raqam
    if not text.isdigit() or len(text) != 6:
        return False

    logger.info(f"Private OTP verification: code={text}, phone={waiting_phone}, user={user.id}")

    # OTP Manager orqali tekshirish
    is_valid, message = otp_manager.verify_otp(waiting_phone, text, str(user.id))

    if is_valid:
        # Kod to'g'ri - foydalanuvchini ro'yxatdan o'tkazish
        registry = PhoneRegistry(
            phone=waiting_phone,
            telegram_user_id=str(user.id),
            telegram_username=user.username or '',
            full_name=user.full_name or user.first_name or '',
            is_verified=True
        )
        registry.save()

        # Seller'ning telegram_user_id ni ham yangilash
        seller = Seller.get(phone=waiting_phone, is_active=True)
        if seller:
            seller.telegram_user_id = str(user.id)
            seller.save()

        # Context tozalash
        context.user_data.pop('waiting_private_otp_phone', None)

        logger.info(f"Private OTP verified: {waiting_phone} -> user {user.id}")

        await update.message.reply_text(
            f"✅ <b>Tasdiqlandi! Muvaffaqiyatli ro'yxatdan o'tdingiz!</b>\n\n"
            f"📞 <b>Telefon:</b> {waiting_phone}\n\n"
            f"Endi guruhingizni ulash uchun:\n"
            f"1️⃣ Guruh yarating yoki mavjud guruhga botni qo'shing\n"
            f"2️⃣ Guruhda /start bosing\n"
            f"3️⃣ Telefon raqamingizni yuboring: <code>{waiting_phone}</code>\n"
            f"4️⃣ OTP kodi <b>shu chatga</b> keladi\n"
            f"5️⃣ Kodni guruhga yozing va guruhni ulang",
            parse_mode='HTML'
        )
        return True
    else:
        await update.message.reply_text(
            f"❌ <b>Xato!</b>\n\n{message}",
            parse_mode='HTML'
        )
        return True


# Aliases for app.py compatibility
add_seller_command = add_seller
list_sellers_command = list_sellers
delete_seller_command = delete_seller
stats_command = stats
test_order_command = test_order
get_chat_id_command = get_chat_id
otp_stats_command = otp_stats
otp_security_command = otp_security


async def handle_menu_callback(update, context):
    """Menu callback handler - callback_handler.py ga yo'naltirish"""
    from . import callback_handler
    await callback_handler.handle_callback(update, context)


# ==========================================
# ADMIN TEXT MESSAGE HANDLERS
# ==========================================

async def handle_admin_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Admin text input handler - quyidagilarni qabul qiladi:
    1. Buyurtma qidirish - order ID
    2. Shablon qo'shish - sarlavha va matn
    3. Shablon tahrirlash - yangi matn
    """
    from . import callback_handler
    from .models import NotificationTemplate

    chat = update.effective_chat
    user = update.effective_user

    # Faqat shaxsiy chatda va faqat adminlar uchun
    if chat.type != 'private':
        return False

    if not await is_admin(user.id):
        return False

    text = update.message.text.strip()

    # 1. BUYURTMA QIDIRISH
    if context.user_data.get('waiting_order_search'):
        context.user_data.pop('waiting_order_search', None)
        await callback_handler.search_order_by_id(text, update.message, context)
        return True

    # 2. SHABLON QO'SHISH
    if context.user_data.get('adding_template'):
        step = context.user_data.get('template_step', 'title')

        if step == 'title':
            # Sarlavha qabul qilindi
            context.user_data['new_template_title'] = text
            context.user_data['template_step'] = 'content'

            keyboard = [[InlineKeyboardButton("❌ Bekor qilish", callback_data="notify_cancel")]]

            await update.message.reply_text(
                f"✅ <b>Sarlavha:</b> {text}\n\n"
                f"2️⃣ Endi xabar <b>matnini</b> yuboring:\n\n"
                f"<i>(HTML formatida yozishingiz mumkin)</i>",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return True

        elif step == 'content':
            # Matn qabul qilindi - shablonni saqlash
            title = context.user_data.get('new_template_title', 'Nomsiz')
            content = text

            # Yangi shablon yaratish
            templates = NotificationTemplate.get_all_sorted()
            max_order = max([t.order_num for t in templates], default=0) if templates else 0

            template = NotificationTemplate(
                title=title,
                content=content,
                order_num=max_order + 1
            )
            template.save()

            # Context tozalash
            context.user_data.pop('adding_template', None)
            context.user_data.pop('template_step', None)
            context.user_data.pop('new_template_title', None)

            keyboard = [
                [InlineKeyboardButton("📤 Yuborish", callback_data=f"notify_send_{template.id}")],
                [InlineKeyboardButton("◀️ Shablonlar ro'yxati", callback_data="admin_notify")]
            ]

            await update.message.reply_text(
                f"✅ <b>SHABLON SAQLANDI</b>\n\n"
                f"📄 <b>Shablon #{template.order_num}:</b> {template.title}\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"{template.content}\n"
                "━━━━━━━━━━━━━━━━━━━━",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return True

    # 3. SHABLON TAHRIRLASH
    if context.user_data.get('editing_template'):
        template_id = context.user_data.get('editing_template')
        template = NotificationTemplate.get(id=template_id)

        if template:
            # Yangi matnni saqlash
            template.content = text
            template.save()

            # Context tozalash
            context.user_data.pop('editing_template', None)
            context.user_data.pop('template_step', None)

            keyboard = [
                [InlineKeyboardButton("📤 Yuborish", callback_data=f"notify_send_{template.id}")],
                [InlineKeyboardButton("◀️ Ortga", callback_data="admin_notify")]
            ]

            await update.message.reply_text(
                f"✅ <b>SHABLON YANGILANDI</b>\n\n"
                f"📄 <b>Shablon #{template.order_num}:</b> {template.title}\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"{template.content}\n"
                "━━━━━━━━━━━━━━━━━━━━",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            context.user_data.pop('editing_template', None)
            await update.message.reply_text(
                "❌ Shablon topilmadi!",
                parse_mode='HTML'
            )

        return True

    return False


async def handle_change_phone_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Telefon raqamni o'zgartirish callback"""
    query = update.callback_query
    await query.answer()

    # Yangi telefon raqam kutish holatini o'rnatish
    context.user_data['waiting_phone_registration'] = True

    await query.edit_message_text(
        f"📝 <b>Telefon raqamni o'zgartirish</b>\n\n"
        f"Yangi telefon raqamingizni yuboring:\n\n"
        f"<i>Masalan: +998901234567</i>",
        parse_mode='HTML'
    )


async def handle_staff_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xodim qo'shish uchun matn qabul qilish"""
    from .models import Seller, Staff

    chat = update.effective_chat
    user = update.effective_user

    # Faqat shaxsiy chatda
    if chat.type != 'private':
        return False

    seller_id = context.user_data.get('adding_staff_seller')
    step = context.user_data.get('adding_staff_step')

    if not seller_id or not step:
        return False

    text = update.message.text.strip()

    if step == 'staff_id':
        # ID qabul qilindi
        context.user_data['adding_staff_id'] = text
        context.user_data['adding_staff_step'] = 'name'

        await update.message.reply_text(
            f"✅ <b>ID:</b> {text}\n\n"
            f"👤 Endi xodimning <b>to'liq ismini</b> yuboring:\n\n"
            f"<i>Masalan: Alisher Karimov</i>",
            parse_mode='HTML'
        )
        return True

    elif step == 'name':
        # Ism qabul qilindi
        context.user_data['adding_staff_name'] = text
        context.user_data['adding_staff_step'] = 'phone'

        await update.message.reply_text(
            f"✅ <b>Ism:</b> {text}\n\n"
            f"📱 Endi xodimning <b>telefon raqamini</b> yuboring:\n\n"
            f"<i>Masalan: +998901234567</i>\n\n"
            f"Yoki <b>0</b> - telefon kiritmasdan davom etish",
            parse_mode='HTML'
        )
        return True

    elif step == 'phone':
        # Telefon qabul qilindi
        phone = ''
        if text not in ['0', '-', 'skip', 'o\'tkazish']:
            phone_pattern = re.compile(r'^[\+]?998[0-9]{9}$')
            clean_phone = re.sub(r'[\s\-\(\)]', '', text)
            if clean_phone and not clean_phone.startswith('+'):
                clean_phone = '+' + clean_phone

            if not phone_pattern.match(clean_phone):
                await update.message.reply_text(
                    f"❌ <b>Noto'g'ri format!</b>\n\n"
                    f"Telefon raqam to'g'ri formatda bo'lishi kerak.\n"
                    f"<i>Masalan: +998901234567</i>\n\n"
                    f"Yoki /skip - telefon kiritmasdan davom etish",
                    parse_mode='HTML'
                )
                return True
            phone = clean_phone

        context.user_data['adding_staff_phone'] = phone
        context.user_data['adding_staff_step'] = 'role'

        keyboard = [
            [InlineKeyboardButton("👨‍💼 Menejer", callback_data=f"staff_role|{seller_id}|manager")],
            [InlineKeyboardButton("👨‍🍳 Oshpaz", callback_data=f"staff_role|{seller_id}|cook")],
            [InlineKeyboardButton("🚚 Yetkazuvchi", callback_data=f"staff_role|{seller_id}|courier")],
            [InlineKeyboardButton("👤 Xodim", callback_data=f"staff_role|{seller_id}|staff")]
        ]

        await update.message.reply_text(
            f"✅ <b>Telefon:</b> {phone or 'Kiritilmadi'}\n\n"
            f"🏷 Xodimning <b>rolini</b> tanlang:",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return True

    return False


async def handle_staff_role_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xodim rolini tanlash callback"""
    from .models import Seller, Staff

    query = update.callback_query
    await query.answer()

    data = query.data  # staff_role|seller_id|role
    parts = data.split("|")
    if len(parts) != 3:
        return

    _, seller_id, role = parts

    staff_id_num = context.user_data.get('adding_staff_id', '')
    staff_name = context.user_data.get('adding_staff_name', '')
    staff_phone = context.user_data.get('adding_staff_phone', '')

    if not staff_name:
        await query.edit_message_text("❌ Xatolik yuz berdi. Qaytadan urinib ko'ring.")
        return

    # Xodimni yaratish
    staff = Staff(
        seller_id=seller_id,
        staff_id=staff_id_num,
        full_name=staff_name,
        phone=staff_phone,
        role=role,
        is_active=True
    )
    staff.save()

    # Context ni tozalash
    context.user_data.pop('adding_staff_seller', None)
    context.user_data.pop('adding_staff_step', None)
    context.user_data.pop('adding_staff_id', None)
    context.user_data.pop('adding_staff_name', None)
    context.user_data.pop('adding_staff_phone', None)

    role_names = {
        'manager': 'Menejer',
        'cook': 'Oshpaz',
        'courier': 'Yetkazuvchi',
        'staff': 'Xodim'
    }

    keyboard = [
        [InlineKeyboardButton("👥 Xodimlar ro'yxati", callback_data=f"seller_staff_{seller_id}")],
        [InlineKeyboardButton("➕ Yana qo'shish", callback_data=f"add_staff_{seller_id}")]
    ]

    await query.edit_message_text(
        f"✅ <b>Xodim muvaffaqiyatli qo'shildi!</b>\n\n"
        f"🆔 <b>ID:</b> {staff_id_num}\n"
        f"👤 <b>Ism:</b> {staff_name}\n"
        f"📱 <b>Telefon:</b> {staff_phone or 'Kiritilmadi'}\n"
        f"🏷 <b>Rol:</b> {role_names.get(role, 'Xodim')}",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def handle_private_phone_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Shaxsiy chatda telefon raqam yuborilganda:
    1. Agar ro'yxatdan o'tish kutilayotgan bo'lsa - PhoneRegistry ga saqlash
    2. Agar faol OTP bo'lsa - kodni yuborish
    """
    from .models import PhoneRegistry

    chat = update.effective_chat
    user = update.effective_user

    # Faqat shaxsiy chatda
    if chat.type != 'private':
        return False

    text = update.message.text.strip() if update.message.text else ""

    # Telefon raqam formatini tekshirish
    phone_pattern = re.compile(r'^[\+]?998[0-9]{9}$')
    clean_phone = re.sub(r'[\s\-\(\)]', '', text)

    if clean_phone and not clean_phone.startswith('+'):
        clean_phone = '+' + clean_phone

    if not phone_pattern.match(clean_phone):
        return False

    # 1. Ro'yxatdan o'tish kutilayotgan bo'lsa - PhoneRegistry ga saqlash
    waiting_registration = context.user_data.get('waiting_phone_registration')

    if waiting_registration:
        from .models import Seller

        # ==========================================
        # XAVFSIZLIK: Boshqa raqamdan kirishga urinish tekshirish
        # ==========================================
        existing_seller = Seller.get(phone=clean_phone, is_active=True)

        if existing_seller:
            # Bu telefon allaqachon seller'ga tegishli
            existing_registry = PhoneRegistry.get_by_phone(clean_phone)

            # Agar telefon boshqa foydalanuvchiga ulangan bo'lsa
            if existing_registry and existing_registry.telegram_user_id != str(user.id):
                # Biznes egasiga OGOHLANTIRISH yuborish
                try:
                    warning_text = (
                        f"🚨 <b>OGOHLANTIRISH!</b>\n\n"
                        f"Sizning raqamingizdan kirishga urinilmoqda!\n\n"
                        f"📞 <b>Raqam:</b> {clean_phone}\n"
                        f"🏪 <b>Biznes:</b> {existing_seller.full_name}\n\n"
                        f"👤 <b>Urinayotgan shaxs:</b>\n"
                        f"   Ism: {user.full_name or user.first_name or 'Noma`lum'}\n"
                        f"   Username: @{user.username or 'noma`lum'}\n"
                        f"   ID: <code>{user.id}</code>\n\n"
                        f"⚠️ Agar bu siz bo'lmasangiz, admin bilan bog'laning!"
                    )
                    await context.bot.send_message(
                        chat_id=int(existing_registry.telegram_user_id),
                        text=warning_text,
                        parse_mode='HTML'
                    )
                    logger.warning(f"Unauthorized access attempt: user {user.id} tried phone {clean_phone}")
                except Exception as e:
                    logger.error(f"Failed to send unauthorized access warning: {e}")

                # Biznes egasiga OTP yuborish
                success, otp_msg = await otp_manager.send_otp(clean_phone, existing_registry.telegram_user_id)

                if success:
                    # OTP kodni kutish holatini o'rnatish
                    context.user_data['waiting_phone_registration'] = False
                    context.user_data['waiting_private_otp_phone'] = clean_phone

                    await update.message.reply_text(
                        f"⚠️ <b>Bu raqam boshqa biznesga tegishli!</b>\n\n"
                        f"📞 <code>{clean_phone}</code>\n"
                        f"🏪 <b>Biznes:</b> {existing_seller.full_name}\n\n"
                        f"Biznes egasiga ogohlantirish va tasdiqlash kodi yuborildi.\n\n"
                        f"Agar bu sizning raqamingiz bo'lsa, biznes egasiga yuborilgan "
                        f"<b>6 xonali tasdiqlash kodini</b> shu yerga kiriting:",
                        parse_mode='HTML'
                    )
                else:
                    context.user_data.pop('waiting_phone_registration', None)
                    await update.message.reply_text(
                        f"⚠️ <b>Bu raqam boshqa biznesga tegishli!</b>\n\n"
                        f"📞 <code>{clean_phone}</code>\n\n"
                        f"Biznes egasiga ogohlantirish yuborildi.\n"
                        f"{otp_msg}",
                        parse_mode='HTML'
                    )
                return True

            # Agar seller bor lekin PhoneRegistry da yo'q va seller'ning telegram_user_id boshqa
            elif not existing_registry and existing_seller.telegram_user_id and existing_seller.telegram_user_id != str(user.id):
                # Seller'ning Telegram ID'siga ogohlantirish
                try:
                    warning_text = (
                        f"🚨 <b>OGOHLANTIRISH!</b>\n\n"
                        f"Sizning raqamingizdan kirishga urinilmoqda!\n\n"
                        f"📞 <b>Raqam:</b> {clean_phone}\n"
                        f"🏪 <b>Biznes:</b> {existing_seller.full_name}\n\n"
                        f"👤 <b>Urinayotgan shaxs:</b>\n"
                        f"   Ism: {user.full_name or user.first_name or 'Noma`lum'}\n"
                        f"   Username: @{user.username or 'noma`lum'}\n"
                        f"   ID: <code>{user.id}</code>\n\n"
                        f"⚠️ Agar bu siz bo'lmasangiz, admin bilan bog'laning!"
                    )
                    await context.bot.send_message(
                        chat_id=int(existing_seller.telegram_user_id),
                        text=warning_text,
                        parse_mode='HTML'
                    )
                    logger.warning(f"Unauthorized access attempt: user {user.id} tried phone {clean_phone}")
                except Exception as e:
                    logger.error(f"Failed to send unauthorized access warning: {e}")

                context.user_data.pop('waiting_phone_registration', None)
                await update.message.reply_text(
                    f"⚠️ <b>Bu raqam boshqa biznesga tegishli!</b>\n\n"
                    f"📞 <code>{clean_phone}</code>\n\n"
                    f"Biznes egasiga ogohlantirish yuborildi.\n"
                    f"Agar bu sizning raqamingiz bo'lsa, avval guruhda ro'yxatdan o'ting.",
                    parse_mode='HTML'
                )
                return True

        # ==========================================
        # Normal ro'yxatdan o'tish
        # ==========================================
        # PhoneRegistry ga saqlash
        registry = PhoneRegistry(
            phone=clean_phone,
            telegram_user_id=str(user.id),
            telegram_username=user.username or '',
            full_name=user.full_name or user.first_name or '',
            is_verified=True
        )
        registry.save()

        # Kutish holatini tozalash
        context.user_data.pop('waiting_phone_registration', None)

        logger.info(f"Phone registered: {clean_phone} -> telegram_user_id: {user.id}")

        await update.message.reply_text(
            f"✅ <b>Muvaffaqiyatli ro'yxatdan o'tdingiz!</b>\n\n"
            f"📞 <b>Telefon:</b> {clean_phone}\n\n"
            f"Endi guruhingizni ulash uchun:\n"
            f"1️⃣ Guruh yarating yoki mavjud guruhga botni qo'shing\n"
            f"2️⃣ Guruhda /start bosing\n"
            f"3️⃣ Telefon raqamingizni yuboring: <code>{clean_phone}</code>\n"
            f"4️⃣ OTP kodi <b>shu chatga</b> keladi\n"
            f"5️⃣ Kodni guruhga yozing va ro'yxatdan o'ting",
            parse_mode='HTML'
        )
        return True

    # 2. Faol OTP bormi tekshirish
    pending_otp = otp_manager.get_pending_otp(clean_phone)

    if pending_otp:
        # Bu telefon shu foydalanuvchiga tegishlimi tekshirish
        registered = PhoneRegistry.get_by_phone(clean_phone)
        if registered and registered.telegram_user_id == str(user.id):
            # OTP mavjud va telefon egasi - kodni yuborish
            await update.message.reply_text(
                f"🔐 <b>Tasdiqlash kodi</b>\n\n"
                f"📞 Telefon: <code>{clean_phone}</code>\n\n"
                f"🔑 Sizning kodingiz: <code>{pending_otp.otp_code}</code>\n\n"
                f"⏱ Kod 5 daqiqa amal qiladi.\n"
                f"<i>Ushbu kodni guruhga yuboring.</i>",
                parse_mode='HTML'
            )
            logger.info(f"OTP code sent to registered owner {user.id} for phone {clean_phone}")
            return True
        else:
            # Telefon boshqa odamga tegishli
            await update.message.reply_text(
                f"⚠️ <b>Bu telefon raqami sizga tegishli emas!</b>\n\n"
                f"📞 <code>{clean_phone}</code>\n\n"
                f"Agar bu sizning raqamingiz bo'lsa, avval /start bosib ro'yxatdan o'ting.",
                parse_mode='HTML'
            )
            return True
    else:
        # OTP mavjud emas - ro'yxatdan o'tganmi tekshirish
        registered = PhoneRegistry.get_by_phone(clean_phone)
        if registered:
            if registered.telegram_user_id == str(user.id):
                await update.message.reply_text(
                    f"👋 <b>Siz ro'yxatdan o'tgansiz!</b>\n\n"
                    f"📞 <b>Telefon:</b> {clean_phone}\n\n"
                    f"Hozirda faol tasdiqlash kodi yo'q.\n"
                    f"Guruhda telefon raqamingizni yuboring - OTP kodi shu chatga keladi.",
                    parse_mode='HTML'
                )
            else:
                await update.message.reply_text(
                    f"⚠️ <b>Bu telefon boshqa foydalanuvchiga ulangan!</b>\n\n"
                    f"📞 <code>{clean_phone}</code>",
                    parse_mode='HTML'
                )
        else:
            # Ro'yxatdan o'tmagan
            await update.message.reply_text(
                f"❌ <b>Telefon raqam ro'yxatdan o'tmagan!</b>\n\n"
                f"📞 <code>{clean_phone}</code>\n\n"
                f"Avval /start bosib telefon raqamingizni ro'yxatdan o'tkazing.",
                parse_mode='HTML'
            )
        return True
