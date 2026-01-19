import uuid
from datetime import datetime
import json
import os
import re

# Simple file-based storage (Django o'rniga)
DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')

def ensure_data_dir():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)


def load_regions_data():
    """Viloyatlar ma'lumotlarini yuklash"""
    regions_file = os.path.join(DATA_DIR, 'regions.json')
    if os.path.exists(regions_file):
        with open(regions_file, 'r', encoding='utf-8') as f:
            return json.load(f).get('regions', [])
    return []


def detect_region_district(address):
    """
    Manzil matnidan viloyat va tumanni aniqlash
    Returns: (region_id, district_id)
    """
    if not address:
        return ('', '')

    address_lower = address.lower()

    # Maxsus belgilarni normallashtirish
    address_normalized = address_lower.replace('\u02bb', "'").replace('\u2018', "'").replace('\u2019', "'").replace('`', "'")

    regions = load_regions_data()

    detected_region = ''
    detected_district = ''

    # Tuman nomlari va ularning variantlari
    district_keywords = {
        # Toshkent shahar tumanlari
        'bektemir': ('toshkent_shahar', 'bektemir'),
        'chilonzor': ('toshkent_shahar', 'chilonzor'),
        'chilanzor': ('toshkent_shahar', 'chilonzor'),
        'yashnobod': ('toshkent_shahar', 'yashnobod'),
        'yashnaobod': ('toshkent_shahar', 'yashnobod'),
        'mirobod': ('toshkent_shahar', 'mirobod'),
        'mirabad': ('toshkent_shahar', 'mirobod'),
        'mirzo ulug': ('toshkent_shahar', 'mirzo_ulugbek'),
        'mirzo-ulug': ('toshkent_shahar', 'mirzo_ulugbek'),
        'ulugbek': ('toshkent_shahar', 'mirzo_ulugbek'),
        'ulug\'bek': ('toshkent_shahar', 'mirzo_ulugbek'),
        'sergeli': ('toshkent_shahar', 'sergeli'),
        'shayxontohur': ('toshkent_shahar', 'shayxontohur'),
        'shayxontoxur': ('toshkent_shahar', 'shayxontohur'),
        'olmazar': ('toshkent_shahar', 'olmazar'),
        'olmazor': ('toshkent_shahar', 'olmazar'),
        'uchtepa': ('toshkent_shahar', 'uchtepa'),
        'yakkasaroy': ('toshkent_shahar', 'yakkasaroy'),
        'yakka saroy': ('toshkent_shahar', 'yakkasaroy'),
        'yunusobod': ('toshkent_shahar', 'yunusobod'),
        'yunusabad': ('toshkent_shahar', 'yunusobod'),

        # Toshkent viloyati tumanlari
        'qibray': ('toshkent_viloyati', 'qibray'),
        'kibray': ('toshkent_viloyati', 'qibray'),
        'chirchiq': ('toshkent_viloyati', 'chirchiq'),
        'olmaliq': ('toshkent_viloyati', 'olmaliq'),
        'angren': ('toshkent_viloyati', 'angren'),
        'ohangaron': ('toshkent_viloyati', 'ohangaron'),
        'bekobod': ('toshkent_viloyati', 'bekobod'),
        'bo\'stonliq': ('toshkent_viloyati', 'bostonliq'),
        'bostonliq': ('toshkent_viloyati', 'bostonliq'),
        'zangiota': ('toshkent_viloyati', 'zangiota'),
        'parkent': ('toshkent_viloyati', 'parkent'),
        'piskent': ('toshkent_viloyati', 'piskent'),
        'chinoz': ('toshkent_viloyati', 'chinoz'),

        # Samarqand
        'samarqand': ('samarqand', 'samarqand_shahar'),
        'samarkand': ('samarqand', 'samarqand_shahar'),
        'urgut': ('samarqand', 'urgut'),
        'kattaqo\'rg\'on': ('samarqand', 'kattaqorgon'),

        # Buxoro
        'buxoro': ('buxoro', 'buxoro_shahar'),
        'bukhara': ('buxoro', 'buxoro_shahar'),

        # Farg'ona
        'farg\'ona': ('fargona', 'fargona_shahar'),
        'fergana': ('fargona', 'fargona_shahar'),
        'fargona': ('fargona', 'fargona_shahar'),
        'qo\'qon': ('fargona', 'qoqon'),
        'kokand': ('fargona', 'qoqon'),
        'marg\'ilon': ('fargona', 'marg\'ilon'),
        'margilan': ('fargona', 'marg\'ilon'),

        # Andijon
        'andijon': ('andijon', 'andijon_shahar'),
        'andijan': ('andijon', 'andijon_shahar'),

        # Namangan
        'namangan': ('namangan', 'namangan_shahar'),

        # Xorazm
        'urganch': ('xorazm', 'urganch_shahar'),
        'xiva': ('xorazm', 'xiva'),
        'khiva': ('xorazm', 'xiva'),

        # Navoiy
        'navoiy': ('navoiy', 'navoiy_shahar'),

        # Qashqadaryo
        'qarshi': ('qashqadaryo', 'qarshi_shahar'),
        'karshi': ('qashqadaryo', 'qarshi_shahar'),
        'shahrisabz': ('qashqadaryo', 'shahrisabz'),

        # Surxondaryo
        'termiz': ('surxondaryo', 'termiz_shahar'),
        'termez': ('surxondaryo', 'termiz_shahar'),

        # Jizzax
        'jizzax': ('jizzax', 'jizzax_shahar'),

        # Sirdaryo
        'guliston': ('sirdaryo', 'guliston_shahar'),

        # Qoraqalpog'iston
        'nukus': ('qoraqalpogiston', 'nukus_shahar'),
    }

    # Avval tumanlarni qidirish (aniqroq)
    for keyword, (region, district) in district_keywords.items():
        if keyword in address_normalized:
            detected_region = region
            detected_district = district
            break

    # Agar tuman topilmasa, viloyatni qidirish
    if not detected_region:
        region_keywords = {
            'toshkent': 'toshkent_shahar',
            'tashkent': 'toshkent_shahar',
            'samarqand': 'samarqand',
            'buxoro': 'buxoro',
            'farg\'ona': 'fargona',
            'fergana': 'fargona',
            'andijon': 'andijon',
            'namangan': 'namangan',
            'xorazm': 'xorazm',
            'navoiy': 'navoiy',
            'qashqadaryo': 'qashqadaryo',
            'surxondaryo': 'surxondaryo',
            'jizzax': 'jizzax',
            'sirdaryo': 'sirdaryo',
            'qoraqalpog': 'qoraqalpogiston',
        }

        for keyword, region in region_keywords.items():
            if keyword in address_normalized:
                detected_region = region
                break

    return (detected_region, detected_district)

