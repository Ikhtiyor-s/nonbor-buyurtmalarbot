"""
Xodimlar Boshqaruvi
Sotuvchi xodimlarini avtonom boshqarish
"""
import os
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import CallbackContext

from .models import Seller

logger = logging.getLogger('bot')

# Data directory
DATA_DIR = Path(__file__).parent.parent / 'data'
STAFF_FILE = DATA_DIR / 'staff.json'


class Staff:
    """Xodim modeli"""

    def __init__(self, **kwargs):
        self.id = kwargs.get('id', '')
        self.vendor_id = kwargs.get('vendor_id', '')
        self.telegram_id = kwargs.get('telegram_id', '')
        self.full_name = kwargs.get('full_name', '')
        self.phone = kwargs.get('phone', '')
        self.role = kwargs.get('role', 'viewer')  # owner, admin, editor, viewer
        self.is_active = kwargs.get('is_active', True)
        self.permissions = kwargs.get('permissions', {})
        self.added_by = kwargs.get('added_by', '')
        self.created_at = kwargs.get('created_at', datetime.now().isoformat())

    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'vendor_id': self.vendor_id,
            'telegram_id': self.telegram_id,
            'full_name': self.full_name,
            'phone': self.phone,
            'role': self.role,
            'is_active': self.is_active,
            'permissions': self.permissions,
            'added_by': self.added_by,
            'created_at': self.created_at
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'Staff':
        return cls(**data)

    def save(self):
        """Xodimni saqlash"""
        staff_list = self.load_all()

        # Mavjudligini tekshirish
        existing_idx = None
        for i, s in enumerate(staff_list):
            if s.get('id') == self.id or s.get('telegram_id') == self.telegram_id:
                existing_idx = i
                break

        if existing_idx is not None:
            staff_list[existing_idx] = self.to_dict()
        else:
            import uuid
            self.id = str(uuid.uuid4())
            staff_list.append(self.to_dict())

        # Faylga yozish
        STAFF_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(STAFF_FILE, 'w', encoding='utf-8') as f:
            json.dump(staff_list, f, ensure_ascii=False, indent=2)

    @classmethod
    def load_all(cls) -> List[Dict]:
        """Barcha xodimlarni yuklash"""
        if not STAFF_FILE.exists():
            return []

        try:
            with open(STAFF_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return []

    @classmethod
    def get(cls, **kwargs) -> Optional['Staff']:
        """Xodimni topish"""
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
    def filter(cls, **kwargs) -> List['Staff']:
        """Xodimlarni filtrlash"""
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

    @classmethod
    def delete(cls, staff_id: str) -> bool:
        """Xodimni o'chirish"""
        staff_list = cls.load_all()
        new_list = [s for s in staff_list if s.get('id') != staff_id]

        if len(new_list) == len(staff_list):
            return False

        with open(STAFF_FILE, 'w', encoding='utf-8') as f:
            json.dump(new_list, f, ensure_ascii=False, indent=2)

        return True


class StaffManager:
    """Xodimlar boshqaruvchisi"""

    ROLE_PERMISSIONS = {
        'owner': {
            'view_orders': True,
            'edit_status': True,
            'cancel_orders': True,
            'view_stats': True,
            'view_earnings': True,
            'manage_staff': True,
            'edit_settings': True
        },
        'admin': {
            'view_orders': True,
            'edit_status': True,
            'cancel_orders': True,
            'view_stats': True,
            'view_earnings': True,
            'manage_staff': True,
            'edit_settings': False
        },
        'editor': {
            'view_orders': True,
            'edit_status': True,
            'cancel_orders': True,
            'view_stats': True,
            'view_earnings': False,
            'manage_staff': False,
            'edit_settings': False
        },
        'viewer': {
            'view_orders': True,
            'edit_status': False,
            'cancel_orders': False,
            'view_stats': True,
            'view_earnings': False,
            'manage_staff': False,
            'edit_settings': False
        }
    }

    ROLE_NAMES = {
        'owner': '👑 Egasi',
        'admin': '⚙️ Admin',
        'editor': '✏️ Tahrirlovchi',
        'viewer': '👁️ Ko\'ruvchi'
    }

    def __init__(self, bot=None):
        self.bot = bot
        self.pending_staff = {}  # user_id: {action, data}

    async def show_staff_management(self, update: Update, context: CallbackContext):
        """Xodimlar boshqaruvi"""
        user_id = update.callback_query.from_user.id if update.callback_query else update.effective_user.id

        # Sotuvchini topish
        seller = Seller.get(telegram_user_id=str(user_id))
        if not seller:
            await self._send_message(update, "❌ Siz sotuvchi sifatida ro'yxatdan o'tmagansiz.")
            return

        # Xodimlar ro'yxati
        staff_list = Staff.filter(vendor_id=seller.id)

        message = f"""
👥 <b>Xodimlar Boshqaruvi</b>
━━━━━━━━━━━━━━━━━━━━

<b>Jami xodimlar:</b> {len(staff_list)} kishi

"""

        if staff_list:
            message += "<b>Xodimlar ro'yxati:</b>\n\n"
            for staff in staff_list:
                role_name = self.ROLE_NAMES.get(staff.role, staff.role)
                status = "✅ Faol" if staff.is_active else "❌ Nofaol"
                message += f"{role_name} {staff.full_name}\n"
                message += f"   📱 {staff.phone} | {status}\n"
                message += f"   🆔 {staff.telegram_id}\n\n"
        else:
            message += "Hozircha xodimlar yo'q.\n"

        keyboard = [
            [
                InlineKeyboardButton("➕ Xodim qo'shish", callback_data="staff_add"),
                InlineKeyboardButton("✏️ Huquqlar", callback_data="staff_permissions")
            ],
            [
                InlineKeyboardButton("🗑️ O'chirish", callback_data="staff_remove"),
                InlineKeyboardButton("📊 Faollik", callback_data="staff_activity")
            ],
            [
                InlineKeyboardButton("⬅️ Orqaga", callback_data="dash_back"),
                InlineKeyboardButton("🔄 Yangilash", callback_data="dash_staff")
            ]
        ]

        await self._send_or_edit(update, message, keyboard)

    async def start_add_staff(self, update: Update, context: CallbackContext):
        """Xodim qo'shishni boshlash"""
        query = update.callback_query
        await query.answer()

        user_id = query.from_user.id

        # Sotuvchini tekshirish
        seller = Seller.get(telegram_user_id=str(user_id))
        if not seller:
            return

        # Pending action
        self.pending_staff[user_id] = {
            'action': 'add_staff',
            'step': 'phone',
            'vendor_id': seller.id
        }

        await query.edit_message_text(
            "📱 <b>Yangi xodim telefon raqamini kiriting:</b>\n\n"
            "Format: 901234567 yoki +998901234567\n\n"
            "❌ Bekor qilish: /cancel",
            parse_mode='HTML'
        )

    async def handle_staff_phone(self, update: Update, context: CallbackContext) -> bool:
        """Xodim telefon raqamini qabul qilish"""
        user_id = update.effective_user.id

        if user_id not in self.pending_staff:
            return False

        pending = self.pending_staff[user_id]

        if pending.get('action') != 'add_staff' or pending.get('step') != 'phone':
            return False

        phone = update.message.text.strip()

        # Telefon raqamni tozalash
        clean_phone = self._clean_phone(phone)

        if not clean_phone:
            await update.message.reply_text(
                "❌ Noto'g'ri telefon raqam formati!\n\n"
                "Format: 901234567 yoki +998901234567"
            )
            return True

        # Telegram ID ni qidirish (sodda usul - foydalanuvchi /start bosgan bo'lishi kerak)
        # Hozircha telefon raqam bilan saqlash
        pending['phone'] = clean_phone
        pending['step'] = 'name'

        await update.message.reply_text(
            f"✅ Telefon: +998{clean_phone}\n\n"
            "👤 Endi xodim ismini kiriting:",
            parse_mode='HTML'
        )

        return True

    async def handle_staff_name(self, update: Update, context: CallbackContext) -> bool:
        """Xodim ismini qabul qilish"""
        user_id = update.effective_user.id

        if user_id not in self.pending_staff:
            return False

        pending = self.pending_staff[user_id]

        if pending.get('action') != 'add_staff' or pending.get('step') != 'name':
            return False

        name = update.message.text.strip()

        if len(name) < 2:
            await update.message.reply_text("❌ Ism juda qisqa!")
            return True

        pending['name'] = name
        pending['step'] = 'role'

        # Rol tanlash
        keyboard = [
            [
                InlineKeyboardButton("👁️ Ko'ruvchi", callback_data="setrole_viewer"),
                InlineKeyboardButton("✏️ Tahrirlovchi", callback_data="setrole_editor")
            ],
            [
                InlineKeyboardButton("⚙️ Admin", callback_data="setrole_admin"),
                InlineKeyboardButton("❌ Bekor qilish", callback_data="staff_cancel")
            ]
        ]

        await update.message.reply_text(
            f"✅ Ism: {name}\n\n"
            "<b>Xodim rolini tanlang:</b>\n\n"
            "👁️ <b>Ko'ruvchi</b> - Faqat buyurtmalarni ko'rish\n"
            "✏️ <b>Tahrirlovchi</b> - Status o'zgartirish\n"
            "⚙️ <b>Admin</b> - To'liq boshqaruv",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return True

    async def handle_role_selection(self, update: Update, context: CallbackContext):
        """Rol tanlash"""
        query = update.callback_query
        await query.answer()

        user_id = query.from_user.id

        if query.data == "staff_cancel":
            if user_id in self.pending_staff:
                del self.pending_staff[user_id]
            await query.edit_message_text("❌ Xodim qo'shish bekor qilindi.")
            return

        if user_id not in self.pending_staff:
            return

        pending = self.pending_staff[user_id]

        if pending.get('step') != 'role':
            return

        role = query.data.replace('setrole_', '')

        # Xodimni saqlash
        import uuid
        staff = Staff(
            id=str(uuid.uuid4()),
            vendor_id=pending['vendor_id'],
            telegram_id='',  # Keyinroq bog'lanadi
            full_name=pending['name'],
            phone=pending['phone'],
            role=role,
            permissions=self.ROLE_PERMISSIONS.get(role, {}),
            added_by=str(user_id),
            is_active=True
        )
        staff.save()

        # Pending ni tozalash
        del self.pending_staff[user_id]

        role_name = self.ROLE_NAMES.get(role, role)

        await query.edit_message_text(
            f"✅ <b>Xodim muvaffaqiyatli qo'shildi!</b>\n\n"
            f"👤 Ism: {pending['name']}\n"
            f"📱 Telefon: +998{pending['phone']}\n"
            f"👨‍💼 Rol: {role_name}\n\n"
            f"Xodim @NonborBuyurtmalarBot ga /start bosishi kerak.",
            parse_mode='HTML'
        )

    async def show_remove_staff(self, update: Update, context: CallbackContext):
        """Xodimni o'chirish"""
        query = update.callback_query
        await query.answer()

        user_id = query.from_user.id
        seller = Seller.get(telegram_user_id=str(user_id))

        if not seller:
            return

        staff_list = Staff.filter(vendor_id=seller.id)

        if not staff_list:
            await query.edit_message_text("Xodimlar ro'yxati bo'sh.")
            return

        keyboard = []
        for staff in staff_list:
            keyboard.append([
                InlineKeyboardButton(
                    f"🗑️ {staff.full_name} ({staff.role})",
                    callback_data=f"confirmremove_{staff.id}"
                )
            ])

        keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="dash_staff")])

        await query.edit_message_text(
            "🗑️ <b>O'chirish uchun xodimni tanlang:</b>",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def confirm_remove_staff(self, update: Update, context: CallbackContext):
        """Xodimni o'chirishni tasdiqlash"""
        query = update.callback_query
        await query.answer()

        staff_id = query.data.replace('confirmremove_', '')

        staff = Staff.get(id=staff_id)
        if not staff:
            await query.edit_message_text("❌ Xodim topilmadi.")
            return

        keyboard = [
            [
                InlineKeyboardButton("✅ Ha, o'chirish", callback_data=f"doremove_{staff_id}"),
                InlineKeyboardButton("❌ Yo'q", callback_data="dash_staff")
            ]
        ]

        await query.edit_message_text(
            f"⚠️ <b>Rostdan ham o'chirmoqchimisiz?</b>\n\n"
            f"👤 {staff.full_name}\n"
            f"📱 +998{staff.phone}",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def do_remove_staff(self, update: Update, context: CallbackContext):
        """Xodimni o'chirish"""
        query = update.callback_query
        await query.answer()

        staff_id = query.data.replace('doremove_', '')

        if Staff.delete(staff_id):
            await query.edit_message_text("✅ Xodim o'chirildi!")
        else:
            await query.edit_message_text("❌ Xodimni o'chirishda xatolik.")

    def _clean_phone(self, phone: str) -> Optional[str]:
        """Telefon raqamni tozalash"""
        phone = phone.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')

        if phone.startswith('+998'):
            phone = phone[4:]
        elif phone.startswith('998'):
            phone = phone[3:]
        elif phone.startswith('8'):
            phone = phone[1:]

        if len(phone) == 9 and phone.isdigit():
            return phone

        return None

    def can_edit_status(self, user_id: int) -> bool:
        """Status o'zgartirish huquqini tekshirish"""
        # Owner yoki admin bo'lsa
        seller = Seller.get(telegram_user_id=str(user_id))
        if seller:
            return True

        # Xodim huquqini tekshirish
        staff = Staff.get(telegram_id=str(user_id))
        if staff and staff.is_active:
            return staff.permissions.get('edit_status', False)

        return False

    async def _send_message(self, update: Update, text: str):
        if update.callback_query:
            await update.callback_query.message.reply_text(text, parse_mode='HTML')
        else:
            await update.message.reply_text(text, parse_mode='HTML')

    async def _send_or_edit(self, update: Update, text: str, keyboard=None):
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None

        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(
                    text, parse_mode='HTML', reply_markup=reply_markup
                )
            except:
                await update.callback_query.message.reply_text(
                    text, parse_mode='HTML', reply_markup=reply_markup
                )
        else:
            await update.message.reply_text(
                text, parse_mode='HTML', reply_markup=reply_markup
            )
