"""
Telegram Bot Application Setup
Main entry point for running the bot with polling
"""
import os
import logging
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters
)

from . import handlers
from . import callback_handlers

logger = logging.getLogger('bot')


def create_application():
    """
    Telegram Bot Application yaratish va sozlash
    """
    token = os.getenv('TELEGRAM_BOT_TOKEN')

    if not token:
        raise ValueError(
            "TELEGRAM_BOT_TOKEN muhit o'zgaruvchisi talab qilinadi!\n"
            ".env faylga TELEGRAM_BOT_TOKEN ni qo'shing."
        )

    # Application yaratish
    application = ApplicationBuilder().token(token).build()

    # ============================================
    # Command Handlers
    # ============================================

    # /start - Asosiy menu
    application.add_handler(
        CommandHandler("start", handlers.start)
    )

    # /add_seller - Sotuvchi qo'shish
    application.add_handler(
        CommandHandler("add_seller", handlers.add_seller_command)
    )

    # /list_sellers - Sotuvchilar ro'yxati
    application.add_handler(
        CommandHandler("list_sellers", handlers.list_sellers_command)
    )
    application.add_handler(
        CommandHandler("sellers", handlers.list_sellers_command)  # Alias
    )

    # /delete_seller - Sotuvchini o'chirish
    application.add_handler(
        CommandHandler("delete_seller", handlers.delete_seller_command)
    )

    # /stats - Statistika
    application.add_handler(
        CommandHandler("stats", handlers.stats_command)
    )
    application.add_handler(
        CommandHandler("statistics", handlers.stats_command)  # Alias
    )

    # /test_order - Test buyurtma
    application.add_handler(
        CommandHandler("test_order", handlers.test_order_command)
    )
    application.add_handler(
        CommandHandler("test", handlers.test_order_command)  # Alias
    )

    # /help - Yordam
    application.add_handler(
        CommandHandler("help", handlers.help_command)
    )

    # /get_chat_id - Chat ID ni olish
    application.add_handler(
        CommandHandler("get_chat_id", handlers.get_chat_id_command)
    )
    application.add_handler(
        CommandHandler("chatid", handlers.get_chat_id_command)  # Alias
    )

    # ============================================
    # Callback Query Handlers
    # ============================================

    # Barcha callback'lar uchun yagona handler
    application.add_handler(
        CallbackQueryHandler(handlers.handle_menu_callback)
    )

    # ============================================
    # Message Handlers (guruhdan telefon va kod)
    # ============================================

    async def message_handler(update, context):
        """Guruhdan telefon raqam va tasdiqlash kodi qabul qilish"""
        # Tasdiqlash kodi
        if await handlers.handle_verification_code(update, context):
            return
        # Guruhdan telefon raqam
        if await handlers.handle_group_phone_message(update, context):
            return
        # Admin - yangi telefon raqam
        if await handlers.handle_new_phone_message(update, context):
            return
        # Admin - guruh ID
        if await handlers.handle_group_id_message(update, context):
            return

    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler)
    )

    # ============================================
    # Error Handler
    # ============================================

    application.add_error_handler(error_handler)

    return application


async def error_handler(update, context):
    """
    Global xatolarni qayta ishlash
    """
    logger.error(f"Update {update} caused error: {context.error}")

    # Foydalanuvchiga xabar berish (agar imkon bo'lsa)
    if update and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "❌ Xatolik yuz berdi. Iltimos, qaytadan urinib ko'ring.\n"
                "Muammo davom etsa, admin bilan bog'laning."
            )
        except Exception:
            pass


def run_bot():
    """
    Botni polling rejimida ishga tushirish
    """
    print("=" * 50)
    print("SELLER BOT")
    print("=" * 50)
    print("\nBot ishga tushirilmoqda...\n")

    try:
        application = create_application()

        print("[OK] Bot muvaffaqiyatli sozlandi")
        print("[>>] Polling rejimida ishlamoqda...")
        print("\nTo'xtatish uchun: Ctrl+C\n")
        print("=" * 50)

        # Botni ishga tushirish
        application.run_polling(
            allowed_updates=[
                "message",
                "callback_query",
                "chat_member"
            ],
            drop_pending_updates=True  # Eski xabarlarni o'tkazib yuborish
        )

    except KeyboardInterrupt:
        print("\n\n[STOP] Bot to'xtatildi")

    except Exception as e:
        logger.exception(f"Bot ishga tushirishda xatolik: {e}")
        print(f"\n[ERROR] Xatolik: {e}")
        raise


if __name__ == '__main__':
    # Standalone mode
    import django
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    django.setup()

    run_bot()