class Seller:
    """Sotuvchi modeli"""

    def __init__(self, id=None, phone='', full_name='', telegram_user_id='',
                 group_chat_id='', group_invite_link='', group_title='',
                 is_active=True, created_at=None, api_identifier='',
                 address='', lat=None, long=None, region='', district=''):
        self.id = id or str(uuid.uuid4())
        self.phone = phone
        self.full_name = full_name
        self.telegram_user_id = telegram_user_id
        self.group_chat_id = group_chat_id
        self.group_invite_link = group_invite_link
        self.group_title = group_title
        self.is_active = is_active
        self.created_at = created_at or datetime.now().isoformat()
        self.api_identifier = api_identifier
        self.address = address
        self.lat = lat
        self.long = long
        self.region = region
        self.district = district

    def to_dict(self):
        return {
            'id': self.id,
            'phone': self.phone,
            'full_name': self.full_name,
            'telegram_user_id': self.telegram_user_id,
            'group_chat_id': self.group_chat_id,
            'group_invite_link': self.group_invite_link,
            'group_title': self.group_title,
            'is_active': self.is_active,
            'created_at': self.created_at,
            'api_identifier': self.api_identifier,
            'address': self.address,
            'lat': self.lat,
            'long': self.long,
            'region': self.region,
            'district': self.district
        }
    
    @classmethod
    def from_dict(cls, data):
        return cls(**data)
    
    def save(self):
        ensure_data_dir()

        # Agar region/district bo'sh bo'lsa, manzildan avtomatik aniqlash
        if self.address and (not self.region or not self.district):
            detected_region, detected_district = detect_region_district(self.address)
            if detected_region and not self.region:
                self.region = detected_region
            if detected_district and not self.district:
                self.district = detected_district

        sellers = Seller.load_all()

        # Mavjud bo'lsa yangilash
        found = False
        for i, s in enumerate(sellers):
            if s['id'] == self.id:
                sellers[i] = self.to_dict()
                found = True
                break

        if not found:
            sellers.append(self.to_dict())

        with open(os.path.join(DATA_DIR, 'sellers.json'), 'w', encoding='utf-8') as f:
            json.dump(sellers, f, ensure_ascii=False, indent=2)
    
    @classmethod
    def load_all(cls):
        ensure_data_dir()
        filepath = os.path.join(DATA_DIR, 'sellers.json')
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        return []
    
    @classmethod
    def get(cls, **kwargs):
        sellers = cls.load_all()
        for s in sellers:
            match = True
            for key, value in kwargs.items():
                if s.get(key) != value:
                    match = False
                    break
            if match:
                return cls.from_dict(s)
        return None
    
    @classmethod
    def filter(cls, **kwargs):
        sellers = cls.load_all()
        result = []
        for s in sellers:
            match = True
            for key, value in kwargs.items():
                if s.get(key) != value:
                    match = False
                    break
            if match:
                result.append(cls.from_dict(s))
        return result


