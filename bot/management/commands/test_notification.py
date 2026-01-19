"""
Management command: Test notification yuborish
Usage: python manage.py test_notification <group_chat_id> [--seller_id <id>]
"""
import asyncio
from datetime import datetime
from django.core.management.base import BaseCommand, CommandError
from bot.core import NotificationBot
from bot.models import Seller


class Command(BaseCommand):
    help = "Test notification yuborish"

    def add_arguments(self, parser):
        parser.add_argument(
            '--group_id',
            type=str,
            help="Telegram guruh ID (agar sotuvchi ko'rsatilmasa)"
        )
        parser.add_argument(
            '--seller_id',
            type=int,
            help="Sotuvchi ID (database'dagi)"
        )

    def handle(self, *args, **options):
        group_id = options.get('group_id')
        seller_id = options.get('seller_id')

        if seller_id:
            try:
                seller = Seller.objects.get(id=seller_id)
                group_id = seller.group_chat_id
                self.stdout.write(f"Sotuvchi topildi: {seller.full_name}")
            except Seller.DoesNotExist:
                raise CommandError(f"Sotuvchi ID={seller_id} topilmadi")

        if not group_id:
            # Birinchi faol sotuvchini olish
            seller = Seller.objects.filter(is_active=True).first()
            if seller:
                group_id = seller.group_chat_id
                self.stdout.write(f"Avtomatik tanlandi: {seller.full_name}")
            else:
                raise CommandError(
                    "group_id yoki seller_id ko'rsating, yoki kamida bitta sotuvchi qo'shing"
                )

        # Test buyurtma
        test_order = {
            "id": f"test_{datetime.now().strftime('%H%M%S')}",
            "seller_telegram_id": "",  # Bo'sh qoldirish - group_id orqali yuboriladi
            "status": "new",
            "customer": {
                "name": "Test Mijoz",
                "phone": "+998901234567",
                "address": "Toshkent, Test ko'chasi, 123-uy"
            },
            "total": 250000,
            "items": [
                {"name": "Test Mahsulot 1", "price": 150000, "quantity": 1},
                {"name": "Test Mahsulot 2", "price": 50000, "quantity": 2}
            ],
            "notes": "Bu test xabar - e'tibor bermang",
            "created_at": datetime.now().isoformat()
        }

        self.stdout.write(f"\n📤 Test xabar yuborilmoqda: {group_id}\n")

        try:
            bot = NotificationBot()

            async def send_test():
                return await bot.send_custom_message(
                    chat_id=group_id,
                    text=bot._format_order_message(test_order)
                )

            success = asyncio.run(send_test())

            if success:
                self.stdout.write(
                    self.style.SUCCESS("✅ Test xabar muvaffaqiyatli yuborildi!\n")
                )
            else:
                self.stdout.write(
                    self.style.ERROR("❌ Test xabar yuborilmadi\n")
                )

        except Exception as e:
            raise CommandError(f"Xatolik: {e}")
