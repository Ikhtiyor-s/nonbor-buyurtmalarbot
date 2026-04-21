#!/bin/sh
set -e

echo "=== Migrationlar qo'llanilmoqda ==="
python manage.py migrate

echo "=== Gunicorn (webhook server) background da ishga tushirilmoqda ==="
gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 2 --daemon --log-file /tmp/gunicorn.log

echo "=== Telegram Bot ishga tushirilmoqda ==="
exec python main.py
