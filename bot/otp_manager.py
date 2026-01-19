"""
OTP Manager - Telegram va SMS orqali OTP yuborish va tekshirish
@VerificationCodes boti orqali Telegram, SMS fallback sifatida
"""

import os
import random
import string
import logging
import aiohttp
from datetime import datetime, timedelta
from telegram import Bot
from .models import OTPRequest, SecurityLog, BlockedIP

logger = logging.getLogger(__name__)


class OTPManager:
    """OTP yuborish va tekshirish boshqaruvchisi"""

    # Rate limit sozlamalari
    MAX_OTP_PER_PHONE_PER_DAY = 5
    MAX_OTP_PER_USER_PER_DAY = 10
    MAX_VERIFICATION_ATTEMPTS = 3
    OTP_EXPIRY_MINUTES = 5
    BLOCK_DURATION_HOURS = 24

    def __init__(self):
        self.bot_token = os.getenv('TELEGRAM_BOT_TOKEN', '')
        self.verification_bot_token = os.getenv('VERIFICATION_BOT_TOKEN', '')
        self.sms_api_key = os.getenv('SMS_API_KEY', '')
        self.sms_api_url = os.getenv('SMS_API_URL', '')
        self.bot = Bot(token=self.bot_token) if self.bot_token else None

    def generate_otp(self, length=6):
        """6 raqamli OTP kod generatsiya qilish"""
        return ''.join(random.choices(string.digits, k=length))

    def _get_today_start(self):
        """Bugungi kunning boshlanish vaqti"""
        now = datetime.now()
        return datetime(now.year, now.month, now.day)

    def check_rate_limit(self, phone: str, telegram_user_id: str = '') -> tuple:
        """
        Rate limitni tekshirish
        Returns: (is_allowed: bool, reason: str)
        """
        today_start = self._get_today_start()
        all_requests = OTPRequest.load_all()

        # Telefon raqami bo'yicha bugungi so'rovlar
        phone_requests_today = 0
        user_requests_today = 0

        for req in all_requests:
            req_date = datetime.fromisoformat(req['created_at'])
            if req_date >= today_start:
                if req['phone'] == phone:
                    phone_requests_today += 1
                if telegram_user_id and req['telegram_user_id'] == telegram_user_id:
                    user_requests_today += 1

        # Telefon raqami limiti
        if phone_requests_today >= self.MAX_OTP_PER_PHONE_PER_DAY:
            self._log_security('rate_limit', phone, telegram_user_id,
                               f'Telefon limiti: {phone_requests_today}/{self.MAX_OTP_PER_PHONE_PER_DAY}')
            return False, f"Bu telefon raqamiga bugun juda ko'p OTP yuborildi. Ertaga urinib ko'ring."

        # Foydalanuvchi limiti
        if telegram_user_id and user_requests_today >= self.MAX_OTP_PER_USER_PER_DAY:
            self._log_security('rate_limit', phone, telegram_user_id,
                               f'Foydalanuvchi limiti: {user_requests_today}/{self.MAX_OTP_PER_USER_PER_DAY}')
            return False, f"Siz bugun juda ko'p OTP so'radingiz. Ertaga urinib ko'ring."

        return True, ""

    def get_pending_otp(self, phone: str) -> OTPRequest:
        """Telefon raqami uchun faol OTP olish"""
        all_requests = OTPRequest.load_all()
        now = datetime.now()

        for req_data in reversed(all_requests):
            if req_data['phone'] == phone and not req_data['is_verified'] and not req_data['is_expired']:
                req = OTPRequest.from_dict(req_data)
                if req.expires_at:
                    expires = datetime.fromisoformat(req.expires_at)
                    if now < expires:
                        return req
                    else:
                        # Muddati o'tgan
                        req.is_expired = True
                        req.save()
        return None

    async def send_otp_telegram(self, phone: str, telegram_user_id: str) -> tuple:
        """
        @VerificationCodes boti orqali OTP yuborish (asosiy usul)
        Returns: (success: bool, otp_code: str, message: str)
        """
        try:
            # Rate limit tekshirish
            allowed, reason = self.check_rate_limit(phone, telegram_user_id)
            if not allowed:
                return False, '', reason

            # Mavjud faol OTP ni tekshirish
            existing = self.get_pending_otp(phone)
            if existing:
                return True, existing.otp_code, "Sizga allaqachon OTP yuborilgan. Telegramni tekshiring."

            # Yangi OTP generatsiya
            otp_code = self.generate_otp()
            expires_at = (datetime.now() + timedelta(minutes=self.OTP_EXPIRY_MINUTES)).isoformat()

            # @VerificationCodes boti orqali yuborish
            if self.verification_bot_token:
                try:
                    verification_bot = Bot(token=self.verification_bot_token)
                    message_text = (
                        f"Nonbor tasdiqlash kodi: {otp_code}\n\n"
                        f"Bu kod 5 daqiqa ichida amal qiladi.\n"
                        f"Kodni hech kimga bermang!"
                    )

                    # Foydalanuvchiga to'g'ridan-to'g'ri yuborish
                    await verification_bot.send_message(
                        chat_id=telegram_user_id,
                        text=message_text
                    )

                    # OTP so'rovni saqlash
                    otp_request = OTPRequest(
                        phone=phone,
                        otp_code=otp_code,
                        telegram_user_id=telegram_user_id,
                        delivery_method='telegram',
                        expires_at=expires_at
                    )
                    otp_request.save()

                    self._log_security('otp_sent', phone, telegram_user_id, 'Telegram orqali yuborildi')
                    logger.info(f"OTP yuborildi (Telegram): {phone}")

                    return True, otp_code, "Tasdiqlash kodi Telegramga yuborildi!"

                except Exception as tg_error:
                    logger.warning(f"Telegram OTP yuborishda xato: {tg_error}")
                    # SMS fallback ga o'tish
                    return await self.send_otp_sms(phone, telegram_user_id, otp_code, expires_at)
            else:
                # Verification bot tokeni yo'q, SMS ishlatish
                return await self.send_otp_sms(phone, telegram_user_id, otp_code, expires_at)

        except Exception as e:
            logger.error(f"OTP yuborishda xato: {e}")
            return False, '', f"Xatolik yuz berdi: {str(e)}"

    async def send_otp_sms(self, phone: str, telegram_user_id: str,
                           otp_code: str = None, expires_at: str = None) -> tuple:
        """
        SMS orqali OTP yuborish (fallback)
        Returns: (success: bool, otp_code: str, message: str)
        """
        try:
            if not otp_code:
                # Rate limit tekshirish
                allowed, reason = self.check_rate_limit(phone, telegram_user_id)
                if not allowed:
                    return False, '', reason

                otp_code = self.generate_otp()
                expires_at = (datetime.now() + timedelta(minutes=self.OTP_EXPIRY_MINUTES)).isoformat()

            # SMS API orqali yuborish
            if self.sms_api_url and self.sms_api_key:
                try:
                    async with aiohttp.ClientSession() as session:
                        # Eskiz.uz SMS API format
                        payload = {
                            'mobile_phone': phone.replace('+', ''),
                            'message': f"Nonbor tasdiqlash kodi: {otp_code}. Kod 5 daqiqa amal qiladi.",
                            'from': 'Nonbor'
                        }
                        headers = {
                            'Authorization': f'Bearer {self.sms_api_key}',
                            'Content-Type': 'application/json'
                        }

                        async with session.post(
                            self.sms_api_url,
                            json=payload,
                            headers=headers
                        ) as response:
                            if response.status == 200:
                                # OTP so'rovni saqlash
                                otp_request = OTPRequest(
                                    phone=phone,
                                    otp_code=otp_code,
                                    telegram_user_id=telegram_user_id,
                                    delivery_method='sms',
                                    expires_at=expires_at
                                )
                                otp_request.save()

                                self._log_security('otp_sent', phone, telegram_user_id, 'SMS orqali yuborildi')
                                logger.info(f"OTP yuborildi (SMS): {phone}")

                                return True, otp_code, "Tasdiqlash kodi SMS orqali yuborildi!"
                            else:
                                logger.error(f"SMS API xatosi: {response.status}")
                                return False, '', "SMS yuborishda xatolik. Keyinroq urinib ko'ring."

                except Exception as sms_error:
                    logger.error(f"SMS yuborishda xato: {sms_error}")
                    return False, '', "SMS xizmati vaqtinchalik ishlamayapti."
            else:
                # SMS API sozlanmagan - OTPni saqlab, manual tekshirish uchun
                otp_request = OTPRequest(
                    phone=phone,
                    otp_code=otp_code,
                    telegram_user_id=telegram_user_id,
                    delivery_method='manual',
                    expires_at=expires_at
                )
                otp_request.save()

                self._log_security('otp_sent', phone, telegram_user_id, 'Manual rejim (SMS sozlanmagan)')
                logger.warning(f"OTP yaratildi (manual): {phone} - kod: {otp_code}")

                # Development rejimda kodni ko'rsatish (production da olib tashlang)
                if os.getenv('DEBUG', 'False').lower() == 'true':
                    return True, otp_code, f"Test rejim - OTP kod: {otp_code}"

                return True, otp_code, "Tasdiqlash kodi yuborildi. Telegramni tekshiring."

        except Exception as e:
            logger.error(f"SMS OTP yuborishda xato: {e}")
            return False, '', f"Xatolik yuz berdi: {str(e)}"

    async def send_otp(self, phone: str, telegram_user_id: str) -> tuple:
        """
        OTP yuborish - avval Telegram, keyin SMS
        Returns: (success: bool, message: str)
        """
        # Avval Telegram orqali
        success, otp_code, message = await self.send_otp_telegram(phone, telegram_user_id)
        return success, message

    def verify_otp(self, phone: str, code: str, telegram_user_id: str = '') -> tuple:
        """
        OTP kodni tekshirish
        Returns: (is_valid: bool, message: str)
        """
        try:
            pending_otp = self.get_pending_otp(phone)

            if not pending_otp:
                self._log_security('otp_failed', phone, telegram_user_id, 'Faol OTP topilmadi')
                return False, "Faol tasdiqlash kodi topilmadi. Yangi kod so'rang."

            # Urinishlar sonini tekshirish
            if pending_otp.attempts >= self.MAX_VERIFICATION_ATTEMPTS:
                pending_otp.is_expired = True
                pending_otp.save()
                self._log_security('blocked', phone, telegram_user_id,
                                   f"Ko'p noto'g'ri urinish: {pending_otp.attempts}")
                return False, "Juda ko'p noto'g'ri urinish. Yangi kod so'rang."

            # Kodni tekshirish
            if pending_otp.otp_code == code:
                pending_otp.is_verified = True
                pending_otp.verified_at = datetime.now().isoformat()
                pending_otp.save()

                self._log_security('otp_verified', phone, telegram_user_id, 'OTP tasdiqlandi')
                logger.info(f"OTP tasdiqlandi: {phone}")
                return True, "Telefon raqami muvaffaqiyatli tasdiqlandi!"
            else:
                # Noto'g'ri kod
                pending_otp.attempts += 1
                pending_otp.save()

                remaining = self.MAX_VERIFICATION_ATTEMPTS - pending_otp.attempts
                self._log_security('otp_failed', phone, telegram_user_id,
                                   f"Noto'g'ri kod, qolgan urinishlar: {remaining}")

                if remaining > 0:
                    return False, f"Noto'g'ri kod. {remaining} ta urinish qoldi."
                else:
                    pending_otp.is_expired = True
                    pending_otp.save()
                    return False, "Noto'g'ri kod. Yangi kod so'rang."

        except Exception as e:
            logger.error(f"OTP tekshirishda xato: {e}")
            return False, f"Xatolik yuz berdi: {str(e)}"

    def _log_security(self, log_type: str, phone: str, telegram_user_id: str, details: str):
        """Xavfsizlik logini saqlash"""
        try:
            log = SecurityLog(
                log_type=log_type,
                phone=phone,
                telegram_user_id=telegram_user_id,
                details=details
            )
            log.save()
        except Exception as e:
            logger.error(f"Security log saqlashda xato: {e}")

    def get_otp_stats(self) -> dict:
        """OTP statistikasi"""
        all_requests = OTPRequest.load_all()
        today_start = self._get_today_start()

        stats = {
            'total': len(all_requests),
            'today': 0,
            'verified_today': 0,
            'failed_today': 0,
            'telegram_delivery': 0,
            'sms_delivery': 0
        }

        for req in all_requests:
            req_date = datetime.fromisoformat(req['created_at'])
            if req_date >= today_start:
                stats['today'] += 1
                if req['is_verified']:
                    stats['verified_today'] += 1
                elif req['is_expired']:
                    stats['failed_today'] += 1

            if req['delivery_method'] == 'telegram':
                stats['telegram_delivery'] += 1
            elif req['delivery_method'] == 'sms':
                stats['sms_delivery'] += 1

        return stats


