"""
Management command: Yangi sotuvchi qo'shish
Usage: python manage.py add_seller <phone> <full_name> <group_chat_id> [--api_id <api_identifier>]
"""
from django.core.management.base import BaseCommand, CommandError
from bot.models import Seller


class Command(BaseCommand):
    help = "Yangi sotuvchi qo'shish"

    def add_arguments(self, parser):
        parser.add_argument(
            'phone',
            type=str,
            help="Sotuvchi telefon raqami (+998901234567)"
        )
        parser.add_argument(
            'full_name',
            type=str,
            help="Sotuvchining to'liq ismi"
        )
        parser.add_argument(
            'group_chat_id',
            type=str,
            help="Telegram guruh ID (buyurtmalar yuboriladigan)"
        )
        parser.add_argument(
            '--api_id',
            type=str,
            default='',
            help="Tashqi API'dagi sotuvchi identifikatori"
        )
        parser.add_argument(
            '--telegram_id',
            type=str,
            default='',
            help="Sotuvchining Telegram user ID"
        )
        parser.add_argument(
            '--username',
            type=str,
            default='',
            help="Sotuvchining Telegram @username"
        )

    def handle(self, *args, **options):
        phone = options['phone']
        full_name = options['full_name']
        group_chat_id = options['group_chat_id']
        api_identifier = options['api_id']
        telegram_user_id = options['telegram_id']
        telegram_username = options['username']

        # Validatsiya
        if Seller.objects.filter(phone=phone).exists():
            raise CommandError(f"Sotuvchi phone={phone} allaqachon mavjud")

        if Seller.objects.filter(group_chat_id=group_chat_id).exists():
            raise CommandError(f"Guruh group_chat_id={group_chat_id} allaqachon boshqa sotuvchiga biriktirilgan")

        try:
            seller = Seller.objects.create(
                phone=phone,
                full_name=full_name,
                group_chat_id=group_chat_id,
                group_title=f"Sotuvchi: {full_name}",
                api_identifier=api_identifier,
                telegram_user_id=telegram_user_id,
                telegram_username=telegram_username
            )

            self.stdout.write(
                self.style.SUCCESS(
                    f"\n✅ Sotuvchi muvaffaqiyatli qo'shildi:\n"
                    f"   ID: {seller.id}\n"
                    f"   Ism: {seller.full_name}\n"
                    f"   Telefon: {seller.phone}\n"
                    f"   Guruh ID: {seller.group_chat_id}\n"
                    f"   API ID: {seller.api_identifier or '-'}\n"
                )
            )

        except Exception as e:
            raise CommandError(f"Xatolik: {e}")
