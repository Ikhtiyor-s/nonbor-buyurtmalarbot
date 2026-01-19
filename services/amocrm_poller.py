"""
AmoCRM API Poller Service
AmoCRM dan leadlarni polling qilish va Telegram ga yuborish
"""
import os
import logging
import asyncio
import aiohttp
from datetime import datetime
from typing import List, Dict, Any, Set

from bot.core import NotificationBot

logger = logging.getLogger('bot')


class AmoCRMPoller:
    """
    AmoCRM API dan leadlarni polling qilish
    """

    def __init__(self):
        self.access_token = os.getenv('AMOCRM_ACCESS_TOKEN', '')
        self.api_domain = os.getenv('AMOCRM_API_DOMAIN', 'api-b.amocrm.ru')
        self.poll_interval = int(os.getenv('AMOCRM_POLL_INTERVAL', '30'))
        self.processed_leads: Set[int] = set()
        self._running = False

        # Pipeline va status filterlari (ixtiyoriy)
        self.allowed_pipeline_ids = []  # Bo'sh = hammasi
        self.allowed_status_ids = []    # Bo'sh = hammasi

    @property
    def base_url(self):
        return f"https://{self.api_domain}"

    @property
    def headers(self):
        return {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

    async def start_polling(self):
        """
        AmoCRM dan leadlarni muntazam tekshirib turish
        """
        print(f"[AMOCRM] AmoCRM API poller ishga tushdi")
        print(f"[AMOCRM] API Domain: {self.api_domain}")
        print(f"[AMOCRM] Interval: {self.poll_interval} sekund")

        self._running = True

        while self._running:
            try:
                await self._poll_leads()
                await asyncio.sleep(self.poll_interval)
            except asyncio.CancelledError:
                print("[AMOCRM] Poller to'xtatildi")
                break
            except Exception as e:
                logger.error(f"AmoCRM Polling error: {e}")
                print(f"[AMOCRM] Xatolik: {e}")
                await asyncio.sleep(60)

    def stop(self):
        """Polling ni to'xtatish"""
        self._running = False

    async def _poll_leads(self):
        """
        AmoCRM dan leadlarni olish
        """
        try:
            async with aiohttp.ClientSession() as session:
                # Leadlarni olish
                url = f"{self.base_url}/api/v4/leads"
                params = {
                    'limit': 50,
                    'order[created_at]': 'desc',
                    'with': 'contacts,companies'
                }

                async with session.get(url, headers=self.headers, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        leads = data.get('_embedded', {}).get('leads', [])

                        if leads:
                            new_leads = []
                            for lead in leads:
                                lead_id = lead.get('id')

                                if lead_id not in self.processed_leads:
                                    # Pipeline filter
                                    if self.allowed_pipeline_ids:
                                        if lead.get('pipeline_id') not in self.allowed_pipeline_ids:
                                            continue

                                    # Status filter
                                    if self.allowed_status_ids:
                                        if lead.get('status_id') not in self.allowed_status_ids:
                                            continue

                                    new_leads.append(lead)

                            if new_leads:
                                print(f"[AMOCRM] {len(new_leads)} ta yangi lead topildi")
                                await self._process_leads(new_leads, session)

                    elif response.status == 401:
                        logger.error("AmoCRM: Token yaroqsiz yoki muddati tugagan")
                        print("[AMOCRM] XATO: Token yaroqsiz!")
                    else:
                        text = await response.text()
                        logger.warning(f"AmoCRM API returned status {response.status}: {text}")

        except aiohttp.ClientError as e:
            logger.error(f"AmoCRM connection error: {e}")
        except Exception as e:
            logger.error(f"AmoCRM request failed: {e}")

    async def _process_leads(self, leads: List[Dict[str, Any]], session: aiohttp.ClientSession):
        """
        Leadlarni qayta ishlash va Telegram ga yuborish
        """
        bot = NotificationBot()

        for lead in leads:
            lead_id = lead.get('id')

            try:
                # Kontakt ma'lumotlarini olish
                contact_info = await self._get_contact_info(lead, session)

                # Lead ni standart formatga o'tkazish
                normalized = self._normalize_lead(lead, contact_info)

                # Telegram ga yuborish
                success = await bot.send_order_notification(normalized)

                if success:
                    self.processed_leads.add(lead_id)
                    print(f"[AMOCRM] Lead #{lead_id} yuborildi")

                    # Memory leak prevention
                    if len(self.processed_leads) > 10000:
                        self.processed_leads = set(list(self.processed_leads)[-5000:])

            except Exception as e:
                logger.error(f"Error processing lead {lead_id}: {e}")

    async def _get_contact_info(self, lead: Dict[str, Any], session: aiohttp.ClientSession) -> Dict[str, Any]:
        """
        Lead bilan bog'liq kontakt ma'lumotlarini olish
        """
        contact_info = {
            'name': '',
            'phone': '',
            'email': ''
        }

        try:
            # Embedded contacts
            contacts = lead.get('_embedded', {}).get('contacts', [])

            if contacts:
                contact_id = contacts[0].get('id')

                # Kontakt tafsilotlarini olish
                url = f"{self.base_url}/api/v4/contacts/{contact_id}"

                async with session.get(url, headers=self.headers) as response:
                    if response.status == 200:
                        contact = await response.json()

                        contact_info['name'] = contact.get('name', '')

                        # Custom fields dan telefon va email olish
                        custom_fields = contact.get('custom_fields_values', [])
                        for field in custom_fields:
                            field_code = field.get('field_code', '')
                            values = field.get('values', [])

                            if values:
                                if field_code == 'PHONE':
                                    contact_info['phone'] = values[0].get('value', '')
                                elif field_code == 'EMAIL':
                                    contact_info['email'] = values[0].get('value', '')

        except Exception as e:
            logger.error(f"Error getting contact info: {e}")

        return contact_info

    def _normalize_lead(self, lead: Dict[str, Any], contact_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        AmoCRM lead formatini standart buyurtma formatiga o'tkazish
        """
        # Lead ma'lumotlari
        lead_id = lead.get('id')
        lead_name = lead.get('name', f'Lead #{lead_id}')
        price = lead.get('price', 0)

        # Pipeline va status
        pipeline_id = lead.get('pipeline_id')
        status_id = lead.get('status_id')

        # Custom fields
        custom_fields = lead.get('custom_fields_values', [])
        address = ''
        notes_parts = []

        for field in custom_fields:
            field_name = field.get('field_name', '')
            values = field.get('values', [])

            if values:
                value = values[0].get('value', '')

                # Manzil maydonlarini topish
                if 'адрес' in field_name.lower() or 'manzil' in field_name.lower() or 'address' in field_name.lower():
                    address = value
                else:
                    notes_parts.append(f"{field_name}: {value}")

        # Tags
        tags = lead.get('_embedded', {}).get('tags', [])
        if tags:
            tag_names = [t.get('name', '') for t in tags]
            notes_parts.append(f"Teglar: {', '.join(tag_names)}")

        # Company
        companies = lead.get('_embedded', {}).get('companies', [])
        if companies:
            company_name = companies[0].get('name', '')
            if company_name:
                notes_parts.append(f"Kompaniya: {company_name}")

        # Created at
        created_at = lead.get('created_at', 0)
        if created_at:
            created_at = datetime.fromtimestamp(created_at).isoformat()
        else:
            created_at = datetime.now().isoformat()

        return {
            'id': str(lead_id),
            'status': 'new',
            'customer': {
                'name': contact_info.get('name') or lead_name,
                'phone': contact_info.get('phone', ''),
                'email': contact_info.get('email', ''),
                'address': address
            },
            'total': price,
            'items': [
                {
                    'name': lead_name,
                    'price': price,
                    'quantity': 1
                }
            ],
            'notes': '\n'.join(notes_parts) if notes_parts else '',
            'created_at': created_at,
            'source': 'amocrm',
            'pipeline_id': pipeline_id,
            'status_id': status_id
        }

    async def get_pipelines(self) -> List[Dict[str, Any]]:
        """
        Barcha pipeline larni olish (sozlash uchun)
        """
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.base_url}/api/v4/leads/pipelines"

                async with session.get(url, headers=self.headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get('_embedded', {}).get('pipelines', [])
                    else:
                        logger.error(f"Failed to get pipelines: {response.status}")
                        return []
        except Exception as e:
            logger.error(f"Error getting pipelines: {e}")
            return []

    async def get_users(self) -> List[Dict[str, Any]]:
        """
        Barcha foydalanuvchilarni olish
        """
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.base_url}/api/v4/users"

                async with session.get(url, headers=self.headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get('_embedded', {}).get('users', [])
                    else:
                        return []
        except Exception as e:
            logger.error(f"Error getting users: {e}")
            return []


async def run_amocrm_poller():
    """
    Standalone AmoCRM poller ishga tushirish
    """
    poller = AmoCRMPoller()
    await poller.start_polling()


if __name__ == '__main__':
    import django
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    django.setup()

    asyncio.run(run_amocrm_poller())
