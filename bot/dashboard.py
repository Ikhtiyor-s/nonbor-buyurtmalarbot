"""
Avtonom Sotuvchi Dashboard
Sotuvchi boshqaruv paneli va statistika
"""
import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import CallbackContext

from .models import Seller, Order

logger = logging.getLogger('bot')


class VendorDashboard:
    """Sotuvchi boshqaruv paneli"""

    def __init__(self, bot=None):
        self.bot = bot

    async def show_dashboard(self, update: Update, context: CallbackContext):
        """Asosiy dashboard ko'rsatish"""
        user_id = update.effective_user.id

        # Sotuvchini topish
        seller = Seller.get(telegram_user_id=str(user_id))
        if not seller:
            await self._send_message(update,
                "❌ Siz sotuvchi sifatida ro'yxatdan o'tmagansiz.\n"
                "Guruhda /start bosing."
            )
            return

        # Statistikalarni olish
        stats = self._get_dashboard_stats(seller)

        message = f"""
🏪 <b>{seller.full_name} - Boshqaruv Paneli</b>
━━━━━━━━━━━━━━━━━━━━

📊 <b>Bugungi statistika:</b>
🛍️ Yangi buyurtmalar: {stats['today_new']} ta
💰 Bugungi daromad: {stats['today_earnings']:,} so'm
✅ Qabul qilingan: {stats['today_accepted']} ta
📦 Yetkazilgan: {stats['today_delivered']} ta

👥 <b>Xodimlar:</b> {stats['staff_count']} kishi
📈 <b>Oylik daromad:</b> {stats['month_earnings']:,} so'm
⭐ <b>Jami buyurtmalar:</b> {stats['total_orders']} ta

━━━━━━━━━━━━━━━━━━━━
📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}
"""

        keyboard = [
            [
                InlineKeyboardButton("👥 Xodimlar", callback_data="dash_staff"),
                InlineKeyboardButton("📊 Statistika", callback_data="dash_stats")
            ],
            [
                InlineKeyboardButton("💰 Daromad", callback_data="dash_earnings"),
                InlineKeyboardButton("📦 Buyurtmalar", callback_data="dash_orders")
            ],
            [
                InlineKeyboardButton("⚙️ Sozlamalar", callback_data="dash_settings"),
                InlineKeyboardButton("📱 Profil", callback_data="dash_profile")
            ],
            [
                InlineKeyboardButton("🔄 Yangilash", callback_data="dash_refresh"),
                InlineKeyboardButton("ℹ️ Yordam", callback_data="dash_help")
            ]
        ]

        await self._send_or_edit(update, message, keyboard)

    async def show_statistics(self, update: Update, context: CallbackContext):
        """Statistika menyusi"""
        keyboard = [
            [
                InlineKeyboardButton("📅 Bugun", callback_data="stats_today"),
                InlineKeyboardButton("📅 Kecha", callback_data="stats_yesterday")
            ],
            [
                InlineKeyboardButton("📅 Shu hafta", callback_data="stats_week"),
                InlineKeyboardButton("📅 Shu oy", callback_data="stats_month")
            ],
            [
                InlineKeyboardButton("📈 O'sish", callback_data="stats_growth"),
                InlineKeyboardButton("👥 Mijozlar", callback_data="stats_customers")
            ],
            [
                InlineKeyboardButton("⬅️ Orqaga", callback_data="dash_back")
            ]
        ]

        await self._send_or_edit(
            update,
            "📊 <b>Statistika va Hisobotlar</b>\n\n"
            "Davrni tanlang:",
            keyboard
        )

    async def show_today_stats(self, update: Update, context: CallbackContext):
        """Bugungi statistika"""
        user_id = update.callback_query.from_user.id
        seller = Seller.get(telegram_user_id=str(user_id))

        if not seller:
            return

        stats = self._get_detailed_stats(seller, 'today')

        message = f"""
📊 <b>Bugungi Statistika</b>
📅 {datetime.now().strftime('%d.%m.%Y')}
━━━━━━━━━━━━━━━━━━━━

🛍️ <b>Buyurtmalar:</b>
   • Yangi: {stats['new']} ta
   • Qabul qilingan: {stats['accepted']} ta
   • Yetkazilgan: {stats['delivered']} ta
   • Bekor qilingan: {stats['cancelled']} ta
   └─ Jami: {stats['total']} ta

💰 <b>Daromad:</b>
   • Bugungi: {stats['earnings']:,} so'm
   • O'rtacha buyurtma: {stats['avg_order']:,} so'm

━━━━━━━━━━━━━━━━━━━━
"""

        keyboard = [
            [InlineKeyboardButton("⬅️ Orqaga", callback_data="dash_stats")]
        ]

        await self._send_or_edit(update, message, keyboard)

    async def show_week_stats(self, update: Update, context: CallbackContext):
        """Haftalik statistika"""
        user_id = update.callback_query.from_user.id
        seller = Seller.get(telegram_user_id=str(user_id))

        if not seller:
            return

        stats = self._get_detailed_stats(seller, 'week')

        message = f"""
📊 <b>Haftalik Statistika</b>
📅 Oxirgi 7 kun
━━━━━━━━━━━━━━━━━━━━

🛍️ <b>Buyurtmalar:</b> {stats['total']} ta
💰 <b>Daromad:</b> {stats['earnings']:,} so'm
📈 <b>Kunlik o'rtacha:</b> {stats['daily_avg']:,} so'm

<b>Kunlar bo'yicha:</b>
{stats['daily_breakdown']}

━━━━━━━━━━━━━━━━━━━━
"""

        keyboard = [
            [InlineKeyboardButton("⬅️ Orqaga", callback_data="dash_stats")]
        ]

        await self._send_or_edit(update, message, keyboard)

    async def show_month_stats(self, update: Update, context: CallbackContext):
        """Oylik statistika"""
        user_id = update.callback_query.from_user.id
        seller = Seller.get(telegram_user_id=str(user_id))

        if not seller:
            return

        stats = self._get_detailed_stats(seller, 'month')

        message = f"""
📊 <b>Oylik Statistika</b>
📅 {datetime.now().strftime('%B %Y')}
━━━━━━━━━━━━━━━━━━━━

🛍️ <b>Buyurtmalar:</b> {stats['total']} ta
💰 <b>Daromad:</b> {stats['earnings']:,} so'm
📈 <b>Kunlik o'rtacha:</b> {stats['daily_avg']:,} so'm
📊 <b>O'tgan oyga nisbatan:</b> {stats['growth']}%

━━━━━━━━━━━━━━━━━━━━
"""

        keyboard = [
            [InlineKeyboardButton("⬅️ Orqaga", callback_data="dash_stats")]
        ]

        await self._send_or_edit(update, message, keyboard)

    async def show_earnings(self, update: Update, context: CallbackContext):
        """Daromad hisoboti"""
        user_id = update.callback_query.from_user.id if update.callback_query else update.effective_user.id
        seller = Seller.get(telegram_user_id=str(user_id))

        if not seller:
            return

        today = datetime.now().date()
        week_ago = today - timedelta(days=7)
        month_start = today.replace(day=1)

        # Daromadlarni hisoblash
        today_earnings = self._calculate_earnings(seller.id, today, today)
        week_earnings = self._calculate_earnings(seller.id, week_ago, today)
        month_earnings = self._calculate_earnings(seller.id, month_start, today)

        message = f"""
💰 <b>Daromad Hisoboti</b>
━━━━━━━━━━━━━━━━━━━━

📅 <b>Bugun:</b> {today_earnings:,} so'm
📅 <b>Shu hafta:</b> {week_earnings:,} so'm
📅 <b>Shu oy:</b> {month_earnings:,} so'm

<b>Kunlik o'rtacha:</b> {week_earnings // 7 if week_earnings else 0:,} so'm

━━━━━━━━━━━━━━━━━━━━
"""

        keyboard = [
            [
                InlineKeyboardButton("📅 Kunlik", callback_data="earn_daily"),
                InlineKeyboardButton("📅 Haftalik", callback_data="earn_weekly")
            ],
            [
                InlineKeyboardButton("📅 Oylik", callback_data="earn_monthly"),
                InlineKeyboardButton("📊 Grafik", callback_data="earn_chart")
            ],
            [
                InlineKeyboardButton("⬅️ Orqaga", callback_data="dash_back")
            ]
        ]

        await self._send_or_edit(update, message, keyboard)

    async def show_orders_list(self, update: Update, context: CallbackContext):
        """Buyurtmalar ro'yxati"""
        user_id = update.callback_query.from_user.id if update.callback_query else update.effective_user.id
        seller = Seller.get(telegram_user_id=str(user_id))

        if not seller:
            return

        # Oxirgi buyurtmalarni olish
        orders = Order.filter(seller_id=seller.id)
        orders = sorted(orders, key=lambda x: x.get('created_at', ''), reverse=True)[:10]

        if not orders:
            message = "📦 <b>Buyurtmalar</b>\n\nHozircha buyurtmalar yo'q."
        else:
            message = "📦 <b>Oxirgi 10 ta Buyurtma</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"

            for order in orders:
                status_emoji = self._get_status_emoji(order.get('status', 'new'))
                total = order.get('total_amount', 0)
                created = order.get('created_at', '')[:10]

                message += f"{status_emoji} #{order.get('external_id', order.get('id', '')[:6])}\n"
                message += f"   💰 {total:,} so'm | 📅 {created}\n\n"

        keyboard = [
            [
                InlineKeyboardButton("🆕 Yangi", callback_data="orders_new"),
                InlineKeyboardButton("✅ Qabul", callback_data="orders_accepted")
            ],
            [
                InlineKeyboardButton("📦 Yetkazilgan", callback_data="orders_delivered"),
                InlineKeyboardButton("❌ Bekor", callback_data="orders_cancelled")
            ],
            [
                InlineKeyboardButton("⬅️ Orqaga", callback_data="dash_back")
            ]
        ]

        await self._send_or_edit(update, message, keyboard)

    async def show_profile(self, update: Update, context: CallbackContext):
        """Profil ko'rsatish"""
        user_id = update.callback_query.from_user.id if update.callback_query else update.effective_user.id
        seller = Seller.get(telegram_user_id=str(user_id))

        if not seller:
            return

        address = seller.address or "Korsatilmagan"
        region = seller.region or "Korsatilmagan"
        district = seller.district or "Korsatilmagan"
        group = seller.group_title or "Ulanmagan"
        status = "Faol" if seller.is_active else "Nofaol"

        message = f"""
📱 <b>Profil</b>
━━━━━━━━━━━━━━━━━━━━

🏪 <b>Biznes:</b> {seller.full_name}
📱 <b>Telefon:</b> {seller.phone}
📍 <b>Manzil:</b> {address}
🌍 <b>Viloyat:</b> {region}
🏘️ <b>Tuman:</b> {district}

<b>Guruh:</b> {group}
<b>Status:</b> {status}

━━━━━━━━━━━━━━━━━━━━
"""

        keyboard = [
            [
                InlineKeyboardButton("✏️ Tahrirlash", callback_data="profile_edit"),
                InlineKeyboardButton("📍 Manzil", callback_data="profile_address")
            ],
            [
                InlineKeyboardButton("⬅️ Orqaga", callback_data="dash_back")
            ]
        ]

        await self._send_or_edit(update, message, keyboard)

    async def show_help(self, update: Update, context: CallbackContext):
        """Yordam"""
        message = """
ℹ️ <b>Yordam</b>
━━━━━━━━━━━━━━━━━━━━

<b>Buyruqlar:</b>
/start - Boshlash
/dashboard - Boshqaruv paneli
/stats - Statistika
/earnings - Daromad
/orders - Buyurtmalar
/staff - Xodimlar
/help - Yordam

<b>Buyurtma statuslari:</b>
🆕 Yangi
✅ Qabul qilingan
📦 Yetkazilgan
❌ Bekor qilingan

<b>Muammolar bo'lsa:</b>
📞 +998 90 123 45 67
📧 support@nonbor.uz

━━━━━━━━━━━━━━━━━━━━
"""

        keyboard = [
            [InlineKeyboardButton("⬅️ Orqaga", callback_data="dash_back")]
        ]

        await self._send_or_edit(update, message, keyboard)

    # ============ HELPER METHODS ============

    def _get_dashboard_stats(self, seller) -> Dict:
        """Dashboard statistikalarini olish"""
        today = datetime.now().date()
        month_start = today.replace(day=1)

        orders = Order.filter(seller_id=seller.id)

        # Bugungi buyurtmalar
        today_orders = [o for o in orders if o.get('created_at', '')[:10] == str(today)]

        # Oylik buyurtmalar
        month_orders = [o for o in orders if o.get('created_at', '')[:10] >= str(month_start)]

        return {
            'today_new': len([o for o in today_orders if o.get('status') == 'new']),
            'today_accepted': len([o for o in today_orders if o.get('status') == 'accepted']),
            'today_delivered': len([o for o in today_orders if o.get('status') == 'delivered']),
            'today_earnings': sum(o.get('total_amount', 0) for o in today_orders if o.get('status') in ['accepted', 'delivered']),
            'month_earnings': sum(o.get('total_amount', 0) for o in month_orders if o.get('status') in ['accepted', 'delivered']),
            'total_orders': len(orders),
            'staff_count': 0  # TODO: Xodimlar moduli
        }

    def _get_detailed_stats(self, seller, period: str) -> Dict:
        """Batafsil statistika"""
        today = datetime.now().date()

        if period == 'today':
            start_date = today
            end_date = today
        elif period == 'yesterday':
            start_date = today - timedelta(days=1)
            end_date = start_date
        elif period == 'week':
            start_date = today - timedelta(days=6)
            end_date = today
        elif period == 'month':
            start_date = today.replace(day=1)
            end_date = today
        else:
            start_date = today
            end_date = today

        orders = Order.filter(seller_id=seller.id)

        # Davrga mos buyurtmalar
        period_orders = []
        for o in orders:
            created = o.get('created_at', '')[:10]
            if str(start_date) <= created <= str(end_date):
                period_orders.append(o)

        total = len(period_orders)
        earnings = sum(o.get('total_amount', 0) for o in period_orders if o.get('status') in ['accepted', 'delivered'])

        days = (end_date - start_date).days + 1

        # Kunlik breakdown
        daily_breakdown = ""
        if period == 'week':
            for i in range(7):
                day = today - timedelta(days=6-i)
                day_orders = [o for o in period_orders if o.get('created_at', '')[:10] == str(day)]
                day_earnings = sum(o.get('total_amount', 0) for o in day_orders)
                daily_breakdown += f"   {day.strftime('%d.%m')}: {len(day_orders)} ta / {day_earnings:,} so'm\n"

        return {
            'new': len([o for o in period_orders if o.get('status') == 'new']),
            'accepted': len([o for o in period_orders if o.get('status') == 'accepted']),
            'delivered': len([o for o in period_orders if o.get('status') == 'delivered']),
            'cancelled': len([o for o in period_orders if o.get('status') in ['rejected', 'cancelled']]),
            'total': total,
            'earnings': earnings,
            'avg_order': earnings // total if total else 0,
            'daily_avg': earnings // days if days else 0,
            'growth': 0,  # TODO: O'sish hisoblash
            'daily_breakdown': daily_breakdown
        }

    def _calculate_earnings(self, seller_id: str, start_date, end_date) -> int:
        """Daromadni hisoblash"""
        orders = Order.filter(seller_id=seller_id)

        total = 0
        for o in orders:
            created = o.get('created_at', '')[:10]
            if str(start_date) <= created <= str(end_date):
                if o.get('status') in ['accepted', 'delivered']:
                    total += o.get('total_amount', 0)

        return total

    def _get_status_emoji(self, status: str) -> str:
        """Status emoji"""
        emojis = {
            'new': '🆕',
            'accepted': '✅',
            'delivered': '📦',
            'rejected': '❌',
            'cancelled': '❌'
        }
        return emojis.get(status, '📋')

    async def _send_message(self, update: Update, text: str, keyboard=None):
        """Xabar yuborish"""
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None

        if update.callback_query:
            await update.callback_query.message.reply_text(
                text, parse_mode='HTML', reply_markup=reply_markup
            )
        else:
            await update.message.reply_text(
                text, parse_mode='HTML', reply_markup=reply_markup
            )

    async def _send_or_edit(self, update: Update, text: str, keyboard=None):
        """Xabarni yuborish yoki tahrirlash"""
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None

        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(
                    text, parse_mode='HTML', reply_markup=reply_markup
                )
            except Exception:
                await update.callback_query.message.reply_text(
                    text, parse_mode='HTML', reply_markup=reply_markup
                )
        else:
            await update.message.reply_text(
                text, parse_mode='HTML', reply_markup=reply_markup
            )