class AdminOTPMonitor:
    """Admin uchun OTP monitoring"""

    def __init__(self):
        self.otp_manager = OTPManager()

    def get_recent_logs(self, limit: int = 20) -> list:
        """Oxirgi xavfsizlik loglari"""
        logs = SecurityLog.load_all()
        return logs[-limit:] if len(logs) > limit else logs

    def get_suspicious_activity(self) -> list:
        """Shubhali faoliyatlar"""
        logs = SecurityLog.load_all()
        suspicious = []

        for log in logs:
            if log['log_type'] in ['rate_limit', 'blocked', 'suspicious']:
                suspicious.append(log)

        return suspicious[-50:]  # Oxirgi 50 ta

    def get_blocked_phones(self) -> list:
        """Bloklangan telefon raqamlari"""
        logs = SecurityLog.load_all()
        blocked = {}

        for log in logs:
            if log['log_type'] == 'blocked':
                phone = log['phone']
                blocked[phone] = log

        return list(blocked.values())

    def format_stats_message(self) -> str:
        """Statistika xabarini formatlash"""
        stats = self.otp_manager.get_otp_stats()

        return (
            "📊 OTP Statistikasi\n"
            "═══════════════════\n\n"
            f"📱 Jami so'rovlar: {stats['total']}\n"
            f"📅 Bugun: {stats['today']}\n"
            f"✅ Tasdiqlangan: {stats['verified_today']}\n"
            f"❌ Bekor qilingan: {stats['failed_today']}\n\n"
            f"📲 Telegram: {stats['telegram_delivery']}\n"
            f"📩 SMS: {stats['sms_delivery']}"
        )

    def format_security_report(self) -> str:
        """Xavfsizlik hisobotini formatlash"""
        suspicious = self.get_suspicious_activity()

        if not suspicious:
            return "✅ Shubhali faoliyat aniqlanmadi."

        report = "⚠️ Xavfsizlik Hisoboti\n═══════════════════\n\n"

        for log in suspicious[-10:]:
            log_type = SecurityLog.LOG_TYPES.get(log['log_type'], log['log_type'])
            created = datetime.fromisoformat(log['created_at']).strftime('%d.%m %H:%M')
            report += f"• [{created}] {log_type}\n"
            report += f"  Tel: {log['phone']}\n"
            report += f"  {log['details']}\n\n"

        return report
