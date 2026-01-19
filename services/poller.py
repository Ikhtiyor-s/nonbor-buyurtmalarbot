"""
Nonbor API Poller Service
API dan buyurtmalarni polling qilish va Telegram ga yuborish
"""
import os
import logging
import asyncio
import requests
from datetime import datetime
from typing import List, Dict, Any, Optional, Set

from bot.core import NotificationBot

logger = logging.getLogger('bot')


class NonborAPIPoller:
    """
    Nonbor API dan buyurtmalarni polling qilish
    https://test.nonbor.uz/api/v2/telegram_bot/get-order-for-courier/
    """

    def __init__(self):
        self.api_url = os.getenv('EXTERNAL_API_URL', 'https://test.nonbor.uz/api/v2/telegram_bot/get-order-for-courier/')
        self.api_key = os.getenv('EXTERNAL_API_KEY', '')
        self.poll_interval = int(os.getenv('POLL_INTERVAL', '30'))
        self.processed_orders: Set[int] = set()
        self._running = False

        # Faqat shu statusdagi buyurtmalarni yuborish
        self.allowed_states = ['PENDING', 'ACCEPTED', 'PREPARING', 'READY']

        # Faqat shu bizneslardan buyurtmalarni yuborish (bo'sh bo'lsa hammasi)
        self.allowed_businesses = ['Milliy']

    async def start_polling(self):
        """
        API dan buyurtmalarni muntazam tekshirib turish
        """
        print(f"[POLLER] Nonbor API poller ishga tushdi")
        print(f"[POLLER] URL: {self.api_url}")
        print(f"[POLLER] Interval: {self.poll_interval} sekund")
        print(f"[POLLER] Allowed states: {self.allowed_states}")

        self._running = True

        while self._running:
            try:
                await self._poll_orders()
                await asyncio.sleep(self.poll_interval)
            except asyncio.CancelledError:
                print("[POLLER] Poller to'xtatildi")
                break
            except Exception as e:
                logger.error(f"Polling error: {e}")
                print(f"[POLLER] Xatolik: {e}")
                await asyncio.sleep(60)

    def stop(self):
        """Polling ni to'xtatish"""
        self._running = False

    async def _poll_orders(self):
        """
        API dan buyurtmalarni olish
        """
        try:
            headers = {
                'Accept': 'application/json',
                'Content-Type': 'application/json'
            }

            if self.api_key:
                headers['Authorization'] = f'Bearer {self.api_key}'

            response = requests.get(
                self.api_url,
                headers=headers,
                timeout=15
            )

            if response.status_code == 200:
                orders = response.json()

                if isinstance(orders, list):
                    # Yangi buyurtmalarni filtrlash
                    new_orders = []
                    for order in orders:
                        order_id = order.get('id')
                        state = order.get('state', '')
                        business_name = order.get('business', {}).get('title', '')

                        # Faqat ruxsat etilgan statuslar va yangi buyurtmalar
                        if order_id not in self.processed_orders:
                            if state in self.allowed_states:
                                # Biznes filteri (bo'sh bo'lsa hammasi o'tadi)
                                if not self.allowed_businesses or business_name in self.allowed_businesses:
                                    new_orders.append(order)

                    if new_orders:
                        print(f"[POLLER] {len(new_orders)} ta yangi buyurtma topildi")
                        await self._process_orders(new_orders)

            else:
                logger.warning(f"API returned status {response.status_code}")

        except requests.Timeout:
            logger.error("API request timed out")
        except requests.ConnectionError:
            logger.error("Could not connect to API")
        except Exception as e:
            logger.error(f"API request failed: {e}")

    async def _process_orders(self, orders: List[Dict[str, Any]]):
        """
        Buyurtmalarni qayta ishlash va Telegram ga yuborish
        """
        bot = NotificationBot()

        for order in orders:
            order_id = order.get('id')

            try:
                # Nonbor formatidan standart formatga o'tkazish
                normalized = self._normalize_nonbor_order(order)

                # Telegram ga yuborish
                success = await bot.send_order_notification(normalized)

                if success:
                    self.processed_orders.add(order_id)
                    print(f"[POLLER] Buyurtma #{order_id} yuborildi")

                    # Memory leak prevention
                    if len(self.processed_orders) > 10000:
                        self.processed_orders = set(list(self.processed_orders)[-5000:])

            except Exception as e:
                logger.error(f"Error processing order {order_id}: {e}")

    def _normalize_nonbor_order(self, order: Dict[str, Any]) -> Dict[str, Any]:
        """
        Nonbor API formatini standart formatga o'tkazish
        """
        # Business (restoran) ma'lumotlari
        business = order.get('business', {})
        business_name = business.get('title', 'Nomalum restoran')
        business_address = business.get('address', '')

        # Delivery ma'lumotlari
        delivery = order.get('delivery', {})
        delivery_address = delivery.get('address', '')
        delivery_price = delivery.get('price', 0)

        # Mahsulotlar
        order_items = order.get('order_item', [])
        items = []
        for item in order_items:
            product = item.get('product', {})
            items.append({
                'name': product.get('name', 'Nomalum'),
                'price': product.get('price', 0),
                'quantity': item.get('quantity', 1)
            })

        # Narxlar (tiyinda keladi, somga o'tkazish kerak emas - API da allaqachon som)
        total_price = order.get('total_price', 0)
        product_price = order.get('price', 0)

        # Status mapping
        state = order.get('state', 'PENDING')
        status_map = {
            'PENDING': 'new',
            'ACCEPTED': 'accepted',
            'PREPARING': 'processing',
            'READY': 'ready',
            'ON_DELIVERY': 'shipped',
            'COMPLETED': 'completed',
            'CANCELLED': 'cancelled'
        }

        # Payment method
        payment = order.get('payment_method', 'CASH')
        payment_text = 'Naqd' if payment == 'CASH' else 'Karta'

        # Notes
        notes_parts = []
        notes_parts.append(f"Restoran: {business_name}")
        if business_address:
            notes_parts.append(f"Restoran manzili: {business_address}")
        notes_parts.append(f"Tolov: {payment_text}")
        if delivery_price:
            notes_parts.append(f"Yetkazib berish: {delivery_price:,} som")

        return {
            'id': str(order.get('id')),
            'status': status_map.get(state, 'new'),
            'customer': {
                'name': f"Buyurtma #{order.get('id')}",
                'phone': '',  # API da telefon yo'q
                'address': delivery_address
            },
            'total': total_price,
            'items': items,
            'notes': '\n'.join(notes_parts),
            'created_at': order.get('created_at', datetime.now().isoformat())
        }


# Alias for backward compatibility
APIPoller = NonborAPIPoller


async def run_poller():
    """
    Standalone poller ishga tushirish
    """
    poller = NonborAPIPoller()
    await poller.start_polling()


if __name__ == '__main__':
    import django
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    django.setup()

    asyncio.run(run_poller())
