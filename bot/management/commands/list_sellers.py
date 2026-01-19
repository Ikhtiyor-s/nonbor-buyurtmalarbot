"""
Management command: Barcha sotuvchilar ro'yxatini ko'rsatish
Usage: python manage.py list_sellers
"""
from django.core.management.base import BaseCommand
from bot.models import Seller


class Command(BaseCommand):
    help = "Barcha sotuvchilar ro'yxatini ko'rsatish"

    def add_arguments(self, parser):
        parser.add_argument(
            '--active',
            action='store_true',
            help="Faqat faol sotuvchilarni ko'rsatish"
        )

    def handle(self, *args, **options):
        queryset = Seller.objects.all()

        if options['active']:
            queryset = queryset.filter(is_active=True)

        sellers = queryset.order_by('-created_at')

        if not sellers.exists():
            self.stdout.write(
                self.style.WARNING("Hech qanday sotuvchi topilmadi")
            )
            return

        self.stdout.write("\n" + "=" * 80)
        self.stdout.write(self.style.SUCCESS(" SOTUVCHILAR RO'YXATI "))
        self.stdout.write("=" * 80 + "\n")

        for seller in sellers:
            status = "✅ Faol" if seller.is_active else "❌ Nofaol"
            orders_count = seller.orders.count()

            self.stdout.write(
                f"\n📋 ID: {seller.id}\n"
                f"   👤 Ism: {seller.full_name}\n"
                f"   📱 Telegram ID: {seller.telegram_id}\n"
                f"   💬 Guruh ID: {seller.group_chat_id}\n"
                f"   🔗 API ID: {seller.api_identifier or '-'}\n"
                f"   📦 Buyurtmalar: {orders_count}\n"
                f"   📊 Status: {status}\n"
                f"   📅 Qo'shilgan: {seller.created_at.strftime('%d.%m.%Y %H:%M')}\n"
            )

        self.stdout.write("\n" + "-" * 80)
        self.stdout.write(f"Jami: {sellers.count()} sotuvchi\n")