class Order:
    """Buyurtma modeli"""

    # Buyurtma turlari
    DELIVERY_TYPE_PICKUP = 'pickup'      # O'zim olib ketaman
    DELIVERY_TYPE_DELIVERY = 'delivery'  # Yetkazib berish

    def __init__(self, id=None, external_id='', seller_id=None, status='new',
                 customer_name='', customer_phone='', total_amount=0,
                 items=None, telegram_message_id='', notified_at=None,
                 created_at=None, updated_at=None, amocrm_lead_id=None,
                 delivery_address='', delivery_type='delivery'):
        self.id = id or str(uuid.uuid4())
        self.external_id = external_id
        self.seller_id = seller_id
        self.status = status
        self.customer_name = customer_name
        self.customer_phone = customer_phone
        self.total_amount = total_amount
        self.items = items or []
        self.telegram_message_id = telegram_message_id
        self.notified_at = notified_at
        self.created_at = created_at or datetime.now().isoformat()
        self.updated_at = updated_at or datetime.now().isoformat()
        self.amocrm_lead_id = amocrm_lead_id  # AmoCRM lead ID (status yangilash uchun)
        self.delivery_address = delivery_address  # Yetkazib berish manzili
        self.delivery_type = delivery_type  # 'pickup' yoki 'delivery'

    def to_dict(self):
        return {
            'id': self.id,
            'external_id': self.external_id,
            'seller_id': self.seller_id,
            'status': self.status,
            'customer_name': self.customer_name,
            'customer_phone': self.customer_phone,
            'total_amount': self.total_amount,
            'items': self.items,
            'telegram_message_id': self.telegram_message_id,
            'notified_at': self.notified_at,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'amocrm_lead_id': self.amocrm_lead_id,
            'delivery_address': self.delivery_address,
            'delivery_type': self.delivery_type
        }
    
    @classmethod
    def from_dict(cls, data):
        return cls(**data)
    
    def save(self):
        ensure_data_dir()
        self.updated_at = datetime.now().isoformat()
        orders = Order.load_all()
        
        found = False
        for i, o in enumerate(orders):
            if o['id'] == self.id or o['external_id'] == self.external_id:
                orders[i] = self.to_dict()
                found = True
                break
        
        if not found:
            orders.append(self.to_dict())
        
        with open(os.path.join(DATA_DIR, 'orders.json'), 'w', encoding='utf-8') as f:
            json.dump(orders, f, ensure_ascii=False, indent=2)
    
    @classmethod
    def load_all(cls):
        ensure_data_dir()
        filepath = os.path.join(DATA_DIR, 'orders.json')
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        return []
    
    @classmethod
    def get(cls, **kwargs):
        orders = cls.load_all()
        for o in orders:
            match = True
            for key, value in kwargs.items():
                if o.get(key) != value:
                    match = False
                    break
            if match:
                return cls.from_dict(o)
        return None
    
    @classmethod
    def filter(cls, **kwargs):
        orders = cls.load_all()
        result = []
        for o in orders:
            match = True
            for key, value in kwargs.items():
                if o.get(key) != value:
                    match = False
                    break
            if match:
                result.append(cls.from_dict(o))
        return result


