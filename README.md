# Nonbor Buyurtmalar Bot

Nonbor API dan kelgan buyurtmalarni Telegram guruhlarga yuboruvchi bot. Har bir restoran/biznes uchun alohida guruh, real-time buyurtma kuzatuvi va avtomatik muddati o'tgan buyurtmalarni tozalash.

## Asosiy xususiyatlari

- **Nonbor API Integration** - Real-time buyurtmalarni polling (har 3 sekund)
- **Multi-Seller** - Har bir biznes uchun alohida Telegram guruh
- **Order Workflow** - YANGI → QABUL QILINDI → TAYYOR → YETKAZILMOQDA → YAKUNLANDI
- **Auto Cleanup** - 5 daqiqa ichida qabul qilinmagan buyurtmalar avtomatik o'chiriladi
- **Staff Management** - Har bir sotuvchi uchun xodimlar boshqaruvi
- **OTP Verification** - Telegram orqali OTP tasdiqlash

---

## Tez boshlash

### 1. O'rnatish

```bash
# Loyiha papkasiga o'tish
cd seller-bot

# Virtual environment yaratish
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/Mac

# Kutubxonalarni o'rnatish
pip install -r requirements.txt
```

### 2. Sozlash

```bash
# .env fayl yaratish
copy .env.example .env
```

**.env faylini tahrirlash:**
```env
# Telegram Bot Token (@BotFather dan oling)
TELEGRAM_BOT_TOKEN=your_bot_token_here

# Admin Telegram ID'lari (vergul bilan ajratilgan)
ADMIN_IDS=123456789,987654321

# Nonbor API
EXTERNAL_API_URL=https://test.nonbor.uz/api/v2/telegram_bot/get-order-for-courier/

# Buyurtma polling intervali (sekund)
POLL_INTERVAL=3

# Buyurtma muddati (daqiqa) - shu vaqtdan keyin qabul qilinmagan buyurtma o'chiriladi
ORDER_EXPIRY_MINUTES=5
```

### 3. Database (migrations)

```bash
python manage.py migrate
```

### 4. Botni ishga tushirish

```bash
python manage.py run_bot
```

---

## Bot qanday ishlaydi (to'liq ketma-ketlik)

### 1-bosqich: Nonbor API Polling

Bot har **3 sekundda** Nonbor API dan yangi buyurtmalarni tekshiradi:
```
https://test.nonbor.uz/api/v2/telegram_bot/get-order-for-courier/
```

Faqat **CHECKING** statusidagi buyurtmalar olinadi:
- `CHECKING` - To'lov qilingan, rasmiylashtirilgan buyurtmalar

> **Eslatma:** `NEW` va `PENDING` statusidagi buyurtmalar olinmaydi, chunki ular hali to'liq rasmiylashtirilmagan.

### 2-bosqich: Buyurtmani guruhga yuborish

Buyurtma topilganda:
1. **Biznes nomi** bo'yicha tegishli sotuvchi topiladi
2. Sotuvchining **Telegram guruhiga** xabar yuboriladi
3. Xabarda **Qabul qilish** va **Rad etish** tugmalari bo'ladi

```
🛍️ YANGI BUYURTMA

📦 Buyurtma: #1234

📋 Mahsulotlar (2 ta):
  • Osh
    2 x 25,000 = 50,000 som
  • Coca-Cola
    15,000 som

💰 Jami: 65,000 som

⚠️ Faqat menejer qabul/rad qila oladi

[✅ Qabul qilish] [❌ Rad etish]
```

### 3-bosqich: Buyurtmani qabul qilish

Operator **"Qabul qilish"** tugmasini bosganda:
- Buyurtma statusi `accepted` ga o'zgaradi
- Yetkazib berish manzili ko'rsatiladi
- **"Tayyor"** tugmasi paydo bo'ladi

```
✅ QABUL QILINDI

👤 Operator: Ali Valiyev
🕐 Vaqt: 14:30 20.01.2026

🚚 Turi: Yetkazib berish
📍 Manzil: Toshkent, Navoiy ko'chasi 15

Buyurtma tayyor bo'lganda "Tayyor" tugmasini bosing

[🍽 Tayyor]
```

