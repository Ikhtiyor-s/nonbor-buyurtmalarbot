"""
AmoCRM API Service
TEKSHIRILMOQDA statusidagi buyurtmalarni olish
"""

import os
import re
import logging
import aiohttp
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


class AmoCRMService:
    """AmoCRM API bilan ishlash uchun service"""

    def __init__(self):
        self.access_token = os.getenv('AMOCRM_ACCESS_TOKEN', '')
        self.domain = os.getenv('AMOCRM_DOMAIN', 'welltech.amocrm.ru')
        self.pipeline_id = int(os.getenv('AMOCRM_PIPELINE_ID', '10154618'))
        self.status_tekshirilmoqda = int(os.getenv('AMOCRM_STATUS_TEKSHIRILMOQDA', '80442678'))
        self.status_qabul_qilindi = int(os.getenv('AMOCRM_STATUS_QABUL_QILINDI', '80442682'))
        self.status_tayyor = int(os.getenv('AMOCRM_STATUS_TAYYOR', '80442686'))
        self.status_yetkazilmoqda = int(os.getenv('AMOCRM_STATUS_YETKAZILMOQDA', '80442690'))
        self.status_yakunlandi = int(os.getenv('AMOCRM_STATUS_YAKUNLANDI', '80442694'))
        self.status_bekor_qilindi = int(os.getenv('AMOCRM_STATUS_BEKOR_QILINDI', '143'))

        self.base_url = f"https://{self.domain}/api/v4"
        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

    def is_configured(self) -> bool:
        """AmoCRM sozlanganligini tekshirish"""
        return bool(self.access_token and self.domain)

    async def get_tekshirilmoqda_leads(self) -> List[Dict[str, Any]]:
        """TEKSHIRILMOQDA statusidagi leadlarni olish"""
        if not self.is_configured():
            logger.warning("AmoCRM is not configured")
            return []

        try:
            url = f"{self.base_url}/leads"
            params = {
                "filter[statuses][0][pipeline_id]": self.pipeline_id,
                "filter[statuses][0][status_id]": self.status_tekshirilmoqda,
                "with": "contacts",
                "limit": 50
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.headers, params=params) as response:
                    if response.status == 401:
                        logger.error("AmoCRM: Unauthorized - token expired")
                        return []

                    if response.status != 200:
                        logger.error(f"AmoCRM API error: {response.status}")
                        return []

                    data = await response.json()
                    leads = data.get('_embedded', {}).get('leads', [])
                    logger.info(f"AmoCRM: Found {len(leads)} TEKSHIRILMOQDA leads")
                    return leads

        except Exception as e:
            logger.error(f"AmoCRM fetch error: {e}")
            return []

    def parse_lead_name(self, lead_name: str) -> Dict[str, Any]:
        """
        Lead nomidan buyurtma ma'lumotlarini ajratib olish
        Format: #1741 | Ixtiyor Suyunov | CASH | 200 001
        """
        result = {
            'order_id': None,
            'customer_name': '',
            'payment_type': '',
            'total': 0
        }

        if not lead_name:
            return result

        parts = [p.strip() for p in lead_name.split('|')]

        # Order ID
        if parts:
            order_match = re.search(r'#(\d+)', parts[0])
            if order_match:
                result['order_id'] = order_match.group(1)

        # Customer name
        if len(parts) > 1:
            result['customer_name'] = parts[1]

        # Payment type
        if len(parts) > 2:
            result['payment_type'] = parts[2]

        # Total amount
        if len(parts) > 3:
            amount_str = parts[3].replace(' ', '').replace(',', '')
            try:
                result['total'] = int(amount_str)
            except ValueError:
                pass

        return result

    async def get_lead_notes(self, lead_id: int) -> List[Dict[str, Any]]:
        """Lead uchun izohlarni olish (buyurtma tafsilotlari)"""
        if not self.is_configured():
            return []

        try:
            url = f"{self.base_url}/leads/{lead_id}/notes"

            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.headers) as response:
                    if response.status != 200:
                        return []

                    data = await response.json()
                    return data.get('_embedded', {}).get('notes', [])

        except Exception as e:
            logger.error(f"Error fetching lead notes: {e}")
            return []

    def parse_order_items_from_notes(self, notes: List[Dict]) -> List[Dict[str, Any]]:
        """Izohlardan buyurtma mahsulotlarini ajratib olish"""
        items = []

        for note in notes:
            note_type = note.get('note_type')
            params = note.get('params', {})

            # common note (text)
            if note_type == 'common':
                text = params.get('text', '')
                # Mahsulotlarni qidirish
                # Format: "Mahsulot nomi - 2x50000"
                lines = text.split('\n')
                for line in lines:
                    if '-' in line and 'x' in line.lower():
                        try:
                            name_part, price_part = line.rsplit('-', 1)
                            name = name_part.strip()

                            # 2x50000 formatini parse qilish
                            price_match = re.search(r'(\d+)\s*[xх]\s*(\d+)', price_part, re.IGNORECASE)
                            if price_match:
                                quantity = int(price_match.group(1))
                                price = int(price_match.group(2))
                                items.append({
                                    'name': name,
                                    'price': price,
                                    'quantity': quantity
                                })
                        except:
                            pass

        return items

    async def update_lead_status(self, lead_id: int, status: str) -> bool:
        """Lead statusini yangilash"""
        if not self.is_configured():
            return False

        status_id = None
        if status == 'accepted':
            status_id = self.status_qabul_qilindi
        elif status == 'cancelled':
            status_id = self.status_bekor_qilindi
        elif status == 'ready':
            status_id = self.status_tayyor
        elif status == 'delivering':
            status_id = self.status_yetkazilmoqda
        elif status == 'completed':
            status_id = self.status_yakunlandi

        if not status_id:
            logger.error(f"Unknown status: {status}")
            return False

        try:
            url = f"{self.base_url}/leads/{lead_id}"
            payload = {
                "status_id": status_id
            }

            async with aiohttp.ClientSession() as session:
                async with session.patch(url, headers=self.headers, json=payload) as response:
                    if response.status == 200:
                        logger.info(f"Lead {lead_id} status updated to {status}")
                        return True
                    else:
                        text = await response.text()
                        logger.error(f"Failed to update lead status: {response.status} - {text}")
                        return False

        except Exception as e:
            logger.error(f"Error updating lead status: {e}")
            return False

    def parse_business_from_notes(self, notes: List[Dict]) -> str:
        """Notes dan biznes nomini ajratib olish"""
        for note in notes:
            note_type = note.get('note_type')
            if note_type == 'common':
                text = note.get('params', {}).get('text', '')
                # "BIZNES:" bo'limini qidirish
                if 'BIZNES:' in text:
                    # "Nomi: Milliy" ni topish
                    lines = text.split('\n')
                    for i, line in enumerate(lines):
                        if 'Nomi:' in line:
                            # "Nomi: Milliy" -> "Milliy"
                            business_name = line.split('Nomi:')[-1].strip()
                            return business_name
        return ''

    async def get_orders_for_notification(self, business_filter: str = None) -> List[Dict[str, Any]]:
        """
        Notification uchun tayyor buyurtmalar ro'yxatini olish

        Args:
            business_filter: Faqat shu biznes nomiga tegishli buyurtmalarni olish (masalan: "Milliy")
        """
        leads = await self.get_tekshirilmoqda_leads()
        orders = []

        for lead in leads:
            lead_id = lead.get('id')
            lead_name = lead.get('name', '')
            price = lead.get('price', 0)

            # Lead nomidan ma'lumotlarni parse qilish
            parsed = self.parse_lead_name(lead_name)

            # Agar price bor bo'lsa, uni ishlatish
            total = price if price else parsed.get('total', 0)

            # Notes dan biznes nomini olish
            notes = await self.get_lead_notes(lead_id)
            business_name = self.parse_business_from_notes(notes)

            # Biznes filtri qo'llanilgan bo'lsa, faqat shu biznesga tegishlilarni olish
            if business_filter and business_name != business_filter:
                logger.debug(f"Lead {lead_id} skipped: business '{business_name}' != filter '{business_filter}'")
                continue

            # Contact ma'lumotlarini olish
            contacts = lead.get('_embedded', {}).get('contacts', [])
            customer_phone = ''
            if contacts:
                # Birinchi contactning telefonini olish
                contact_id = contacts[0].get('id')
                if contact_id:
                    contact_info = await self._get_contact_info(contact_id)
                    customer_phone = contact_info.get('phone', '')

            order_data = {
                'id': parsed.get('order_id') or str(lead_id),
                'amocrm_lead_id': lead_id,
                'business_name': business_name,
                'customer': {
                    'name': parsed.get('customer_name', f"Mijoz #{parsed.get('order_id', lead_id)}"),
                    'phone': customer_phone
                },
                'payment_type': parsed.get('payment_type', 'CASH'),
                'total': total,
                'items': [],  # Keyinroq notesdan olish mumkin
                'delivery_address': '',
                'status': 'new'
            }

            orders.append(order_data)

        return orders

    async def _get_contact_info(self, contact_id: int) -> Dict[str, Any]:
        """Contact ma'lumotlarini olish"""
        result = {'phone': '', 'name': ''}

        try:
            url = f"{self.base_url}/contacts/{contact_id}"

            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.headers) as response:
                    if response.status != 200:
                        return result

                    data = await response.json()

                    # Telefon raqamini custom_fields dan olish
                    custom_fields = data.get('custom_fields_values', [])
                    for field in custom_fields:
                        if field.get('field_code') == 'PHONE':
                            values = field.get('values', [])
                            if values:
                                result['phone'] = values[0].get('value', '')
                                break

                    result['name'] = data.get('name', '')
                    return result

        except Exception as e:
            logger.error(f"Error fetching contact info: {e}")
            return result