class OTPRequest:
    """OTP so'rovi modeli"""

    def __init__(self, id=None, phone='', otp_code='', telegram_user_id='',
                 delivery_method='telegram', is_verified=False, is_expired=False,
                 attempts=0, created_at=None, expires_at=None, verified_at=None,
                 ip_address=''):
        self.id = id or str(uuid.uuid4())
        self.phone = phone
        self.otp_code = otp_code
        self.telegram_user_id = telegram_user_id
        self.delivery_method = delivery_method  # 'telegram' or 'sms'
        self.is_verified = is_verified
        self.is_expired = is_expired
        self.attempts = attempts
        self.created_at = created_at or datetime.now().isoformat()
        self.expires_at = expires_at
        self.verified_at = verified_at
        self.ip_address = ip_address

    def to_dict(self):
        return {
            'id': self.id,
            'phone': self.phone,
            'otp_code': self.otp_code,
            'telegram_user_id': self.telegram_user_id,
            'delivery_method': self.delivery_method,
            'is_verified': self.is_verified,
            'is_expired': self.is_expired,
            'attempts': self.attempts,
            'created_at': self.created_at,
            'expires_at': self.expires_at,
            'verified_at': self.verified_at,
            'ip_address': self.ip_address
        }

    @classmethod
    def from_dict(cls, data):
        return cls(**data)

    def save(self):
        ensure_data_dir()
        requests = OTPRequest.load_all()

        found = False
        for i, r in enumerate(requests):
            if r['id'] == self.id:
                requests[i] = self.to_dict()
                found = True
                break

        if not found:
            requests.append(self.to_dict())

        with open(os.path.join(DATA_DIR, 'otp_requests.json'), 'w', encoding='utf-8') as f:
            json.dump(requests, f, ensure_ascii=False, indent=2)

    @classmethod
    def load_all(cls):
        ensure_data_dir()
        filepath = os.path.join(DATA_DIR, 'otp_requests.json')
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        return []

    @classmethod
    def get(cls, **kwargs):
        requests = cls.load_all()
        for r in requests:
            match = True
            for key, value in kwargs.items():
                if r.get(key) != value:
                    match = False
                    break
            if match:
                return cls.from_dict(r)
        return None

    @classmethod
    def filter(cls, **kwargs):
        requests = cls.load_all()
        result = []
        for r in requests:
            match = True
            for key, value in kwargs.items():
                if r.get(key) != value:
                    match = False
                    break
            if match:
                result.append(cls.from_dict(r))
        return result


