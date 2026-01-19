"""
Management command: API Poller ni ishga tushirish
Usage: python manage.py run_poller
"""
import asyncio
from django.core.management.base import BaseCommand
from services.poller import APIPoller


class Command(BaseCommand):
    help = "API Poller ni ishga tushirish (webhook o'rniga)"

    def add_arguments(self, parser):
        parser.add_argument(
            '--interval',
            type=int,
            default=30,
            help="Polling intervali (sekundlarda, default: 30)"
        )

    def handle(self, *args, **options):
        interval = options['interval']

        self.stdout.write(
            self.style.SUCCESS(
                f"\n[>>] API Poller ishga tushirilmoqda...\n"
                f"    Interval: {interval} sekund\n"
                f"    To'xtatish uchun: Ctrl+C\n"
            )
        )

        poller = APIPoller()
        poller.poll_interval = interval

        try:
            asyncio.run(poller.start_polling())
        except KeyboardInterrupt:
            self.stdout.write(
                self.style.WARNING("\n\n[STOP] Poller to'xtatildi\n")
            )
