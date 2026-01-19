from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters
import os
import logging
import asyncio
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


async def order_polling_job(context):
    """Real-time buyurtmalarni tekshirish (Nonbor API)"""
    from .core import fetch_and_send_orders
    try:
        await fetch_and_send_orders()
    except Exception as e:
        logger.error(f"Order polling error: {e}")




async def cleanup_expired_orders_job(context):
    """Muddati o'tgan buyurtmalarni guruhdan o'chirish"""
    from .core import cleanup_expired_orders
    try:
        await cleanup_expired_orders()
    except Exception as e:
        logger.error(f"Cleanup expired orders error: {e}")


async def update_sellers_group_info(application):
    """Barcha sotuvchilarning guruh ma'lumotlarini yangilash"""
    from .models import Seller

    sellers = Seller.load_all()
    updated_count = 0

    for seller_data in sellers:
        seller = Seller.from_dict(seller_data)

        # Faqat guruh ulangan, lekin nomi/linki bo'sh bo'lganlarni yangilash
        if seller.group_chat_id and (not seller.group_title or not seller.group_invite_link):
            try:
                chat = await application.bot.get_chat(int(seller.group_chat_id))

                # Guruh nomini olish
                if chat.title and not seller.group_title:
                    seller.group_title = chat.title

                # Invite linkni olish
                if not seller.group_invite_link:
                    try:
                        # Mavjud link bo'lsa
                        if chat.invite_link:
                            seller.group_invite_link = chat.invite_link
                        else:
                            # Yangi link yaratish
                            invite_link = await application.bot.export_chat_invite_link(int(seller.group_chat_id))
                            seller.group_invite_link = invite_link
                    except Exception as link_error:
                        logger.warning(f"Invite link olishda xato ({seller.full_name}): {link_error}")

                seller.save()
                updated_count += 1
                logger.info(f"Guruh ma'lumotlari yangilandi: {seller.full_name} - {seller.group_title}")

            except Exception as e:
                logger.warning(f"Guruh ma'lumotlarini olishda xato ({seller.full_name}): {e}")

    if updated_count > 0:
        logger.info(f"Jami {updated_count} ta sotuvchi guruh ma'lumotlari yangilandi")


