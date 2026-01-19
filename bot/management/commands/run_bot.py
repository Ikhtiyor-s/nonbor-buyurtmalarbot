"""
Management command: Telegram botni ishga tushirish
Usage: python manage.py run_bot
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Telegram botni polling rejimida ishga tushirish"

    def handle(self, *args, **options):
        from bot.app import run_bot
        run_bot()
