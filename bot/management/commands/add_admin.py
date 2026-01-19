"""
Management command: Bot admin qo'shish
Usage: python manage.py add_admin <telegram_id> <full_name> [--superadmin]
"""
from django.core.management.base import BaseCommand, CommandError
from bot.models import AdminUser


class Command(BaseCommand):
    help = "Bot admin qo'shish"

    def add_arguments(self, parser):
        parser.add_argument(
            'telegram_id',
            type=str,
            help="Admin Telegram user ID"
        )
        parser.add_argument(
            'full_name',
            type=str,
            help="Admin ismi"
        )
        parser.add_argument(
            '--username',
            type=str,
            default='',
            help="Telegram @username"
        )
        parser.add_argument(
            '--superadmin',
            action='store_true',
            help="Super admin sifatida qo'shish"
        )

    def handle(self, *args, **options):
        telegram_id = options['telegram_id']
        full_name = options['full_name']
        username = options['username']
        is_superadmin = options['superadmin']

        # Mavjudligini tekshirish
        if AdminUser.objects.filter(telegram_id=telegram_id).exists():
            raise CommandError(f"Admin telegram_id={telegram_id} allaqachon mavjud")

        try:
            admin = AdminUser.objects.create(
                telegram_id=telegram_id,
                full_name=full_name,
                username=username,
                is_superadmin=is_superadmin
            )

            admin_type = "Super Admin" if is_superadmin else "Admin"

            self.stdout.write(
                self.style.SUCCESS(
                    f"\n✅ {admin_type} muvaffaqiyatli qo'shildi:\n"
                    f"   Telegram ID: {admin.telegram_id}\n"
                    f"   Ism: {admin.full_name}\n"
                    f"   Username: @{admin.username or '-'}\n"
                    f"   Super Admin: {'Ha' if admin.is_superadmin else 'Yo\\'q'}\n"
                )
            )

        except Exception as e:
            raise CommandError(f"Xatolik: {e}")