class SecurityLog:
    """Xavfsizlik log modeli"""

    LOG_TYPES = {
        'otp_sent': 'OTP yuborildi',
        'otp_verified': 'OTP tasdiqlandi',
        'otp_failed': 'OTP noto\'g\'ri',
        'rate_limit': 'Rate limit',
        'blocked': 'Bloklandi',
        'suspicious': 'Shubhali harakat'
    }

    def __init__(self, id=None, log_type='', phone='', telegram_user_id='',
                 ip_address='', details='', created_at=None):
        self.id = id or str(uuid.uuid4())
        self.log_type = log_type
        self.phone = phone
        self.telegram_user_id = telegram_user_id
        self.ip_address = ip_address
        self.details = details
        self.created_at = created_at or datetime.now().isoformat()

    def to_dict(self):
        return {
            'id': self.id,
            'log_type': self.log_type,
            'phone': self.phone,
            'telegram_user_id': self.telegram_user_id,
            'ip_address': self.ip_address,
            'details': self.details,
            'created_at': self.created_at
        }

    @classmethod
    def from_dict(cls, data):
        return cls(**data)

    def save(self):
        ensure_data_dir()
        logs = SecurityLog.load_all()
        logs.append(self.to_dict())

        # Faqat oxirgi 1000 ta logni saqlash
        if len(logs) > 1000:
            logs = logs[-1000:]

        with open(os.path.join(DATA_DIR, 'security_logs.json'), 'w', encoding='utf-8') as f:
            json.dump(logs, f, ensure_ascii=False, indent=2)

    @classmethod
    def load_all(cls):
        ensure_data_dir()
        filepath = os.path.join(DATA_DIR, 'security_logs.json')
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        return []

    @classmethod
    def filter_by_date(cls, start_date, end_date=None):
        logs = cls.load_all()
        result = []
        for log in logs:
            log_date = datetime.fromisoformat(log['created_at']).date()
            if log_date >= start_date:
                if end_date is None or log_date <= end_date:
                    result.append(cls.from_dict(log))
        return result


class BlockedIP:
    """Bloklangan IP modeli"""

    def __init__(self, id=None, ip_address='', reason='', blocked_until=None,
                 created_at=None):
        self.id = id or str(uuid.uuid4())
        self.ip_address = ip_address
        self.reason = reason
        self.blocked_until = blocked_until
        self.created_at = created_at or datetime.now().isoformat()

    def to_dict(self):
        return {
            'id': self.id,
            'ip_address': self.ip_address,
            'reason': self.reason,
            'blocked_until': self.blocked_until,
            'created_at': self.created_at
        }

    @classmethod
    def from_dict(cls, data):
        return cls(**data)

    def save(self):
        ensure_data_dir()
        blocked = BlockedIP.load_all()

        found = False
        for i, b in enumerate(blocked):
            if b['ip_address'] == self.ip_address:
                blocked[i] = self.to_dict()
                found = True
                break

        if not found:
            blocked.append(self.to_dict())

        with open(os.path.join(DATA_DIR, 'blocked_ips.json'), 'w', encoding='utf-8') as f:
            json.dump(blocked, f, ensure_ascii=False, indent=2)

    @classmethod
    def load_all(cls):
        ensure_data_dir()
        filepath = os.path.join(DATA_DIR, 'blocked_ips.json')
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        return []

    @classmethod
    def is_blocked(cls, ip_address):
        blocked = cls.load_all()
        now = datetime.now()
        for b in blocked:
            if b['ip_address'] == ip_address:
                if b['blocked_until']:
                    blocked_until = datetime.fromisoformat(b['blocked_until'])
                    if now < blocked_until:
                        return True
                else:
                    return True
        return False

    @classmethod
    def unblock(cls, ip_address):
        blocked = cls.load_all()
        blocked = [b for b in blocked if b['ip_address'] != ip_address]
        with open(os.path.join(DATA_DIR, 'blocked_ips.json'), 'w', encoding='utf-8') as f:
            json.dump(blocked, f, ensure_ascii=False, indent=2)


