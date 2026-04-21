from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, PicklePersistence
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


async def order_polling_loop(app):
    """
    Nonbor API polling loop: avvalgi javob kelgandan keyin POLL_INTERVAL sekund kutadi.
    Har doim faqat bitta so'rov ishlaydi — serverga ortiqcha yuklama yo'q.
    """
    from .core import fetch_and_send_orders
    poll_interval = int(os.getenv('POLL_INTERVAL', 5))
    logger.info(f"Order polling loop boshlandi (interval={poll_interval}s javobdan keyin)")
    while True:
        try:
            await fetch_and_send_orders()
        except Exception as e:
            logger.error(f"Order polling error: {e}")
        await asyncio.sleep(poll_interval)


async def order_polling_job(context):
    """Fallback job (loop ishga tushmasa uchun)"""
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


async def check_missed_orders_job(context):
    """Qabul qilinmagan buyurtmalar haqida admin guruhga xabar"""
    from .core import check_missed_orders
    try:
        await check_missed_orders()
    except Exception as e:
        logger.error(f"Missed orders check error: {e}")


async def call_sellers_job(context):
    """Qabul qilinmagan buyurtmalar uchun Asterisk AMI orqali qo'ng'iroq"""
    from .core import check_and_call_sellers
    try:
        await check_and_call_sellers()
    except Exception as e:
        logger.error(f"Call sellers error: {e}")


async def sync_businesses_job(context):
    """Nonbor API dan bizneslarni sellers.json ga sync qilish"""
    from .core import sync_businesses_from_api
    try:
        await sync_businesses_from_api()
    except Exception as e:
        logger.error(f"Businesses sync error: {e}")


async def admin_summary_job(context):
    """Admin guruhidagi yagona xabarni yangilash"""
    from .core import update_admin_group_summary
    try:
        await update_admin_group_summary()
    except Exception as e:
        logger.error(f"Admin summary update error: {e}")


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

    persistence = PicklePersistence(filepath=os.path.join(os.path.dirname(__file__), '..', 'data', 'bot_persistence.pkl'))
    application = ApplicationBuilder().token(token).persistence(persistence).build()

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
        # Private chatda OTP tekshirish (ruxsatsiz kirish urinishi uchun)
        if await handlers.handle_private_otp_verification(update, context):
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

    poll_interval = int(os.getenv('POLL_INTERVAL', 5))
    job_queue = application.job_queue

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

    # Qabul qilinmagan buyurtmalar tekshirish (har 5 sekundda)
    job_queue.run_repeating(
        check_missed_orders_job,
        interval=5,
        first=10,
        job_kwargs={'coalesce': True, 'max_instances': 1, 'misfire_grace_time': 10}
    )
    print("\nMissed orders alert faollashtirildi (har 5 sek tekshiriladi)")

    # Asterisk AMI qo'ng'iroq (har 15 sekundda tekshiriladi)
    retry_interval = int(os.getenv('RETRY_INTERVAL', 30))
    job_queue.run_repeating(
        call_sellers_job,
        interval=15,
        first=20,
        job_kwargs={'coalesce': True, 'max_instances': 1, 'misfire_grace_time': 15}
    )
    print(f"\nAsterisk AMI autodialer faollashtirildi (har 15 sek tekshiriladi, retry={retry_interval}s)")

    # Bizneslarni APIdan sync qilish (startup + har 5 daqiqada)
    job_queue.run_repeating(
        sync_businesses_job,
        interval=300,
        first=5,
        job_kwargs={'coalesce': True, 'max_instances': 1, 'misfire_grace_time': 60}
    )
    print("\nBizneslar auto-sync faollashtirildi (startup + har 5 daqiqada)")

    # Admin guruh summary xabari (har 5 sekundda tekshiradi, o'zgarish bo'lsa yangilaydi)
    job_queue.run_repeating(
        admin_summary_job,
        interval=5,
        first=15,
        job_kwargs={'coalesce': True, 'max_instances': 1, 'misfire_grace_time': 10}
    )
    print("\nAdmin guruh summary faollashtirildi (har 5 sek tekshiriladi)")

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
    print(f"\nBuyurtmalar: javob kelgandan keyin {poll_interval}s kutib tekshiriladi")
    print("\n" + "="*50 + "\n")

    # Bot ishga tushganda: guruh ma'lumotlari yangilash + polling loop boshlash
    async def post_init(app):
        await update_sellers_group_info(app)
        asyncio.create_task(order_polling_loop(app))

    application.post_init = post_init

    application.run_polling(drop_pending_updates=True)