def run_bot():
    from . import handlers
    from . import callback_handler
    from .dashboard import VendorDashboard
    from .staff_manager import StaffManager

    token = os.getenv('TELEGRAM_BOT_TOKEN')

    if not token or token == 'YOUR_BOT_TOKEN_HERE':
        print("\n" + "="*50)
        print("XATO: Bot token kiritilmagan!")
        print("="*50)
        print("\n1. .env faylini oching")
        print("2. TELEGRAM_BOT_TOKEN= dan keyin tokenni qo'ying")
        print("3. @BotFather dan token olish mumkin")
        print("\n" + "="*50)
        return

    application = ApplicationBuilder().token(token).build()

    # Dashboard va Staff Manager instansiyalari
    dashboard = VendorDashboard()
    staff_manager = StaffManager()

    # Dashboard commands
    async def dashboard_cmd(update, context):
        await dashboard.show_dashboard(update, context)

    async def earnings_cmd(update, context):
        await dashboard.show_earnings(update, context)

    async def orders_cmd(update, context):
        await dashboard.show_orders_list(update, context)

    async def staff_cmd(update, context):
        await staff_manager.show_staff_management(update, context)

    # Commands
    application.add_handler(CommandHandler("start", handlers.start))
    application.add_handler(CommandHandler("dashboard", dashboard_cmd))
    application.add_handler(CommandHandler("earnings", earnings_cmd))
    application.add_handler(CommandHandler("orders", orders_cmd))
    application.add_handler(CommandHandler("staff", staff_cmd))
    application.add_handler(CommandHandler("add_seller", handlers.add_seller))
    application.add_handler(CommandHandler("set_group", handlers.set_group))
    application.add_handler(CommandHandler("list_sellers", handlers.list_sellers))
    application.add_handler(CommandHandler("delete_seller", handlers.delete_seller))
    application.add_handler(CommandHandler("test_order", handlers.test_order))
    application.add_handler(CommandHandler("get_chat_id", handlers.get_chat_id))
    application.add_handler(CommandHandler("help", handlers.help_command))
    application.add_handler(CommandHandler("stats", handlers.stats))

    # OTP Admin commands
    application.add_handler(CommandHandler("otp_stats", handlers.otp_stats))
    application.add_handler(CommandHandler("otp_security", handlers.otp_security))

    # Dashboard callbacks
    async def handle_dashboard_callback(update, context):
        query = update.callback_query
        data = query.data

        if data == "dash_back" or data == "dash_refresh":
            await dashboard.show_dashboard(update, context)
        elif data == "dash_stats":
            await dashboard.show_statistics(update, context)
        elif data == "dash_earnings":
            await dashboard.show_earnings(update, context)
        elif data == "dash_orders":
            await dashboard.show_orders_list(update, context)
        elif data == "dash_profile":
            await dashboard.show_profile(update, context)
        elif data == "dash_help":
            await dashboard.show_help(update, context)
        elif data == "dash_staff":
            await staff_manager.show_staff_management(update, context)
        elif data == "stats_today":
            await dashboard.show_today_stats(update, context)
        elif data == "stats_week":
            await dashboard.show_week_stats(update, context)
        elif data == "stats_month":
            await dashboard.show_month_stats(update, context)
        elif data == "staff_add":
            await staff_manager.start_add_staff(update, context)
        elif data == "staff_remove":
            await staff_manager.show_remove_staff(update, context)
        elif data.startswith("setrole_"):
            await staff_manager.handle_role_selection(update, context)
        elif data.startswith("confirmremove_"):
            await staff_manager.confirm_remove_staff(update, context)
        elif data.startswith("doremove_"):
            await staff_manager.do_remove_staff(update, context)
        elif data.startswith("otp_"):
            await handlers.handle_otp_callback(update, context)
        elif data == "change_phone":
            await handlers.handle_change_phone_callback(update, context)
        # Xodim rolini tanlash callback
        elif data.startswith("staff_role|"):
            await handlers.handle_staff_role_callback(update, context)
        # Seller Dashboard callbacks
        elif data.startswith("seller_stats_") or data.startswith("seller_staff_") or data.startswith("seller_back_") or data.startswith("add_staff_") or data.startswith("remove_staff") or data.startswith("rmstaff_") or data.startswith("delstaff_"):
            await callback_handler.handle_callback(update, context)
        else:
            # Boshqa callbacklarni callback_handler ga yo'naltirish
            await callback_handler.handle_callback(update, context)

    # Callbacks - dashboard callbacklarini alohida handle qilish
    application.add_handler(CallbackQueryHandler(
        handle_dashboard_callback,
        pattern="^(dash_|stats_|staff_|setrole_|confirmremove_|doremove_|otp_|change_phone|seller_stats_|seller_staff_|seller_back_|add_staff_|remove_staff|rmstaff_|delstaff_|staff_role)"
    ))

    # Boshqa callbacklar
    application.add_handler(CallbackQueryHandler(callback_handler.handle_callback))

    # Message handler for group ID input, phone edit, and group registration
    async def message_handler(update, context):
        # Admin text input (buyurtma qidirish, shablon yaratish/tahrirlash)
        if await handlers.handle_admin_text_input(update, context):
            return
        # Sotuvchi xodim qo'shish (ism/telefon)
        if await handlers.handle_staff_input(update, context):
            return
        # Xodim qo'shish - telefon raqam
        if await staff_manager.handle_staff_phone(update, context):
            return
        # Xodim qo'shish - ism
        if await staff_manager.handle_staff_name(update, context):
            return
        # Guruhdan tasdiqlash kodi
        if await handlers.handle_verification_code(update, context):
            return
        # Guruhdan telefon raqam (sotuvchi ro'yxatdan o'tishi)
        if await handlers.handle_group_phone_message(update, context):
            return
        # Shaxsiy chatda telefon raqam - ro'yxatdan o'tish yoki OTP olish
        if await handlers.handle_private_phone_registration(update, context):
            return
        # Admin - yangi telefon raqamini qabul qilish
        if await handlers.handle_new_phone_message(update, context):
            return
        # Admin - guruh ID qabul qilish
        if await handlers.handle_group_id_message(update, context):
            return

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    # Buyurtmalarni real-time tekshirish (har 3 sekundda)
    poll_interval = int(os.getenv('POLL_INTERVAL', 3))
    job_queue = application.job_queue
    job_queue.run_repeating(
        order_polling_job,
        interval=poll_interval,
        first=3,
        job_kwargs={'coalesce': True, 'max_instances': 1, 'misfire_grace_time': 30}
    )

    # Muddati o'tgan buyurtmalarni tozalash (har 2 sekundda - real-time)
    cleanup_interval = 2  # 2 sekund
    order_expiry_minutes = int(os.getenv('ORDER_EXPIRY_MINUTES', 5))
    job_queue.run_repeating(
        cleanup_expired_orders_job,
        interval=cleanup_interval,
        first=5,
        job_kwargs={'coalesce': True, 'max_instances': 1, 'misfire_grace_time': 10}
    )
    print(f"\nExpired orders cleanup faollashtirildi (har 2 sek tekshiriladi, {order_expiry_minutes} daqiqadan keyin o'chiriladi)")

    print("\n" + "="*50)
    print("SELLER BOT - AVTONOM TIZIM ISHGA TUSHDI")
    print("="*50)
    print("\nAsosiy buyruqlar:")
    print("  /start          - Boshlash")
    print("  /dashboard      - Boshqaruv paneli")
    print("  /staff          - Xodimlar boshqaruvi")
    print("  /stats          - Statistika")
    print("  /earnings       - Daromad hisoboti")
    print("  /orders         - Buyurtmalar ro'yxati")
    print("  /help           - Yordam")
    print("\nAdmin buyruqlar:")
    print("  /add_seller     - Sotuvchi qo'shish")
    print("  /list_sellers   - Sotuvchilar ro'yxati")
    print("  /set_group      - Guruh ulash")
    print("  /delete_seller  - Sotuvchini o'chirish")
    print("  /test_order     - Test buyurtma")
    print("  /get_chat_id    - Chat ID olish")
    print("\nOTP Monitoring:")
    print("  /otp_stats      - OTP statistikasi")
    print("  /otp_security   - Xavfsizlik hisoboti")
    print("\nBuyurtmalar har " + str(poll_interval) + " sekundda tekshiriladi")
    print("\n" + "="*50 + "\n")

    # Bot ishga tushganda guruh ma'lumotlarini yangilash
    async def post_init(app):
        await update_sellers_group_info(app)

    application.post_init = post_init

    application.run_polling(drop_pending_updates=True)