class Staff:
    """Xodimlar modeli"""

    ROLES = {
        'manager': 'Menejer',
        'cook': 'Oshpaz',
        'courier': 'Yetkazuvchi',
        'staff': 'Xodim'
    }

    def __init__(self, id=None, seller_id='', staff_id='', full_name='', phone='',
                 telegram_user_id='', role='staff', is_active=True,
                 created_at=None, updated_at=None):
        self.id = id or str(uuid.uuid4())
        self.seller_id = seller_id
        self.staff_id = staff_id  # Xodim ID raqami (001, 002, ...)
        self.full_name = full_name
        self.phone = phone
        self.telegram_user_id = telegram_user_id
        self.role = role
        self.is_active = is_active
        self.created_at = created_at or datetime.now().isoformat()
        self.updated_at = updated_at or datetime.now().isoformat()

    def to_dict(self):
        return {
            'id': self.id,
            'seller_id': self.seller_id,
            'staff_id': self.staff_id,
            'full_name': self.full_name,
            'phone': self.phone,
            'telegram_user_id': self.telegram_user_id,
            'role': self.role,
            'is_active': self.is_active,
            'created_at': self.created_at,
            'updated_at': self.updated_at
        }

    @classmethod
    def from_dict(cls, data):
        return cls(**data)

    def save(self):
        ensure_data_dir()
        self.updated_at = datetime.now().isoformat()
        staff_list = Staff.load_all()

        found = False
        for i, s in enumerate(staff_list):
            if s['id'] == self.id:
                staff_list[i] = self.to_dict()
                found = True
                break

        if not found:
            staff_list.append(self.to_dict())

        with open(os.path.join(DATA_DIR, 'staff.json'), 'w', encoding='utf-8') as f:
            json.dump(staff_list, f, ensure_ascii=False, indent=2)

    @classmethod
    def load_all(cls):
        ensure_data_dir()
        filepath = os.path.join(DATA_DIR, 'staff.json')
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        return []

    @classmethod
    def get(cls, **kwargs):
        staff_list = cls.load_all()
        for s in staff_list:
            match = True
            for key, value in kwargs.items():
                if s.get(key) != value:
                    match = False
                    break
            if match:
                return cls.from_dict(s)
        return None

    @classmethod
    def filter(cls, **kwargs):
        staff_list = cls.load_all()
        result = []
        for s in staff_list:
            match = True
            for key, value in kwargs.items():
                if s.get(key) != value:
                    match = False
                    break
            if match:
                result.append(cls.from_dict(s))
        return result


class PhoneRegistry:
    """
    Telefon raqam va Telegram user ID bog'lanishi.
    Foydalanuvchi /start bosib telefon yuborsa, shu yerda saqlanadi.
    OTP yuborishda aynan shu telegram_user_id ga yuboriladi.
    """

    def __init__(self, id=None, phone='', telegram_user_id='', telegram_username='',
                 full_name='', is_verified=False, created_at=None, updated_at=None):
        self.id = id or str(uuid.uuid4())
        self.phone = phone
        self.telegram_user_id = telegram_user_id
        self.telegram_username = telegram_username
        self.full_name = full_name
        self.is_verified = is_verified
        self.created_at = created_at or datetime.now().isoformat()
        self.updated_at = updated_at or datetime.now().isoformat()

    def to_dict(self):
        return {
            'id': self.id,
            'phone': self.phone,
            'telegram_user_id': self.telegram_user_id,
            'telegram_username': self.telegram_username,
            'full_name': self.full_name,
            'is_verified': self.is_verified,
            'created_at': self.created_at,
            'updated_at': self.updated_at
        }

    @classmethod
    def from_dict(cls, data):
        return cls(**data)

    def save(self):
        ensure_data_dir()
        self.updated_at = datetime.now().isoformat()
        registry = PhoneRegistry.load_all()

        found = False
        for i, r in enumerate(registry):
            # Telefon yoki telegram_user_id bo'yicha yangilash
            if r['phone'] == self.phone or r['telegram_user_id'] == self.telegram_user_id:
                registry[i] = self.to_dict()
                found = True
                break

        if not found:
            registry.append(self.to_dict())

        with open(os.path.join(DATA_DIR, 'phone_registry.json'), 'w', encoding='utf-8') as f:
            json.dump(registry, f, ensure_ascii=False, indent=2)

    @classmethod
    def load_all(cls):
        ensure_data_dir()
        filepath = os.path.join(DATA_DIR, 'phone_registry.json')
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        return []

    @classmethod
    def get_by_phone(cls, phone: str):
        """Telefon raqam bo'yicha topish"""
        registry = cls.load_all()
        for r in registry:
            if r['phone'] == phone:
                return cls.from_dict(r)
        return None

    @classmethod
    def get_by_telegram_id(cls, telegram_user_id: str):
        """Telegram user ID bo'yicha topish"""
        registry = cls.load_all()
        for r in registry:
            if r['telegram_user_id'] == telegram_user_id:
                return cls.from_dict(r)
        return None

    @classmethod
    def get(cls, **kwargs):
        registry = cls.load_all()
        for r in registry:
            match = True
            for key, value in kwargs.items():
                if r.get(key) != value:
                    match = False
                    break
            if match:
                return cls.from_dict(r)
        return None