### 4-bosqich: Buyurtma tayyor

Operator **"Tayyor"** tugmasini bosganda:
- Buyurtma statusi `ready` ga o'zgaradi
- Mijoz telefon raqami va ma'lumotlari ko'rsatiladi
- Buyurtma turiga qarab tugma paydo bo'ladi:
  - **Yetkazib berish** → "Yetkazilmoqda" tugmasi
  - **Olib ketish** → "Yakunlandi" tugmasi

**Yetkazib berish uchun:**
```
🍽 TAYYOR

👤 Mijoz: Sardor Aliyev
📞 Telefon: +998901234567
📍 Manzil: Toshkent, Navoiy ko'chasi 15

[🚚 Yetkazilmoqda]
```

**Olib ketish uchun:**
```
🍽 TAYYOR

👤 Mijoz: Sardor Aliyev
📞 Telefon: +998901234567

[✅ Yakunlandi]
```

### 5-bosqich: Yetkazilmoqda (faqat delivery uchun)

**"Yetkazilmoqda"** tugmasi bosilganda:
- Buyurtma statusi `delivering` ga o'zgaradi
- **"Yakunlandi"** tugmasi paydo bo'ladi

### 6-bosqich: Yakunlandi

**"Yakunlash"** tugmasi bosilganda:
- Buyurtma statusi `completed` ga o'zgaradi
- Buyurtma muvaffaqiyatli yakunlandi

### Muddati o'tgan buyurtmalar

Bot har **2 sekundda** muddati o'tgan buyurtmalarni tekshiradi:
- Agar buyurtma **5 daqiqa** ichida qabul qilinmasa
- Guruhdan xabar **avtomatik o'chiriladi**
- Buyurtma statusi `expired` ga o'zgaradi

---

## Bot Komandalar

### Asosiy komandalar
```
/start          - Boshlash
/dashboard      - Boshqaruv paneli
/staff          - Xodimlar boshqaruvi
/stats          - Statistika
/earnings       - Daromad hisoboti
/orders         - Buyurtmalar ro'yxati
/help           - Yordam
```

### Admin Panel

Admin `/start` bosganda yangi admin panel ochiladi:

```
📊 ADMIN PANEL

[📊 Statistika]        - Buyurtmalar statistikasi (kunlik/haftalik/oylik/yillik)
[📋 Sotuvchilar]       - Viloyat/tuman bo'yicha sotuvchilar ro'yxati
[🔍 Buyurtma qidirish] - ID bo'yicha buyurtma qidirish
[🧪 Test buyurtma]     - Biznesga test buyurtma yuborish (pagination)
[📢 Xabarnoma]         - Shablon xabarlarni bizneslar guruhiga yuborish
```

#### Statistika
- Kunlik, haftalik, oylik va yillik filtrlar
- Buyurtmalar soni va foizlari
- Jami savdo summasi

#### Buyurtma qidirish
- ID raqami bo'yicha buyurtma topish
- Vaqt jadvali ko'rish
- Biznes va mijoz ma'lumotlari

#### Xabarnoma yuborish
- Shablon xabarlar yaratish, tahrirlash, o'chirish
- Barcha bizneslar yoki viloyat bo'yicha yuborish
- Yuborish natijasi statistikasi

### Admin CLI komandalar
```
/add_seller     - Sotuvchi qo'shish
/list_sellers   - Sotuvchilar ro'yxati
/set_group      - Guruh ulash
/delete_seller  - Sotuvchini o'chirish
/test_order     - Test buyurtma yuborish
/get_chat_id    - Guruh ID olish
```

### OTP Monitoring
```
/otp_stats      - OTP statistikasi
/otp_security   - Xavfsizlik hisoboti
```

---

## Biznes ro'yxatdan o'tish

Bizneslar **Nonbor platformasida** ro'yxatdan o'tadi:
🌐 https://business.nonbor.uz/

### Guruh ulash