class NotificationTemplate:
    """Xabarnoma shablon modeli"""

    def __init__(self, id=None, title='', content='', order_num=0,
                 created_at=None, updated_at=None):
        self.id = id or str(uuid.uuid4())
        self.title = title
        self.content = content
        self.order_num = order_num
        self.created_at = created_at or datetime.now().isoformat()
        self.updated_at = updated_at or datetime.now().isoformat()

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'content': self.content,
            'order_num': self.order_num,
            'created_at': self.created_at,
            'updated_at': self.updated_at
        }

    @classmethod
    def from_dict(cls, data):
        return cls(**data)

    def save(self):
        ensure_data_dir()
        self.updated_at = datetime.now().isoformat()
        templates = NotificationTemplate.load_all()

        found = False
        for i, t in enumerate(templates):
            if t['id'] == self.id:
                templates[i] = self.to_dict()
                found = True
                break

        if not found:
            # Yangi shablonga tartib raqam berish
            if self.order_num == 0:
                max_order = max([t.get('order_num', 0) for t in templates], default=0)
                self.order_num = max_order + 1
            templates.append(self.to_dict())

        with open(os.path.join(DATA_DIR, 'notification_templates.json'), 'w', encoding='utf-8') as f:
            json.dump(templates, f, ensure_ascii=False, indent=2)

    def delete(self):
        """Shablonni o'chirish"""
        ensure_data_dir()
        templates = NotificationTemplate.load_all()
        templates = [t for t in templates if t['id'] != self.id]

        with open(os.path.join(DATA_DIR, 'notification_templates.json'), 'w', encoding='utf-8') as f:
            json.dump(templates, f, ensure_ascii=False, indent=2)

    @classmethod
    def load_all(cls):
        ensure_data_dir()
        filepath = os.path.join(DATA_DIR, 'notification_templates.json')
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        return []

    @classmethod
    def get(cls, **kwargs):
        templates = cls.load_all()
        for t in templates:
            match = True
            for key, value in kwargs.items():
                if t.get(key) != value:
                    match = False
                    break
            if match:
                return cls.from_dict(t)
        return None

    @classmethod
    def filter(cls, **kwargs):
        """Filtrlangan shablonlar ro'yxati"""
        templates = cls.load_all()
        result = []
        for t in templates:
            match = True
            for key, value in kwargs.items():
                if t.get(key) != value:
                    match = False
                    break
            if match:
                result.append(cls.from_dict(t))
        # Tartib bo'yicha saralash
        result.sort(key=lambda x: x.order_num)
        return result

    @classmethod
    def get_all_sorted(cls):
        """Barcha shablonlarni tartib bo'yicha olish"""
        templates = cls.load_all()
        templates.sort(key=lambda x: x.get('order_num', 0))
        return [cls.from_dict(t) for t in templates]