1. Biznes egasi Telegram guruh yaratadi
2. Botni guruhga qo'shib, admin qiladi
3. Guruhda `/start` bosadi
4. Nonbor'da ro'yxatdan o'tgan telefon raqamini yuboradi
5. OTP kodi shaxsiy chatga keladi
6. Kodni guruhga yozib, ro'yxatdan o'tadi

> **Eslatma:** Sotuvchilar faqat Nonbor platformasidan ro'yxatdan o'tadi. Bot orqali qo'shib bo'lmaydi.

---

## Fayl strukturasi

```
seller-bot/
├── bot/
│   ├── __init__.py         # Bot application va job'lar
│   ├── core.py             # NotificationBot, API polling, cleanup
│   ├── handlers.py         # Command handlers
│   ├── callback_handler.py # Callback query handlers
│   ├── models.py           # Seller, Order, Staff modellari
│   ├── dashboard.py        # Vendor dashboard
│   ├── staff_manager.py    # Staff management
│   ├── otp_manager.py      # OTP verification
│   └── management/commands/
│       ├── run_bot.py      # Bot ishga tushirish
│       ├── add_seller.py   # Sotuvchi qo'shish
│       └── ...
├── data/
│   ├── sellers.json        # Sotuvchilar ma'lumotlari
│   ├── orders.json         # Buyurtmalar
│   ├── staff.json          # Xodimlar
│   ├── notification_templates.json  # Xabarnoma shablonlari
│   └── ...
├── services/
│   └── poller.py           # Standalone API poller
├── config/
│   ├── settings.py
│   └── urls.py
├── .env                    # Sozlamalar (git'ga qo'shilmaydi)
├── .env.example            # Namuna sozlamalar
├── requirements.txt
├── manage.py
├── Dockerfile
└── docker-compose.yml
```

---

## Muhim sozlamalar

| O'zgaruvchi | Tavsif | Default |
|-------------|--------|---------|
| `TELEGRAM_BOT_TOKEN` | Bot tokeni | - |
| `ADMIN_IDS` | Admin Telegram ID'lari | - |
| `EXTERNAL_API_URL` | Nonbor API URL | - |
| `POLL_INTERVAL` | Polling intervali (sekund) | 3 |
| `ORDER_EXPIRY_MINUTES` | Buyurtma muddati (daqiqa) | 5 |

---

## Buyurtma statuslari

| Status | Tavsif |
|--------|--------|
| `new` | Yangi buyurtma (qabul qilinmagan) |
| `accepted` | Qabul qilindi |
| `ready` | Tayyor |
| `delivering` | Yetkazilmoqda |
| `completed` | Yakunlandi |
| `rejected` | Rad etildi |
| `expired` | Muddati o'tdi (avtomatik o'chirildi) |

---

## Docker bilan ishga tushirish

```bash
# Build va ishga tushirish
docker-compose up -d

# Loglarni ko'rish
docker-compose logs -f

# To'xtatish
docker-compose down
```

---

## Xavfsizlik

- `.env` faylni **hech qachon** git'ga qo'shmang
- Production'da `DEBUG=False` qiling
- Bot tokenini **maxfiy saqlang**
- Admin ID'larni tekshiring

---

## Muammolar va yechimlar

### 409 Conflict xatosi
Bot allaqachon ishlab turibdi. Boshqa terminal/jarayonda ishlab turgan botni to'xtating.

### Buyurtmalar kelmayapti
1. `EXTERNAL_API_URL` to'g'ri ekanligini tekshiring
2. Sotuvchi nomi Nonbor dagi biznes nomi bilan **bir xil** bo'lishi kerak
3. Sotuvchiga guruh ulangan bo'lishi kerak

### Bot guruhga xabar yubora olmayapti
1. Bot guruhda **admin** bo'lishi kerak
2. Guruh ID to'g'ri ekanligini tekshiring (manfiy son bo'ladi)

---

## Yordam

Muammolar bo'lsa:
- Telegram: @ikhtiyor_s
- GitHub Issues: https://github.com/Ikhtiyor-s/nonbor-buyurtmalarbot/issues
