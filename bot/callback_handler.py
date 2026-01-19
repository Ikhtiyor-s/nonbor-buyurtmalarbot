import os
import json
import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# Pagination uchun konstantalar
ITEMS_PER_PAGE = 10

# Viloyatlar ma'lumotlarini yuklash
def load_regions():
    regions_file = os.path.join(os.path.dirname(__file__), '..', 'data', 'regions.json')
    if os.path.exists(regions_file):
        with open(regions_file, 'r', encoding='utf-8') as f:
            return json.load(f).get('regions', [])
    return []

def get_region_name(region_id):
    regions = load_regions()
    for r in regions:
        if r['id'] == region_id:
            return r['name']
    return region_id

def get_district_name(region_id, district_id):
    regions = load_regions()
    for r in regions:
        if r['id'] == region_id:
            for d in r.get('districts', []):
                if d['id'] == district_id:
                    return d['name']
    return district_id


def get_back_button(callback_data="back_admin"):
    """Ortga qaytish tugmasi"""
    return [[InlineKeyboardButton("◀️ Ortga", callback_data=callback_data)]]


def get_admin_menu_keyboard():
    """Admin panel asosiy menyu tugmalari"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Statistika", callback_data="admin_stats")],
        [InlineKeyboardButton("📋 Sotuvchilar ro'yxati", callback_data="admin_sellers")],
        [InlineKeyboardButton("🔍 Buyurtma qidirish", callback_data="admin_search")],
        [InlineKeyboardButton("🧪 Test buyurtma", callback_data="admin_test")],
        [InlineKeyboardButton("📢 Xabarnoma yuborish", callback_data="admin_notify")]
    ])


def get_main_menu_keyboard():
    """Asosiy menyu tugmalari (deprecated - use get_admin_menu_keyboard)"""
    return get_admin_menu_keyboard()


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    if data.startswith("accept_"):
        order_id = data.replace("accept_", "")
        await accept_order(order_id, query)

    elif data.startswith("ready_"):
        order_id = data.replace("ready_", "")
        await mark_order_ready(order_id, query)

    elif data.startswith("delivering_"):
        order_id = data.replace("delivering_", "")
        await mark_order_delivering(order_id, query)

    elif data.startswith("completed_"):
        order_id = data.replace("completed_", "")
        await mark_order_completed(order_id, query)

    elif data.startswith("reject_"):
        order_id = data.replace("reject_", "")
        await reject_order(order_id, query)

    elif data == "menu_back" or data == "back_admin":
        # Admin panel asosiy menyuga qaytish
        user = query.from_user
        message = (
            f"👨‍💼 <b>ADMIN PANEL</b>\n\n"
            f"Salom, <b>{user.first_name}</b>!\n\n"
            f"🤖 Nonbor Buyurtmalar Bot - bizneslar uchun buyurtma notification tizimi.\n\n"
            f"Quyidagi tugmalardan foydalaning:"
        )
        await query.message.edit_text(
            text=message,
            reply_markup=get_admin_menu_keyboard(),
            parse_mode='HTML'
        )

    # ==========================================
    # YANGI ADMIN PANEL CALLBACKS
    # ==========================================
    elif data == "admin_stats":
        await show_admin_stats(query)

    elif data == "admin_sellers":
        await show_regions_list(query)

    elif data == "admin_search":
        await show_order_search(query, context)

    elif data == "admin_test":
        await show_test_order_businesses(query, 0)

    elif data == "admin_notify":
        await show_notification_templates(query)

    elif data.startswith("stats_"):
        period = data.replace("stats_", "")
        await show_admin_stats(query, period)

    elif data.startswith("test_page_"):
        page = int(data.replace("test_page_", ""))
        await show_test_order_businesses(query, page)

    elif data.startswith("test_send_"):
        seller_id = data.replace("test_send_", "")
        await send_test_order(query, seller_id)

    elif data == "notify_add":
        await start_add_notification_template(query, context)

    elif data.startswith("notify_view_"):
        template_id = data.replace("notify_view_", "")
        await show_notification_template(query, template_id)

    elif data.startswith("notify_edit_"):
        template_id = data.replace("notify_edit_", "")
        await start_edit_notification_template(query, template_id, context)

    elif data.startswith("notify_delete_"):
        template_id = data.replace("notify_delete_", "")
        await delete_notification_template(query, template_id)

    elif data.startswith("notify_send_"):
        template_id = data.replace("notify_send_", "")
        await show_notification_recipients(query, template_id, context)

    elif data == "notify_all":
        await select_all_recipients(query, context)

    elif data.startswith("notify_region_"):
        region_id = data.replace("notify_region_", "")
        await toggle_region_selection(query, region_id, context)

    elif data == "notify_confirm":
        await confirm_send_notification(query, context)

    elif data == "notify_do_send":
        await do_send_notification(query, context)

    elif data == "notify_cancel":
        # Context tozalash
        context.user_data.pop('adding_template', None)
        context.user_data.pop('editing_template', None)
        context.user_data.pop('template_step', None)
        context.user_data.pop('new_template_title', None)
        await show_notification_templates(query)

    elif data == "menu_add_seller":
        keyboard = get_back_button()
        await query.message.edit_text(
            "➕ <b>Sotuvchi qo'shish</b>\n\n"
            "📝 <b>Format:</b>\n"
            "<code>/add_seller +998XXXXXXXXX Ism Familya</code>\n\n"
            "📌 <b>Misol:</b>\n"
            "<code>/add_seller +998901234567 Ali Valiyev</code>",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data == "menu_list_sellers":
        await show_regions_list(query)

    elif data == "menu_sellers":
        await show_regions_list(query)

    elif data.startswith("region_"):
        region_id = data.replace("region_", "")
        await show_districts_list(query, region_id)

    elif data.startswith("district|"):
        # district|REGIONID|DISTRICTID
        parts = data.split("|")
        if len(parts) == 3:
            _, region_id, district_id = parts
            await show_sellers_by_location(query, region_id, district_id)

    elif data == "back_to_regions":
        await show_regions_list(query)

    # Pagination callbacks
    elif data.startswith("page_regions|"):
        page = int(data.split("|")[1])
        await show_regions_list(query, page)

    elif data.startswith("page_district|"):
        parts = data.split("|")
        region_id = parts[1]
        page = int(parts[2])
        await show_districts_list(query, region_id, page)

    elif data.startswith("page_sellers|"):
        parts = data.split("|")
        region_id = parts[1]
        district_id = parts[2]
        page = int(parts[3])
        await show_sellers_by_location(query, region_id, district_id, page)

    elif data == "menu_test_order":
        keyboard = get_back_button()
        await query.message.edit_text(
            "🧪 <b>Test buyurtma</b>\n\n"
            "Birinchi sotuvchiga yuborish:\n"
            "<code>/test_order</code>\n\n"
            "Aniq sotuvchiga yuborish:\n"
            "<code>/test_order SELLER_ID</code>",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data == "menu_stats":
        await show_stats(query)

    elif data == "stats_daily":
        await show_stats(query, period="daily")

    elif data == "stats_monthly":
        await show_stats(query, period="monthly")

    elif data == "stats_yearly":
        await show_stats(query, period="yearly")

    elif data == "stats_all":
        await show_stats(query, period="all")

    elif data == "menu_help":
        await show_help(query)

    elif data == "menu_set_group":
        # Guruh ulash uchun barcha sotuvchilar ro'yxati (asosiy menyudan)
        await show_sellers_for_group(query, None, None)

    elif data.startswith("setgroup_region|"):
        # Viloyat bo'yicha guruh ulash: setgroup_region|REGIONID
        region_id = data.replace("setgroup_region|", "")
        await show_sellers_for_group(query, region_id, None)

    elif data.startswith("setgroup_district|"):
        # Tuman bo'yicha guruh ulash: setgroup_district|REGIONID|DISTRICTID
        parts = data.split("|")
        if len(parts) == 3:
            _, region_id, district_id = parts
            await show_sellers_for_group(query, region_id, district_id)

    elif data.startswith("setgroup_"):
        # Sotuvchi tanlandi, guruh ID so'rash
        seller_id = data.replace("setgroup_", "")
        await ask_group_id(query, seller_id, context)

    elif data.startswith("cancelsetgroup_"):
        # Guruh ulashni bekor qilish
        context.user_data.pop('waiting_group_id', None)
        await show_sellers_list(query, for_group_setup=True)

    elif data.startswith("testorder_"):
        # Test buyurtma yuborish
        seller_id = data.replace("testorder_", "")
        await send_test_order(query, seller_id)

    elif data.startswith("edit_seller|"):
        # Sotuvchini tahrirlash
        seller_id = data.split("|")[1]
        await show_edit_seller_menu(query, seller_id)

    elif data.startswith("edit_phone|"):
        # Telefon raqamini tahrirlash
        seller_id = data.split("|")[1]
        await ask_new_phone(query, seller_id, context)

    elif data.startswith("cancel_edit|"):
        # Tahrirlashni bekor qilish
        seller_id = data.split("|")[1]
        context.user_data.pop('waiting_new_phone', None)
        await ask_group_id(query, seller_id, context)

    elif data.startswith("remove_group|"):
        # Guruhni o'chirish
        seller_id = data.split("|")[1]
        await remove_seller_group(query, seller_id)

    # ==========================================
    # Seller Dashboard Callbacks
    # ==========================================
    elif data.startswith("seller_stats_"):
        # Sotuvchi statistikasi - faqat shaxsiy chatda
        if query.message.chat.type != 'private':
            await query.answer("📊 Statistikani ko'rish uchun botga o'ting", show_alert=True)
            return
        seller_id = data.replace("seller_stats_", "")
        await show_seller_stats(query, seller_id)

    elif data.startswith("seller_staff_"):
        # Xodimlar boshqaruvi - faqat shaxsiy chatda
        if query.message.chat.type != 'private':
            await query.answer("👥 Xodimlarni boshqarish uchun botga o'ting", show_alert=True)
            return
        seller_id = data.replace("seller_staff_", "")
        await show_seller_staff(query, seller_id)

    elif data.startswith("add_staff_"):
        # Yangi xodim qo'shish - faqat shaxsiy chatda
        if query.message.chat.type != 'private':
            await query.answer("➕ Xodim qo'shish uchun botga o'ting", show_alert=True)
            return
        seller_id = data.replace("add_staff_", "")
        await ask_staff_info(query, seller_id, context)

    elif data.startswith("remove_staff|"):
        # Xodimni o'chirish (eski format)
        parts = data.split("|")
        seller_id = parts[1]
        staff_id = parts[2]
        await remove_staff_member(query, seller_id, staff_id)

    elif data.startswith("rmstaff_"):
        # Xodimni o'chirish - tasdiqlash so'rash
        staff_id = data.replace("rmstaff_", "")
        await confirm_remove_staff(query, staff_id)

    elif data.startswith("delstaff_"):
        # Xodimni o'chirishni tasdiqlash
        staff_id = data.replace("delstaff_", "")
        await remove_staff_member_by_id(query, staff_id)

    elif data.startswith("seller_back_"):
        # Sotuvchi dashboardiga qaytish
        seller_id = data.replace("seller_back_", "")
        await show_seller_dashboard(query, seller_id)

    elif data.startswith("seller_settings_"):
        # Sotuvchi sozlamalari
        seller_id = data.replace("seller_settings_", "")
        await show_seller_settings(query, seller_id)


async def remove_seller_group(query, seller_id):
    """Sotuvchidan guruhni o'chirish"""
    from .models import Seller

    seller = Seller.get(id=seller_id)
    if not seller:
        await query.answer("Sotuvchi topilmadi!", show_alert=True)
        return

    old_group = seller.group_title or seller.group_chat_id
    seller.group_chat_id = ""
    seller.group_title = ""
    seller.group_invite_link = ""
    seller.save()

    await query.answer(f"Guruh o'chirildi: {old_group}", show_alert=True)
    await show_edit_seller_menu(query, seller_id)


async def show_regions_list(query, page=0):
    """Viloyatlar ro'yxatini ko'rsatish - barcha oshxonalar + viloyatlar (pagination bilan)"""
    from .models import Seller

    sellers = Seller.filter(is_active=True)
    total_sellers = len(sellers)

    if not sellers:
        keyboard = [
            [InlineKeyboardButton("➕ Sotuvchi qo'shish", callback_data="menu_add_seller")],
            [InlineKeyboardButton("◀️ Ortga", callback_data="menu_back")]
        ]
        await query.message.edit_text(
            "📭 <b>Hozircha sotuvchilar yo'q</b>\n\n"
            "Yangi sotuvchi qo'shish uchun tugmani bosing yoki:\n"
            "<code>/add_seller +998XXXXXXXXX Ism</code>",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # Pagination hisoblash
    total_pages = (total_sellers + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    start_idx = page * ITEMS_PER_PAGE
    end_idx = min(start_idx + ITEMS_PER_PAGE, total_sellers)
    page_sellers = sellers[start_idx:end_idx]

    # Barcha oshxonalar ro'yxati
    message = f"📋 <b>Barcha oshxonalar</b> ({total_sellers} ta)\n"
    if total_pages > 1:
        message += f"📄 Sahifa: {page + 1}/{total_pages}\n"
    message += "\n"

    for i, seller in enumerate(page_sellers, start_idx + 1):
        status = "✅" if seller.group_chat_id else "⚠️"
        message += f"{status} <b>{i}. {seller.full_name}</b>\n"
        message += f"    📞 {seller.phone}\n"
        if hasattr(seller, 'address') and seller.address:
            message += f"    📍 {seller.address}\n"
        if seller.group_chat_id:
            group_name = seller.group_title if hasattr(seller, 'group_title') and seller.group_title else "Guruh"
            if hasattr(seller, 'group_invite_link') and seller.group_invite_link:
                message += f"    👥 <a href=\"{seller.group_invite_link}\">{group_name}</a>\n"
            else:
                message += f"    👥 {group_name}\n"
        else:
            message += f"    ⚠️ <i>Guruh ulanmagan</i>\n"
        message += "\n"

    message += "━━━━━━━━━━━━━━━━━━━━\n"
    message += "✅ - Guruh ulangan | ⚠️ - Guruh ulanmagan\n\n"
    message += "🗺 <b>Viloyat bo'yicha filtrlash:</b>"

    # Viloyatlar bo'yicha guruhlash
    regions = load_regions()
    region_counts = {}
    no_region_count = 0

    for seller in sellers:
        if seller.region:
            region_counts[seller.region] = region_counts.get(seller.region, 0) + 1
        else:
            no_region_count += 1

    keyboard = []

    # 1. Guruh ulash tugmasi
    keyboard.append([InlineKeyboardButton("🔗 Guruh ulash", callback_data="menu_set_group")])

    # 2. Viloyatlar
    for region in regions:
        count = region_counts.get(region['id'], 0)
        if count > 0:
            btn_text = f"🏙 {region['name']} ({count})"
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"region_{region['id']}")])

    # Viloyati belgilanmaganlar
    if no_region_count > 0:
        keyboard.append([InlineKeyboardButton(f"❓ Viloyati noma'lum ({no_region_count})", callback_data="region_unknown")])

    # 3. Pagination tugmalari
    if total_pages > 1:
        pagination_btns = []
        if page > 0:
            pagination_btns.append(InlineKeyboardButton("⬅️ Oldingi", callback_data=f"page_regions|{page - 1}"))
        if page < total_pages - 1:
            pagination_btns.append(InlineKeyboardButton("Keyingi ➡️", callback_data=f"page_regions|{page + 1}"))
        if pagination_btns:
            keyboard.append(pagination_btns)

    # 4. Ortga tugmasi
    keyboard.append([InlineKeyboardButton("◀️ Ortga", callback_data="menu_back")])

    await query.message.edit_text(message, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard), disable_web_page_preview=True)


async def show_districts_list(query, region_id, page=0):
    """Viloyat tanlanganda - shu viloyat oshxonalari + tumanlar (pagination bilan)"""
    from .models import Seller

    sellers = Seller.filter(is_active=True)

    if region_id == "unknown":
        # Viloyati belgilanmagan sotuvchilar
        filtered_sellers = [s for s in sellers if not s.region]
        region_name = "Viloyati noma'lum"
    else:
        filtered_sellers = [s for s in sellers if s.region == region_id]
        region_name = get_region_name(region_id)

    if not filtered_sellers:
        keyboard = [[InlineKeyboardButton("◀️ Ortga", callback_data="back_to_regions")]]
        await query.message.edit_text(
            f"📭 <b>{region_name}</b> da sotuvchi yo'q",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # Pagination hisoblash
    total_count = len(filtered_sellers)
    total_pages = (total_count + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    start_idx = page * ITEMS_PER_PAGE
    end_idx = min(start_idx + ITEMS_PER_PAGE, total_count)
    page_sellers = filtered_sellers[start_idx:end_idx]

    # Viloyat oshxonalari ro'yxati
    message = f"🏙 <b>{region_name}</b> ({total_count} ta)\n"
    if total_pages > 1:
        message += f"📄 Sahifa: {page + 1}/{total_pages}\n"
    message += "\n"

    for i, seller in enumerate(page_sellers, start_idx + 1):
        status = "✅" if seller.group_chat_id else "⚠️"
        message += f"{status} <b>{i}. {seller.full_name}</b>\n"
        message += f"    📞 {seller.phone}\n"
        if hasattr(seller, 'address') and seller.address:
            message += f"    📍 {seller.address}\n"
        if seller.group_chat_id:
            group_name = seller.group_title if hasattr(seller, 'group_title') and seller.group_title else "Guruh"
            if hasattr(seller, 'group_invite_link') and seller.group_invite_link:
                message += f"    👥 <a href=\"{seller.group_invite_link}\">{group_name}</a>\n"
            else:
                message += f"    👥 {group_name}\n"
        else:
            message += f"    ⚠️ <i>Guruh ulanmagan</i>\n"
        message += "\n"

    message += "━━━━━━━━━━━━━━━━━━━━\n"
    message += "✅ - Guruh ulangan | ⚠️ - Guruh ulanmagan\n\n"
    message += "🗺 <b>Tuman bo'yicha filtrlash:</b>"

    # Tumanlar bo'yicha guruhlash
    regions = load_regions()
    district_counts = {}
    no_district_count = 0

    for seller in filtered_sellers:
        if seller.district:
            district_counts[seller.district] = district_counts.get(seller.district, 0) + 1
        else:
            no_district_count += 1

    keyboard = []

    # 1. Guruh ulash tugmasi (shu viloyat uchun)
    keyboard.append([InlineKeyboardButton("🔗 Guruh ulash", callback_data=f"setgroup_region|{region_id}")])

    # 2. Tumanlar
    if region_id != "unknown":
        for region in regions:
            if region['id'] == region_id:
                for district in region.get('districts', []):
                    count = district_counts.get(district['id'], 0)
                    if count > 0:
                        btn_text = f"📍 {district['name']} ({count})"
                        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"district|{region_id}|{district['id']}")])
                break

    # Tumani belgilanmaganlar
    if no_district_count > 0:
        keyboard.append([InlineKeyboardButton(f"❓ Tumani noma'lum ({no_district_count})", callback_data=f"district|{region_id}|unknown")])

    # 3. Pagination tugmalari
    if total_pages > 1:
        pagination_btns = []
        if page > 0:
            pagination_btns.append(InlineKeyboardButton("⬅️ Oldingi", callback_data=f"page_district|{region_id}|{page - 1}"))
        if page < total_pages - 1:
            pagination_btns.append(InlineKeyboardButton("Keyingi ➡️", callback_data=f"page_district|{region_id}|{page + 1}"))
        if pagination_btns:
            keyboard.append(pagination_btns)

    # 4. Ortga tugmasi (viloyatlarga qaytish)
    keyboard.append([InlineKeyboardButton("◀️ Ortga", callback_data="back_to_regions")])

    await query.message.edit_text(message, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard), disable_web_page_preview=True)


async def show_sellers_by_location(query, region_id, district_id, page=0):
    """Tuman tanlanganda - shu tuman oshxonalari + guruh ulash + ortga (pagination bilan)"""
    from .models import Seller

    sellers = Seller.filter(is_active=True)

    # Filtrlash
    if region_id == "unknown":
        filtered_sellers = [s for s in sellers if not s.region]
        location_name = "Viloyati noma'lum"
    elif district_id is None:
        filtered_sellers = [s for s in sellers if s.region == region_id]
        location_name = get_region_name(region_id)
    elif district_id == "unknown":
        filtered_sellers = [s for s in sellers if s.region == region_id and not s.district]
        location_name = f"{get_region_name(region_id)} - Tumani noma'lum"
    else:
        filtered_sellers = [s for s in sellers if s.region == region_id and s.district == district_id]
        location_name = f"{get_region_name(region_id)} - {get_district_name(region_id, district_id)}"

    if not filtered_sellers:
        keyboard = [[InlineKeyboardButton("◀️ Ortga", callback_data=f"region_{region_id}")]]
        await query.message.edit_text(
            f"📭 <b>{location_name}</b> da sotuvchi yo'q",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # Pagination hisoblash
    total_count = len(filtered_sellers)
    total_pages = (total_count + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    start_idx = page * ITEMS_PER_PAGE
    end_idx = min(start_idx + ITEMS_PER_PAGE, total_count)
    page_sellers = filtered_sellers[start_idx:end_idx]

    # Tuman oshxonalari ro'yxati
    message = f"📍 <b>{location_name}</b> ({total_count} ta)\n"
    if total_pages > 1:
        message += f"📄 Sahifa: {page + 1}/{total_pages}\n"
    message += "\n"

    for i, seller in enumerate(page_sellers, start_idx + 1):
        status = "✅" if seller.group_chat_id else "⚠️"
        message += f"{status} <b>{i}. {seller.full_name}</b>\n"
        message += f"    📞 {seller.phone}\n"
        if hasattr(seller, 'address') and seller.address:
            message += f"    📍 {seller.address}\n"
        if seller.group_chat_id:
            group_name = seller.group_title if hasattr(seller, 'group_title') and seller.group_title else "Guruh"
            if hasattr(seller, 'group_invite_link') and seller.group_invite_link:
                message += f"    👥 <a href=\"{seller.group_invite_link}\">{group_name}</a>\n"
            else:
                message += f"    👥 {group_name}\n"
        else:
            message += f"    ⚠️ <i>Guruh ulanmagan</i>\n"
        message += "\n"

    message += "━━━━━━━━━━━━━━━━━━━━\n"
    message += "✅ - Guruh ulangan | ⚠️ - Guruh ulanmagan"

    keyboard = []

    # 1. Guruh ulash tugmasi (shu tuman uchun)
    keyboard.append([InlineKeyboardButton("🔗 Guruh ulash", callback_data=f"setgroup_district|{region_id}|{district_id}")])

    # 2. Pagination tugmalari
    if total_pages > 1:
        pagination_btns = []
        if page > 0:
            pagination_btns.append(InlineKeyboardButton("⬅️ Oldingi", callback_data=f"page_sellers|{region_id}|{district_id}|{page - 1}"))
        if page < total_pages - 1:
            pagination_btns.append(InlineKeyboardButton("Keyingi ➡️", callback_data=f"page_sellers|{region_id}|{district_id}|{page + 1}"))
        if pagination_btns:
            keyboard.append(pagination_btns)

    # 3. Ortga tugmasi (viloyatga qaytish)
    keyboard.append([InlineKeyboardButton("◀️ Ortga", callback_data=f"region_{region_id}")])

    await query.message.edit_text(message, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard), disable_web_page_preview=True)


async def show_sellers_for_group(query, region_id, district_id):
    """Guruh ulash uchun filtrlangan sotuvchilar ro'yxati"""
    from .models import Seller

    sellers = Seller.filter(is_active=True)

    # Filtrlash
    if region_id is None:
        # Barcha sotuvchilar
        filtered_sellers = sellers
        location_name = "Barcha oshxonalar"
        back_callback = "back_to_regions"
    elif district_id is None or district_id == "":
        # Viloyat bo'yicha
        if region_id == "unknown":
            filtered_sellers = [s for s in sellers if not s.region]
            location_name = "Viloyati noma'lum"
        else:
            filtered_sellers = [s for s in sellers if s.region == region_id]
            location_name = get_region_name(region_id)
        back_callback = f"region_{region_id}"
    else:
        # Tuman bo'yicha
        if district_id == "unknown":
            filtered_sellers = [s for s in sellers if s.region == region_id and not s.district]
            location_name = f"{get_region_name(region_id)} - Tumani noma'lum"
        else:
            filtered_sellers = [s for s in sellers if s.region == region_id and s.district == district_id]
            location_name = f"{get_region_name(region_id)} - {get_district_name(region_id, district_id)}"
        back_callback = f"district|{region_id}|{district_id}"

    if not filtered_sellers:
        keyboard = [[InlineKeyboardButton("◀️ Ortga", callback_data=back_callback)]]
        await query.message.edit_text(
            f"📭 <b>{location_name}</b> da sotuvchi yo'q",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    message = f"🔗 <b>Guruh ulash</b>\n\n"
    message += f"📍 <b>{location_name}</b>\n"
    message += f"Qaysi sotuvchiga guruh ulashni xohlaysiz?\n\n"

    keyboard = []
    for i, seller in enumerate(filtered_sellers, 1):
        status = "✅" if seller.group_chat_id else "⚠️"
        btn_text = f"{status} {i}. {seller.full_name}"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"setgroup_{seller.id}")])

    keyboard.append([InlineKeyboardButton("◀️ Ortga", callback_data=back_callback)])

    await query.message.edit_text(message, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard), disable_web_page_preview=True)


async def show_sellers_list(query, for_group_setup=False):
    from .models import Seller

    sellers = Seller.filter(is_active=True)

    if not sellers:
        keyboard = [
            [InlineKeyboardButton("➕ Sotuvchi qo'shish", callback_data="menu_add_seller")],
            [InlineKeyboardButton("◀️ Ortga", callback_data="menu_back")]
        ]
        await query.message.edit_text(
            "📭 <b>Hozircha sotuvchilar yo'q</b>\n\n"
            "Yangi sotuvchi qo'shish uchun tugmani bosing yoki:\n"
            "<code>/add_seller +998XXXXXXXXX Ism</code>",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if for_group_setup:
        # Guruh ulash uchun sotuvchilar ro'yxati
        message = "🔗 <b>Guruh ulash</b>\n\n"
        message += "Qaysi sotuvchiga guruh ulashni xohlaysiz?\n"
        message += "Sotuvchini tanlang:\n\n"

        keyboard = []
        for i, seller in enumerate(sellers, 1):
            status = "✅" if seller.group_chat_id else "⚠️"
            btn_text = f"{status} {i}. {seller.full_name}"
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"setgroup_{seller.id}")])

        keyboard.append([InlineKeyboardButton("◀️ Ortga", callback_data="menu_back")])

        await query.message.edit_text(message, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard), disable_web_page_preview=True)
    else:
        # Oddiy ro'yxat ko'rsatish
        message = f"📋 <b>Faol sotuvchilar</b> ({len(sellers)} ta)\n\n"

        for i, seller in enumerate(sellers, 1):
            status = "✅" if seller.group_chat_id else "⚠️"
            message += f"{status} <b>{i}. {seller.full_name}</b>\n"
            message += f"    📞 {seller.phone}\n"
            if hasattr(seller, 'address') and seller.address:
                message += f"    📍 {seller.address}\n"
            message += f"    🆔 <code>{seller.id[:8]}...</code>\n"
            if seller.group_chat_id:
                message += f"    👥 Guruh ulangan\n"
            else:
                message += f"    ⚠️ <i>Guruh ulanmagan</i>\n"
            message += "\n"

        message += "━━━━━━━━━━━━━━━━━━━━\n"
        message += "✅ - Guruh ulangan | ⚠️ - Guruh ulanmagan"

        keyboard = [
            [InlineKeyboardButton("🔗 Guruh ulash", callback_data="menu_set_group")],
            [InlineKeyboardButton("◀️ Ortga", callback_data="menu_back")]
        ]
        await query.message.edit_text(message, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard), disable_web_page_preview=True)


async def show_stats(query, period="all"):
    from .models import Seller, Order

    sellers = Seller.filter(is_active=True)
    all_orders = Order.load_all()

    # Vaqt filtrlash
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    year_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)

    def filter_orders_by_date(orders, start_date):
        filtered = []
        for o in orders:
            created = o.get('created_at', '')
            if created:
                try:
                    order_date = datetime.fromisoformat(created.replace('Z', '+00:00'))
                    if order_date.replace(tzinfo=None) >= start_date:
                        filtered.append(o)
                except:
                    pass
        return filtered

    # Davr bo'yicha filtrlaymiz
    if period == "daily":
        filtered_orders = filter_orders_by_date(all_orders, today_start)
        period_title = "📅 Bugungi"
    elif period == "monthly":
        filtered_orders = filter_orders_by_date(all_orders, month_start)
        period_title = "📆 Oylik"
    elif period == "yearly":
        filtered_orders = filter_orders_by_date(all_orders, year_start)
        period_title = "📊 Yillik"
    else:
        filtered_orders = all_orders
        period_title = "📊 Umumiy"

    total_sellers = len(sellers)
    connected_sellers = len([s for s in sellers if s.group_chat_id])
    total_orders = len(filtered_orders)
    accepted_orders = len([o for o in filtered_orders if o.get('status') == 'accepted'])
    rejected_orders = len([o for o in filtered_orders if o.get('status') == 'rejected'])
    pending_orders = len([o for o in filtered_orders if o.get('status') == 'new'])

    # Jami summa
    total_amount = sum(o.get('total_amount', 0) for o in filtered_orders)

    # Davr tugmalari
    keyboard = [
        [
            InlineKeyboardButton("📅 Kunlik" + (" ✓" if period == "daily" else ""), callback_data="stats_daily"),
            InlineKeyboardButton("📆 Oylik" + (" ✓" if period == "monthly" else ""), callback_data="stats_monthly"),
        ],
        [
            InlineKeyboardButton("📊 Yillik" + (" ✓" if period == "yearly" else ""), callback_data="stats_yearly"),
            InlineKeyboardButton("📋 Barchasi" + (" ✓" if period == "all" else ""), callback_data="stats_all"),
        ],
        [InlineKeyboardButton("◀️ Ortga", callback_data="menu_back")]
    ]

    await query.message.edit_text(
        f"{period_title} <b>Statistika</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "👥 <b>Sotuvchilar:</b>\n"
        f"    Jami: {total_sellers} ta\n"
        f"    Guruh ulangan: {connected_sellers} ta\n"
        f"    Ulanmagan: {total_sellers - connected_sellers} ta\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📦 <b>Buyurtmalar:</b>\n"
        f"    Jami: {total_orders} ta\n"
        f"    ✅ Qabul qilingan: {accepted_orders} ta\n"
        f"    ❌ Rad etilgan: {rejected_orders} ta\n"
        f"    ⏳ Kutilmoqda: {pending_orders} ta\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>Jami summa:</b> {total_amount:,.0f} so'm".replace(",", " "),
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def show_help(query):
    keyboard = [
        [InlineKeyboardButton("💬 Qo'llab-quvvatlash", url="https://t.me/NonborSupportBot")],
        [InlineKeyboardButton("◀️ Ortga", callback_data="menu_back")]
    ]
    await query.message.edit_text(
        "📚 <b>Yordam - Barcha buyruqlar</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "👥 <b>Sotuvchilar boshqaruvi:</b>\n\n"
        "➕ /add_seller <code>+998XXXXXXXXX Ism</code>\n"
        "    <i>Yangi sotuvchi qo'shish</i>\n\n"
        "📋 /list_sellers\n"
        "    <i>Barcha sotuvchilar ro'yxati</i>\n\n"
        "🔗 /set_group <code>ID CHAT_ID</code>\n"
        "    <i>Sotuvchiga guruh ulash</i>\n\n"
        "🗑 /delete_seller <code>ID</code>\n"
        "    <i>Sotuvchini o'chirish</i>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🧪 <b>Test va ma'lumot:</b>\n\n"
        "🧪 /test_order <code>[ID]</code>\n"
        "    <i>Test buyurtma yuborish</i>\n\n"
        "📍 /get_chat_id\n"
        "    <i>Joriy chat ID ni olish</i>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "💡 <b>Maslahat:</b> Guruhga botni qo'shib, /get_chat_id yozing\n\n"
        "❓ <b>Savollar bo'lsa:</b> Quyidagi tugmani bosing",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def send_test_order(query, seller_id):
    """Test buyurtma yuborish"""
    from .models import Seller
    from .core import NotificationBot
    import time

    seller = Seller.get(id=seller_id)
    if not seller:
        await query.message.edit_text(
            "❌ Sotuvchi topilmadi!",
            reply_markup=InlineKeyboardMarkup(get_back_button())
        )
        return

    if not seller.group_chat_id:
        keyboard = [
            [InlineKeyboardButton("🔗 Guruh ulash", callback_data=f"setgroup_{seller_id}")],
            [InlineKeyboardButton("◀️ Ortga", callback_data="menu_back")]
        ]
        await query.message.edit_text(
            f"⚠️ <b>{seller.full_name}</b> uchun guruh ulanmagan!\n\n"
            f"Avval guruh ulang.",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # Yuborish jarayoni
    await query.message.edit_text(
        f"⏳ <b>Test buyurtma yuborilmoqda...</b>\n\n"
        f"👤 Sotuvchi: {seller.full_name}",
        parse_mode='HTML'
    )

    test_order_data = {
        "id": f"TEST-{int(time.time())}",
        "seller_id": seller.id,
        "status": "new",
        "customer": {
            "name": "Test Mijoz",
            "phone": "+998901112233"
        },
        "total": 150000,
        "items": [
            {"name": "Pizza Margarita", "price": 65000, "quantity": 1},
            {"name": "Coca-Cola 1L", "price": 15000, "quantity": 2},
            {"name": "Lavash", "price": 55000, "quantity": 1}
        ]
    }

    bot = NotificationBot()
    success = await bot.send_order_notification(test_order_data)

    keyboard = [
        [InlineKeyboardButton("🧪 Yana test", callback_data=f"testorder_{seller_id}")],
        [InlineKeyboardButton("◀️ Ortga", callback_data="menu_back")]
    ]

    if success:
        await query.message.edit_text(
            f"✅ <b>Test buyurtma yuborildi!</b>\n\n"
            f"👤 Sotuvchi: {seller.full_name}\n"
            f"📦 Buyurtma: #{test_order_data['id']}\n"
            f"💰 Summa: {test_order_data['total']:,} so'm\n\n"
            f"Guruhni tekshiring - xabar kelgan bo'lishi kerak.",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await query.message.edit_text(
            f"❌ <b>Xatolik!</b>\n\n"
            f"Test buyurtma yuborishda muammo yuz berdi.\n"
            f"Guruh ID to'g'riligini tekshiring.\n\n"
            f"👥 Guruh ID: <code>{seller.group_chat_id}</code>",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


async def ask_group_id(query, seller_id, context):
    """Sotuvchi uchun guruh ID so'rash"""
    from .models import Seller

    seller = Seller.get(id=seller_id)
    if not seller:
        await query.message.edit_text(
            "❌ Sotuvchi topilmadi!",
            reply_markup=InlineKeyboardMarkup(get_back_button())
        )
        return

    # Context'ga sotuvchi ID ni saqlash
    context.user_data['waiting_group_id'] = seller_id

    keyboard = [
        [InlineKeyboardButton("✏️ Tahrirlash", callback_data=f"edit_seller|{seller_id}")],
        [InlineKeyboardButton("◀️ Ortga", callback_data="menu_sellers")]
    ]

    current_group = f"\n\n📍 Hozirgi guruh: <code>{seller.group_chat_id}</code>" if seller.group_chat_id else ""

    await query.message.edit_text(
        f"🔗 <b>Guruh ulash</b>\n\n"
        f"👤 <b>Sotuvchi:</b> {seller.full_name}\n"
        f"📞 <b>Telefon:</b> {seller.phone}"
        f"{current_group}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📝 <b>Guruh ID ni yuboring</b>\n\n"
        f"💡 Guruh ID olish uchun:\n"
        f"1. Botni guruhga qo'shing\n"
        f"2. Guruhda /get_chat_id yozing\n"
        f"3. Ko'rsatilgan ID ni shu yerga yuboring\n\n"
        f"<i>Masalan: -1001234567890</i>",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def show_edit_seller_menu(query, seller_id):
    """Sotuvchini tahrirlash menyusi"""
    from .models import Seller

    seller = Seller.get(id=seller_id)
    if not seller:
        await query.answer("Sotuvchi topilmadi!", show_alert=True)
        return

    keyboard = [
        [InlineKeyboardButton("📞 Telefon raqamni o'zgartirish", callback_data=f"edit_phone|{seller_id}")]
    ]

    # Guruh ulangan bo'lsa, o'chirish tugmasini qo'shish
    if seller.group_chat_id:
        keyboard.append([InlineKeyboardButton("🗑 Guruhni o'chirish", callback_data=f"remove_group|{seller_id}")])

    keyboard.append([InlineKeyboardButton("◀️ Ortga", callback_data=f"setgroup_{seller_id}")])

    # Guruh ma'lumotlari
    if seller.group_chat_id:
        group_name = seller.group_title if hasattr(seller, 'group_title') and seller.group_title else "Guruh"
        if hasattr(seller, 'group_invite_link') and seller.group_invite_link:
            group_info = f"👥 <b>Guruh:</b> <a href=\"{seller.group_invite_link}\">{group_name}</a>\n"
        else:
            group_info = f"👥 <b>Guruh:</b> {group_name} (ID: {seller.group_chat_id})\n"
    else:
        group_info = "👥 <b>Guruh:</b> <i>Ulanmagan</i>\n"

    await query.message.edit_text(
        f"✏️ <b>Sotuvchini tahrirlash</b>\n\n"
        f"👤 <b>Nomi:</b> {seller.full_name}\n"
        f"📞 <b>Telefon:</b> {seller.phone}\n"
        f"📍 <b>Manzil:</b> {seller.address or 'Kiritilmagan'}\n"
        f"{group_info}\n"
        f"Quyidagi parametrlarni o'zgartirishingiz mumkin:",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True
    )


async def ask_new_phone(query, seller_id, context):
    """Yangi telefon raqamini so'rash"""
    from .models import Seller

    seller = Seller.get(id=seller_id)
    if not seller:
        await query.answer("Sotuvchi topilmadi!", show_alert=True)
        return

    # Context'ga saqlash
    context.user_data['waiting_new_phone'] = seller_id

    keyboard = [
        [InlineKeyboardButton("❌ Bekor qilish", callback_data=f"cancel_edit|{seller_id}")]
    ]

    await query.message.edit_text(
        f"📞 <b>Telefon raqamni o'zgartirish</b>\n\n"
        f"👤 <b>Sotuvchi:</b> {seller.full_name}\n"
        f"📞 <b>Hozirgi raqam:</b> {seller.phone}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Yangi telefon raqamini yuboring:\n\n"
        f"<i>Masalan: +998901234567</i>",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def accept_order(order_id, query):
    from .models import Order, Staff, Seller

    order = Order.get(external_id=order_id)

    if not order:
        await query.answer("Buyurtma topilmadi!", show_alert=True)
        return

    # Faqat menejer qabul qila oladi
    user_id = str(query.from_user.id)
    seller = Seller.get(id=order.seller_id) if order.seller_id else None

    logger.info(f"Accept order: user_id={user_id}, order_id={order_id}, seller_id={order.seller_id}")

    is_manager = False

    if seller:
        logger.info(f"Seller: {seller.full_name}, owner_id={seller.telegram_user_id}")

        # Biznes egasi bo'lsa - menejer hisoblanadi
        if seller.telegram_user_id == user_id:
            is_manager = True
            logger.info(f"User is seller owner")

        # Yoki staff jadvalida menejer sifatida ro'yxatdan o'tgan
        if not is_manager:
            # 1. telegram_user_id bo'yicha tekshirish
            staff = Staff.get(seller_id=seller.id, telegram_user_id=user_id, is_active=True)
            if staff and staff.role == 'manager':
                is_manager = True
                logger.info(f"User is manager by telegram_user_id")

            # 2. staff_id bo'yicha tekshirish (xodim qo'shilganda telegram ID staff_id sifatida kiritilgan bo'lishi mumkin)
            if not is_manager:
                staff = Staff.get(seller_id=seller.id, staff_id=user_id, is_active=True)
                if staff and staff.role == 'manager':
                    is_manager = True
                    logger.info(f"User is manager by staff_id")
                    # telegram_user_id ni yangilash
                    staff.telegram_user_id = user_id
                    staff.save()

        if not is_manager:
            logger.info(f"User {user_id} is NOT a manager")
    else:
        logger.warning(f"Seller not found for order {order_id}")

    if not is_manager:
        await query.answer("⛔ Faqat biznes egasi yoki menejerlar buyurtmani qabul qila oladi!", show_alert=True)
        return

    order.status = 'accepted'
    order.save()

    # AmoCRM da ham statusni yangilash
    if hasattr(order, 'amocrm_lead_id') and order.amocrm_lead_id:
        try:
            from .services.amocrm import AmoCRMService
            amocrm = AmoCRMService()
            await amocrm.update_lead_status(int(order.amocrm_lead_id), 'accepted')
        except Exception as e:
            logger.error(f"AmoCRM status update error: {e}")

    current_time = datetime.now().strftime('%H:%M %d.%m.%Y')

    # Manzilni olish
    delivery_address = getattr(order, 'delivery_address', '') or ''
    delivery_type = getattr(order, 'delivery_type', 'delivery')

    # Buyurtma qabul qilindi - endi "Tayyor" tugmasini ko'rsatish
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🍽 Tayyor", callback_data=f"ready_{order_id}")]
    ])

    new_text = query.message.text + (
        f"\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ <b>QABUL QILINDI</b>\n\n"
        f"👤 Operator: {query.from_user.full_name}\n"
        f"🕐 Vaqt: {current_time}\n"
    )

    # Manzilni ko'rsatish
    if delivery_type == 'pickup':
        new_text += f"\n🏪 <b>Turi:</b> Olib ketish"
    else:
        new_text += f"\n🚚 <b>Turi:</b> Yetkazib berish"
        if delivery_address:
            new_text += f"\n📍 <b>Manzil:</b> {delivery_address}"

    new_text += f"\n\n<i>Buyurtma tayyor bo'lganda \"Tayyor\" tugmasini bosing</i>"

    await query.edit_message_text(
        text=new_text,
        reply_markup=keyboard,
        parse_mode='HTML'
    )

    logger.info(f"Order {order_id} accepted by {query.from_user.id}")


async def mark_order_ready(order_id, query):
    """Buyurtma tayyor - keyingi bosqichga o'tish"""
    from .models import Order, Seller

    order = Order.get(external_id=order_id)

    if not order:
        await query.answer("Buyurtma topilmadi!", show_alert=True)
        return

    # Buyurtma statusini yangilash
    order.status = 'ready'
    order.save()

    # AmoCRM da ham statusni yangilash
    if hasattr(order, 'amocrm_lead_id') and order.amocrm_lead_id:
        try:
            from .services.amocrm import AmoCRMService
            amocrm = AmoCRMService()
            await amocrm.update_lead_status(int(order.amocrm_lead_id), 'ready')
        except Exception as e:
            logger.error(f"AmoCRM status update error: {e}")

    current_time = datetime.now().strftime('%H:%M %d.%m.%Y')

    # Mijoz ma'lumotlarini olish
    customer_name = order.customer_name or "Noma'lum"
    customer_phone = order.customer_phone or "Ko'rsatilmagan"

    # Manzilni olish (agar saqlangan bo'lsa)
    delivery_address = ""
    if hasattr(order, 'delivery_address'):
        delivery_address = order.delivery_address or ""

    # delivery_type ni olish
    delivery_type = getattr(order, 'delivery_type', 'delivery')

    # Yangi xabar - mijoz ma'lumotlari bilan
    new_text = query.message.text + (
        f"\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🍽 <b>TAYYOR</b>\n\n"
        f"👤 <b>Mijoz:</b> {customer_name}\n"
        f"📞 <b>Telefon:</b> <code>{customer_phone}</code>\n"
    )

    if delivery_address:
        new_text += f"📍 <b>Manzil:</b> {delivery_address}\n"

    new_text += f"\n🕐 Tayyor vaqti: {current_time}"

    # Keyingi tugma - delivery_type ga qarab
    if delivery_type == 'pickup':
        # Olib ketish - to'g'ridan-to'g'ri YAKUNLANDI ga o'tish
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Yakunlandi", callback_data=f"completed_{order_id}")]
        ])
        new_text += "\n\n<i>Mijoz olib ketganda \"Yakunlandi\" tugmasini bosing</i>"
    else:
        # Yetkazib berish - avval YETKAZILMOQDA ga o'tish
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚚 Yetkazilmoqda", callback_data=f"delivering_{order_id}")]
        ])
        new_text += "\n\n<i>Kuryer jo'naganda \"Yetkazilmoqda\" tugmasini bosing</i>"

    await query.edit_message_text(
        text=new_text,
        reply_markup=keyboard,
        parse_mode='HTML'
    )

    logger.info(f"Order {order_id} marked as ready by {query.from_user.id}")


async def mark_order_delivering(order_id, query):
    """Buyurtma yetkazilmoqda"""
    from .models import Order

    order = Order.get(external_id=order_id)

    if not order:
        await query.answer("Buyurtma topilmadi!", show_alert=True)
        return

    # Buyurtma statusini yangilash
    order.status = 'delivering'
    order.save()

    # AmoCRM da ham statusni yangilash
    if hasattr(order, 'amocrm_lead_id') and order.amocrm_lead_id:
        try:
            from .services.amocrm import AmoCRMService
            amocrm = AmoCRMService()
            await amocrm.update_lead_status(int(order.amocrm_lead_id), 'delivering')
        except Exception as e:
            logger.error(f"AmoCRM status update error: {e}")

    current_time = datetime.now().strftime('%H:%M %d.%m.%Y')

    # Keyingi tugma - YAKUNLANDI
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yakunlandi", callback_data=f"completed_{order_id}")]
    ])

    new_text = query.message.text + (
        f"\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🚚 <b>YETKAZILMOQDA</b>\n\n"
        f"🕐 Vaqt: {current_time}\n\n"
        f"<i>Buyurtma yetkazilganda \"Yakunlandi\" tugmasini bosing</i>"
    )

    await query.edit_message_text(
        text=new_text,
        reply_markup=keyboard,
        parse_mode='HTML'
    )

    logger.info(f"Order {order_id} marked as delivering by {query.from_user.id}")


async def mark_order_completed(order_id, query):
    """Buyurtma yakunlandi"""
    from .models import Order

    order = Order.get(external_id=order_id)

    if not order:
        await query.answer("Buyurtma topilmadi!", show_alert=True)
        return

    # Buyurtma statusini yangilash
    order.status = 'completed'
    order.save()

    # AmoCRM da ham statusni yangilash
    if hasattr(order, 'amocrm_lead_id') and order.amocrm_lead_id:
        try:
            from .services.amocrm import AmoCRMService
            amocrm = AmoCRMService()
            await amocrm.update_lead_status(int(order.amocrm_lead_id), 'completed')
        except Exception as e:
            logger.error(f"AmoCRM status update error: {e}")

    current_time = datetime.now().strftime('%H:%M %d.%m.%Y')

    new_text = query.message.text + (
        f"\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ <b>YAKUNLANDI</b>\n\n"
        f"🕐 Vaqt: {current_time}"
    )

    await query.edit_message_text(
        text=new_text,
        reply_markup=None,
        parse_mode='HTML'
    )

    logger.info(f"Order {order_id} completed by {query.from_user.id}")


async def reject_order(order_id, query):
    from .models import Order, Staff, Seller

    order = Order.get(external_id=order_id)

    if not order:
        await query.answer("Buyurtma topilmadi!", show_alert=True)
        return

    # Faqat menejer rad eta oladi
    user_id = str(query.from_user.id)
    seller = Seller.get(id=order.seller_id) if order.seller_id else None

    is_manager = False

    if seller:
        # Biznes egasi bo'lsa - menejer hisoblanadi
        if seller.telegram_user_id == user_id:
            is_manager = True

        # Yoki staff jadvalida menejer sifatida ro'yxatdan o'tgan
        if not is_manager:
            # 1. telegram_user_id bo'yicha tekshirish
            staff = Staff.get(seller_id=seller.id, telegram_user_id=user_id, is_active=True)
            if staff and staff.role == 'manager':
                is_manager = True

            # 2. staff_id bo'yicha tekshirish (xodim qo'shilganda telegram ID staff_id sifatida kiritilgan bo'lishi mumkin)
            if not is_manager:
                staff = Staff.get(seller_id=seller.id, staff_id=user_id, is_active=True)
                if staff and staff.role == 'manager':
                    is_manager = True
                    # telegram_user_id ni yangilash (keyingi safar tezroq topilishi uchun)
                    staff.telegram_user_id = user_id
                    staff.save()

    if not is_manager:
        await query.answer("⛔ Faqat biznes egasi yoki menejerlar buyurtmani rad eta oladi!", show_alert=True)
        return

    order.status = 'cancelled'
    order.save()

    # AmoCRM da ham statusni yangilash - BEKOR QILINDI
    if hasattr(order, 'amocrm_lead_id') and order.amocrm_lead_id:
        try:
            from .services.amocrm import AmoCRMService
            amocrm = AmoCRMService()
            await amocrm.update_lead_status(int(order.amocrm_lead_id), 'cancelled')
        except Exception as e:
            logger.error(f"AmoCRM status update error: {e}")

    current_time = datetime.now().strftime('%H:%M %d.%m.%Y')

    new_text = query.message.text + (
        f"\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"❌ <b>BEKOR QILINDI</b>\n\n"
        f"👤 Operator: {query.from_user.full_name}\n"
        f"🕐 Vaqt: {current_time}"
    )

    await query.edit_message_text(
        text=new_text,
        reply_markup=None,
        parse_mode='HTML'
    )

    logger.info(f"Order {order_id} rejected by {query.from_user.id}")


# ==========================================
# Seller Dashboard Functions
# ==========================================

async def show_seller_dashboard(query, seller_id):
    """Sotuvchi dashboardini ko'rsatish"""
    from .models import Seller

    seller = Seller.get(id=seller_id)
    if not seller:
        await query.answer("Sotuvchi topilmadi!", show_alert=True)
        return

    keyboard = [
        [
            InlineKeyboardButton("📊 Statistika", callback_data=f"seller_stats_{seller_id}"),
            InlineKeyboardButton("👥 Xodimlar", callback_data=f"seller_staff_{seller_id}")
        ]
    ]

    await query.message.edit_text(
        f"👋 <b>Dashboard</b>\n\n"
        f"🏪 <b>Biznes:</b> {seller.full_name}\n"
        f"📞 <b>Telefon:</b> {seller.phone}\n"
        f"👥 <b>Guruh:</b> {seller.group_title or 'Ulangan'}\n\n"
        f"Quyidagi tugmalardan foydalaning:",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def show_seller_stats(query, seller_id):
    """Sotuvchi statistikasini ko'rsatish"""
    from .models import Seller, Order

    seller = Seller.get(id=seller_id)
    if not seller:
        await query.answer("Sotuvchi topilmadi!", show_alert=True)
        return

    # Faqat shu sotuvchining buyurtmalarini olish
    all_orders = Order.load_all()
    seller_orders = [o for o in all_orders if o.get('seller_id') == seller_id]

    # Vaqt filtrlash
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    def filter_orders_by_date(orders, start_date):
        filtered = []
        for o in orders:
            created = o.get('created_at', '')
            if created:
                try:
                    order_date = datetime.fromisoformat(created.replace('Z', '+00:00'))
                    if order_date.replace(tzinfo=None) >= start_date:
                        filtered.append(o)
                except:
                    pass
        return filtered

    daily_orders = filter_orders_by_date(seller_orders, today_start)
    monthly_orders = filter_orders_by_date(seller_orders, month_start)

    # Kunlik statistika
    daily_total = len(daily_orders)
    daily_accepted = len([o for o in daily_orders if o.get('status') == 'accepted'])
    daily_rejected = len([o for o in daily_orders if o.get('status') == 'rejected'])
    daily_amount = sum(o.get('total_amount', 0) for o in daily_orders if o.get('status') == 'accepted')

    # Oylik statistika
    monthly_total = len(monthly_orders)
    monthly_accepted = len([o for o in monthly_orders if o.get('status') == 'accepted'])
    monthly_rejected = len([o for o in monthly_orders if o.get('status') == 'rejected'])
    monthly_amount = sum(o.get('total_amount', 0) for o in monthly_orders if o.get('status') == 'accepted')

    # Umumiy statistika
    total_orders = len(seller_orders)
    total_accepted = len([o for o in seller_orders if o.get('status') == 'accepted'])
    total_amount = sum(o.get('total_amount', 0) for o in seller_orders if o.get('status') == 'accepted')

    keyboard = [
        [
            InlineKeyboardButton("👥 Xodimlar", callback_data=f"seller_staff_{seller_id}"),
            InlineKeyboardButton("🔄 Yangilash", callback_data=f"seller_stats_{seller_id}")
        ],
        [InlineKeyboardButton("◀️ Ortga", callback_data=f"seller_back_{seller_id}")]
    ]

    stats_message = (
        f"📊 <b>Statistika - {seller.full_name}</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📅 <b>Bugungi:</b>\n"
        f"    Buyurtmalar: {daily_total} ta\n"
        f"    ✅ Qabul: {daily_accepted} ta\n"
        f"    ❌ Rad: {daily_rejected} ta\n"
        f"    💰 Summa: {daily_amount:,.0f} so'm\n\n".replace(",", " ") +
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📆 <b>Shu oy:</b>\n"
        f"    Buyurtmalar: {monthly_total} ta\n"
        f"    ✅ Qabul: {monthly_accepted} ta\n"
        f"    ❌ Rad: {monthly_rejected} ta\n"
        f"    💰 Summa: {monthly_amount:,.0f} so'm\n\n".replace(",", " ") +
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📊 <b>Umumiy:</b>\n"
        f"    Jami buyurtmalar: {total_orders} ta\n"
        f"    ✅ Qabul qilingan: {total_accepted} ta\n"
        f"    💰 Jami summa: {total_amount:,.0f} so'm".replace(",", " ")
    )

    try:
        await query.message.edit_text(
            stats_message,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception:
        await query.message.reply_text(
            stats_message,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


async def show_seller_staff(query, seller_id):
    """Xodimlar ro'yxatini ko'rsatish"""
    from .models import Seller, Staff

    seller = Seller.get(id=seller_id)
    if not seller:
        await query.answer("Sotuvchi topilmadi!", show_alert=True)
        return

    # Xodimlarni yuklash
    staff_members = Staff.filter(seller_id=seller_id, is_active=True)

    keyboard = []

    if staff_members:
        message = f"👥 <b>Xodimlar - {seller.full_name}</b>\n\n"

        for i, staff in enumerate(staff_members, 1):
            role_emoji = "👨‍💼" if staff.role == "manager" else "👨‍🍳" if staff.role == "cook" else "🚚" if staff.role == "courier" else "👤"
            role_name = "Menejer" if staff.role == "manager" else "Oshpaz" if staff.role == "cook" else "Yetkazuvchi" if staff.role == "courier" else "Xodim"
            staff_id_display = staff.staff_id if hasattr(staff, 'staff_id') and staff.staff_id else f"#{i}"

            # Telegram ID orqali link yaratish
            tg_id = staff.telegram_user_id or staff.staff_id
            if tg_id:
                message += f"{role_emoji} <b><a href=\"tg://user?id={tg_id}\">{staff_id_display}. {staff.full_name}</a></b>\n"
            else:
                message += f"{role_emoji} <b>{staff_id_display}. {staff.full_name}</b>\n"

            phone_display = staff.phone or "Raqam yo'q"
            message += f"    📱 {phone_display}\n"
            message += f"    🏷 {role_name}\n\n"

            # Xodimni o'chirish tugmasi
            keyboard.append([InlineKeyboardButton(f"🗑 {staff.full_name} ni o'chirish", callback_data=f"rmstaff_{staff.id}")])

        message += f"━━━━━━━━━━━━━━━━━━━━\n"
        message += f"Jami: {len(staff_members)} ta xodim"
    else:
        message = f"👥 <b>Xodimlar - {seller.full_name}</b>\n\n"
        message += "📭 Hozircha xodimlar yo'q.\n\n"
        message += "Yangi xodim qo'shish uchun quyidagi tugmani bosing."

    keyboard.append([InlineKeyboardButton("➕ Xodim qo'shish", callback_data=f"add_staff_{seller_id}")])
    keyboard.append([
        InlineKeyboardButton("📊 Statistika", callback_data=f"seller_stats_{seller_id}"),
        InlineKeyboardButton("◀️ Ortga", callback_data=f"seller_back_{seller_id}")
    ])

    try:
        await query.message.edit_text(
            message,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        # Agar edit ishlamasa, yangi xabar yuborish
        await query.message.reply_text(
            message,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


async def ask_staff_info(query, seller_id, context):
    """Yangi xodim ma'lumotlarini so'rash - avval ID"""
    from .models import Seller

    seller = Seller.get(id=seller_id)
    if not seller:
        await query.answer("Sotuvchi topilmadi!", show_alert=True)
        return

    # Context'ga saqlash
    context.user_data['adding_staff_seller'] = seller_id
    context.user_data['adding_staff_step'] = 'staff_id'

    keyboard = [
        [InlineKeyboardButton("❌ Bekor qilish", callback_data=f"seller_staff_{seller_id}")]
    ]

    await query.message.edit_text(
        f"➕ <b>Yangi xodim qo'shish</b>\n\n"
        f"🏪 <b>Biznes:</b> {seller.full_name}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 Xodimning <b>ID raqamini</b> yuboring:\n\n"
        f"<i>Masalan: 001 yoki 1</i>",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def remove_staff_member(query, seller_id, staff_id):
    """Xodimni o'chirish"""
    from .models import Staff

    staff = Staff.get(id=staff_id)
    if not staff:
        await query.answer("Xodim topilmadi!", show_alert=True)
        return

    staff_name = staff.full_name
    staff.is_active = False
    staff.save()

    await query.answer(f"✅ {staff_name} o'chirildi", show_alert=True)
    await show_seller_staff(query, seller_id)


async def remove_staff_member_by_id(query, staff_id):
    """Xodimni o'chirish (faqat staff_id bilan)"""
    from .models import Staff

    staff = Staff.get(id=staff_id)
    if not staff:
        await query.answer("Xodim topilmadi!", show_alert=True)
        return

    seller_id = staff.seller_id
    staff_name = staff.full_name
    staff.is_active = False
    staff.save()

    await query.answer(f"✅ {staff_name} o'chirildi", show_alert=True)
    await show_seller_staff(query, seller_id)


async def confirm_remove_staff(query, staff_id):
    """Xodimni o'chirishni tasdiqlash"""
    from .models import Staff, Seller

    staff = Staff.get(id=staff_id)
    if not staff:
        await query.answer("Xodim topilmadi!", show_alert=True)
        return

    seller = Seller.get(id=staff.seller_id)
    seller_name = seller.full_name if seller else "Noma'lum"

    role_name = "Menejer" if staff.role == "manager" else "Oshpaz" if staff.role == "cook" else "Yetkazuvchi" if staff.role == "courier" else "Xodim"

    keyboard = [
        [
            InlineKeyboardButton("✅ Ha, o'chirish", callback_data=f"delstaff_{staff_id}"),
            InlineKeyboardButton("❌ Yo'q", callback_data=f"seller_staff_{staff.seller_id}")
        ]
    ]

    staff_id_display = staff.staff_id if hasattr(staff, 'staff_id') and staff.staff_id else '-'

    await query.message.edit_text(
        f"⚠️ <b>Xodimni o'chirishni tasdiqlang</b>\n\n"
        f"🆔 <b>ID:</b> {staff_id_display}\n"
        f"👤 <b>Ism:</b> {staff.full_name}\n"
        f"📱 <b>Telefon:</b> {staff.phone or 'Kiritilmagan'}\n"
        f"🏷 <b>Lavozim:</b> {role_name}\n"
        f"🏪 <b>Biznes:</b> {seller_name}\n\n"
        f"Rostdan ham bu xodimni o'chirmoqchimisiz?",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def show_seller_settings(query, seller_id):
    """Sotuvchi sozlamalarini ko'rsatish"""
    from .models import Seller, Staff

    seller = Seller.get(id=seller_id)
    if not seller:
        await query.answer("Sotuvchi topilmadi!", show_alert=True)
        return

    # Xodimlar soni
    staff_count = len(Staff.filter(seller_id=seller_id, is_active=True))

    keyboard = [
        [InlineKeyboardButton("👥 Xodimlar boshqaruvi", callback_data=f"seller_staff_{seller_id}")],
        [InlineKeyboardButton("📊 Statistika", callback_data=f"seller_stats_{seller_id}")],
        [InlineKeyboardButton("◀️ Ortga", callback_data=f"seller_back_{seller_id}")]
    ]

    await query.message.edit_text(
        f"⚙️ <b>Sozlamalar - {seller.full_name}</b>\n\n"
        f"🏪 <b>Biznes:</b> {seller.full_name}\n"
        f"📞 <b>Telefon:</b> {seller.phone}\n"
        f"👥 <b>Guruh:</b> {seller.group_title or 'Ulangan'}\n"
        f"👨‍💼 <b>Xodimlar:</b> {staff_count} ta\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Quyidagi tugmalardan foydalaning:",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ==========================================
# ADMIN PANEL - STATISTIKA
# ==========================================

async def show_admin_stats(query, period="daily"):
    """Admin statistikasini ko'rsatish (kunlik/haftalik/oylik/yillik)"""
    from .models import Seller, Order

    sellers = Seller.filter(is_active=True)
    all_orders = Order.load_all()

    # Vaqt filtrlash
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())  # Dushanba
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    year_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)

    def filter_orders_by_date(orders, start_date):
        filtered = []
        for o in orders:
            created = o.get('created_at', '')
            if created:
                try:
                    order_date = datetime.fromisoformat(created.replace('Z', '+00:00'))
                    if order_date.replace(tzinfo=None) >= start_date:
                        filtered.append(o)
                except:
                    pass
        return filtered

    # Davr bo'yicha filtrlaymiz
    if period == "daily":
        filtered_orders = filter_orders_by_date(all_orders, today_start)
        period_title = "📅 Bugungi"
    elif period == "weekly":
        filtered_orders = filter_orders_by_date(all_orders, week_start)
        period_title = "📆 Haftalik"
    elif period == "monthly":
        filtered_orders = filter_orders_by_date(all_orders, month_start)
        period_title = "📆 Oylik"
    elif period == "yearly":
        filtered_orders = filter_orders_by_date(all_orders, year_start)
        period_title = "📊 Yillik"
    else:
        filtered_orders = all_orders
        period_title = "📊 Umumiy"

    total_orders = len(filtered_orders)
    accepted_orders = len([o for o in filtered_orders if o.get('status') in ['accepted', 'ready', 'delivering', 'completed']])
    rejected_orders = len([o for o in filtered_orders if o.get('status') in ['rejected', 'cancelled']])
    pending_orders = len([o for o in filtered_orders if o.get('status') == 'new'])
    expired_orders = len([o for o in filtered_orders if o.get('status') == 'expired'])

    # Jami savdo summasi (faqat qabul qilingan/yakunlangan buyurtmalar)
    completed_statuses = ['accepted', 'ready', 'delivering', 'completed']
    total_amount = sum(o.get('total_amount', 0) for o in filtered_orders if o.get('status') in completed_statuses)

    # Foizlar
    accepted_percent = (accepted_orders / total_orders * 100) if total_orders > 0 else 0
    rejected_percent = (rejected_orders / total_orders * 100) if total_orders > 0 else 0

    # Davr tugmalari
    keyboard = [
        [
            InlineKeyboardButton("📅 Kunlik" + (" ✓" if period == "daily" else ""), callback_data="stats_daily"),
            InlineKeyboardButton("📆 Haftalik" + (" ✓" if period == "weekly" else ""), callback_data="stats_weekly"),
        ],
        [
            InlineKeyboardButton("📆 Oylik" + (" ✓" if period == "monthly" else ""), callback_data="stats_monthly"),
            InlineKeyboardButton("📊 Yillik" + (" ✓" if period == "yearly" else ""), callback_data="stats_yearly"),
        ],
        [InlineKeyboardButton("◀️ Ortga", callback_data="back_admin")]
    ]

    await query.message.edit_text(
        f"{period_title} <b>STATISTIKA</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 <b>Buyurtmalar:</b> {total_orders} ta\n"
        f"✅ Qabul qilingan: {accepted_orders} ta ({accepted_percent:.1f}%)\n"
        f"❌ Rad etilgan: {rejected_orders} ta ({rejected_percent:.1f}%)\n"
        f"⏳ Kutilmoqda: {pending_orders} ta\n"
        f"⌛ Muddati o'tgan: {expired_orders} ta\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>Jami savdo:</b> {total_amount:,.0f} so'm".replace(",", " "),
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ==========================================
# ADMIN PANEL - BUYURTMA QIDIRISH
# ==========================================

async def show_order_search(query, context):
    """Buyurtma qidirish interfeysini ko'rsatish"""
    context.user_data['waiting_order_search'] = True

    keyboard = [[InlineKeyboardButton("◀️ Ortga", callback_data="back_admin")]]

    await query.message.edit_text(
        "🔍 <b>BUYURTMA QIDIRISH</b>\n\n"
        "Buyurtma ID raqamini yuboring:\n\n"
        "<i>Masalan: 1234 yoki TEST-1705728000</i>",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def search_order_by_id(order_id: str, query_or_update, context):
    """Buyurtmani ID bo'yicha qidirish va natijani ko'rsatish"""
    from .models import Order, Seller

    # Qidirish
    order = Order.get(external_id=order_id)

    keyboard = [
        [InlineKeyboardButton("🔍 Yana qidirish", callback_data="admin_search")],
        [InlineKeyboardButton("◀️ Ortga", callback_data="back_admin")]
    ]

    if not order:
        message = (
            f"❌ <b>BUYURTMA TOPILMADI</b>\n\n"
            f"<code>#{order_id}</code> raqamli buyurtma topilmadi."
        )
    else:
        # Biznes ma'lumotlari
        seller = Seller.get(id=order.seller_id) if order.seller_id else None
        business_name = seller.full_name if seller else "Noma'lum"

        # Status emoji va nomi
        status_map = {
            'new': ('⏳', 'Kutilmoqda'),
            'accepted': ('✅', 'Qabul qilindi'),
            'ready': ('🍽', 'Tayyor'),
            'delivering': ('🚚', 'Yetkazilmoqda'),
            'completed': ('✅', 'Yakunlandi'),
            'rejected': ('❌', 'Rad etildi'),
            'cancelled': ('❌', 'Bekor qilindi'),
            'expired': ('⌛', 'Muddati o\'tdi')
        }
        status_emoji, status_name = status_map.get(order.status, ('❓', order.status))

        # Vaqt ma'lumotlari
        created_at = order.created_at or ''
        notified_at = order.notified_at or ''
        updated_at = order.updated_at or ''

        def format_time(iso_str):
            if not iso_str:
                return '-'
            try:
                dt = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
                return dt.strftime('%H:%M:%S %d.%m.%Y')
            except:
                return iso_str

        message = (
            f"🔍 <b>BUYURTMA TOPILDI</b>\n\n"
            f"📦 <b>Buyurtma:</b> #{order.external_id}\n"
            f"🏪 <b>Biznes:</b> {business_name}\n"
            f"📊 <b>Status:</b> {status_emoji} {status_name}\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"⏱ <b>VAQT JADVALI:</b>\n\n"
            f"📥 Kelgan: {format_time(notified_at)}\n"
        )

        # Agar completed bo'lsa, vaqtlarni hisoblash
        if order.status in ['completed', 'delivering', 'ready', 'accepted']:
            message += f"📊 Status: {status_name}\n"

        message += (
            f"\n━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Mijoz:</b> {order.customer_name or 'Noma\\'lum'}\n"
            f"📞 <b>Telefon:</b> {order.customer_phone or 'Ko\\'rsatilmagan'}\n"
            f"💰 <b>Summa:</b> {order.total_amount:,} so'm".replace(",", " ")
        )

    # Xabarni yuborish
    if hasattr(query_or_update, 'message') and hasattr(query_or_update.message, 'edit_text'):
        await query_or_update.message.edit_text(message, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
    elif hasattr(query_or_update, 'reply_text'):
        await query_or_update.reply_text(message, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await query_or_update.message.reply_text(message, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


# ==========================================
# ADMIN PANEL - TEST BUYURTMA (PAGINATION)
# ==========================================

async def show_test_order_businesses(query, page=0):
    """Test buyurtma uchun bizneslar ro'yxati (pagination bilan)"""
    from .models import Seller

    sellers = Seller.filter(is_active=True)
    total_count = len(sellers)

    if total_count == 0:
        keyboard = [[InlineKeyboardButton("◀️ Ortga", callback_data="back_admin")]]
        await query.message.edit_text(
            "🧪 <b>TEST BUYURTMA</b>\n\n"
            "📭 Hozircha bizneslar yo'q.",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # Pagination
    total_pages = (total_count + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    start_idx = page * ITEMS_PER_PAGE
    end_idx = min(start_idx + ITEMS_PER_PAGE, total_count)
    page_sellers = sellers[start_idx:end_idx]

    message = f"🧪 <b>TEST BUYURTMA</b>\n\n"
    message += f"Qaysi biznesga test buyurtma yubormoqchisiz?\n\n"
    if total_pages > 1:
        message += f"📄 Sahifa: {page + 1}/{total_pages}\n\n"

    keyboard = []
    for i, seller in enumerate(page_sellers, start_idx + 1):
        status = "✅" if seller.group_chat_id else "⚠️"
        btn_text = f"{status} {i}. {seller.full_name}"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"test_send_{seller.id}")])

    # Pagination tugmalari
    if total_pages > 1:
        pagination_btns = []
        if page > 0:
            pagination_btns.append(InlineKeyboardButton("⬅️ Oldingi", callback_data=f"test_page_{page - 1}"))
        if page < total_pages - 1:
            pagination_btns.append(InlineKeyboardButton("Keyingi ➡️", callback_data=f"test_page_{page + 1}"))
        if pagination_btns:
            keyboard.append(pagination_btns)

    keyboard.append([InlineKeyboardButton("◀️ Ortga", callback_data="back_admin")])

    await query.message.edit_text(message, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


# ==========================================
# ADMIN PANEL - XABARNOMA SHABLON TIZIMI
# ==========================================

async def show_notification_templates(query):
    """Xabarnoma shablonlarini ko'rsatish"""
    from .models import NotificationTemplate

    templates = NotificationTemplate.get_all_sorted()

    message = "📢 <b>XABARNOMA YUBORISH</b>\n\n"

    keyboard = []

    if templates:
        message += "Shablon xabarlar:\n\n"
        for template in templates:
            # Sarlavhani 30 belgigacha qisqartirish
            title = template.title[:30] + "..." if len(template.title) > 30 else template.title
            message += f"{template.order_num}️⃣ {title}\n"
            keyboard.append([InlineKeyboardButton(
                f"{template.order_num}️⃣ {title}",
                callback_data=f"notify_view_{template.id}"
            )])
    else:
        message += "📭 Shablon xabarlar yo'q.\n\n"
        message += "Yangi shablon qo'shish uchun quyidagi tugmani bosing."

    keyboard.append([InlineKeyboardButton("➕ Yangi shablon qo'shish", callback_data="notify_add")])
    keyboard.append([InlineKeyboardButton("◀️ Ortga", callback_data="back_admin")])

    await query.message.edit_text(message, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def start_add_notification_template(query, context):
    """Yangi shablon qo'shishni boshlash"""
    context.user_data['adding_template'] = True
    context.user_data['template_step'] = 'title'

    keyboard = [[InlineKeyboardButton("❌ Bekor qilish", callback_data="notify_cancel")]]

    await query.message.edit_text(
        "📝 <b>YANGI SHABLON QO'SHISH</b>\n\n"
        "1️⃣ Avval shablon <b>sarlavhasini</b> yuboring:\n\n"
        "<i>Masalan: Texnik ishlar haqida</i>",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def show_notification_template(query, template_id):
    """Shablonni to'liq ko'rsatish"""
    from .models import NotificationTemplate

    template = NotificationTemplate.get(id=template_id)

    if not template:
        await query.answer("Shablon topilmadi!", show_alert=True)
        await show_notification_templates(query)
        return

    message = (
        f"📄 <b>SHABLON #{template.order_num}</b>\n\n"
        f"📌 <b>Sarlavha:</b> {template.title}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"{template.content}\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )

    keyboard = [
        [InlineKeyboardButton("📤 Yuborish", callback_data=f"notify_send_{template_id}")],
        [
            InlineKeyboardButton("✏️ Tahrirlash", callback_data=f"notify_edit_{template_id}"),
            InlineKeyboardButton("🗑 O'chirish", callback_data=f"notify_delete_{template_id}")
        ],
        [InlineKeyboardButton("◀️ Ortga", callback_data="admin_notify")]
    ]

    await query.message.edit_text(message, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def start_edit_notification_template(query, template_id, context):
    """Shablonni tahrirlashni boshlash"""
    from .models import NotificationTemplate

    template = NotificationTemplate.get(id=template_id)
    if not template:
        await query.answer("Shablon topilmadi!", show_alert=True)
        return

    context.user_data['editing_template'] = template_id
    context.user_data['template_step'] = 'content'

    keyboard = [[InlineKeyboardButton("❌ Bekor qilish", callback_data=f"notify_view_{template_id}")]]

    await query.message.edit_text(
        f"✏️ <b>SHABLONNI TAHRIRLASH</b>\n\n"
        f"📌 <b>Sarlavha:</b> {template.title}\n\n"
        "Yangi xabar matnini yuboring:\n\n"
        "<i>(HTML formatida yozishingiz mumkin)</i>",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def delete_notification_template(query, template_id):
    """Shablonni o'chirish"""
    from .models import NotificationTemplate

    template = NotificationTemplate.get(id=template_id)
    if not template:
        await query.answer("Shablon topilmadi!", show_alert=True)
        return

    template.delete()
    await query.answer(f"✅ Shablon o'chirildi!", show_alert=True)
    await show_notification_templates(query)


async def show_notification_recipients(query, template_id, context):
    """Xabarnoma qabul qiluvchilarini tanlash"""
    from .models import Seller, NotificationTemplate

    template = NotificationTemplate.get(id=template_id)
    if not template:
        await query.answer("Shablon topilmadi!", show_alert=True)
        return

    context.user_data['sending_template'] = template_id
    context.user_data['selected_regions'] = []

    sellers = Seller.filter(is_active=True)

    # Viloyatlar bo'yicha guruhlash
    regions = load_regions()
    region_counts = {}
    for seller in sellers:
        if seller.region:
            region_counts[seller.region] = region_counts.get(seller.region, 0) + 1

    total_sellers = len(sellers)

    message = (
        f"📤 <b>XABARNOMA YUBORISH</b>\n\n"
        f"📄 Shablon: {template.title}\n\n"
        f"Kimga yubormoqchisiz?\n\n"
        f"Jami bizneslar: {total_sellers} ta"
    )

    keyboard = [
        [InlineKeyboardButton(f"📢 Barchaga ({total_sellers})", callback_data="notify_all")]
    ]

    # Viloyatlar
    for region in regions:
        count = region_counts.get(region['id'], 0)
        if count > 0:
            keyboard.append([InlineKeyboardButton(
                f"🏙 {region['name']} ({count})",
                callback_data=f"notify_region_{region['id']}"
            )])

    keyboard.append([InlineKeyboardButton("❌ Bekor qilish", callback_data="admin_notify")])

    await query.message.edit_text(message, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def select_all_recipients(query, context):
    """Barcha qabul qiluvchilarni tanlash"""
    context.user_data['selected_regions'] = ['all']
    await confirm_send_notification(query, context)


async def toggle_region_selection(query, region_id, context):
    """Viloyatni tanlash/o'chirish"""
    selected = context.user_data.get('selected_regions', [])

    if region_id in selected:
        selected.remove(region_id)
    else:
        selected.append(region_id)

    context.user_data['selected_regions'] = selected

    # Tanlangan viloyatlarni ko'rsatish
    from .models import Seller

    sellers = Seller.filter(is_active=True)

    if 'all' in selected:
        total_selected = len(sellers)
    else:
        total_selected = len([s for s in sellers if s.region in selected])

    regions = load_regions()
    region_names = []
    for rid in selected:
        for r in regions:
            if r['id'] == rid:
                region_names.append(r['name'])
                break

    message = f"📤 <b>XABARNOMA YUBORISH</b>\n\n"

    if region_names:
        message += "✅ <b>Tanlangan viloyatlar:</b>\n"
        for name in region_names:
            message += f"  • {name}\n"
        message += f"\n<b>Jami:</b> {total_selected} ta biznes"
    else:
        message += "Viloyatlarni tanlang:"

    keyboard = []

    # Tanlangan viloyatlarni ko'rsatish
    region_counts = {}
    for seller in sellers:
        if seller.region:
            region_counts[seller.region] = region_counts.get(seller.region, 0) + 1

    for region in regions:
        count = region_counts.get(region['id'], 0)
        if count > 0:
            is_selected = region['id'] in selected
            prefix = "✅ " if is_selected else "🏙 "
            keyboard.append([InlineKeyboardButton(
                f"{prefix}{region['name']} ({count})",
                callback_data=f"notify_region_{region['id']}"
            )])

    if selected:
        keyboard.append([InlineKeyboardButton("📤 Yuborish", callback_data="notify_confirm")])

    keyboard.append([InlineKeyboardButton("❌ Bekor qilish", callback_data="admin_notify")])

    await query.message.edit_text(message, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def confirm_send_notification(query, context):
    """Xabarnoma yuborishni tasdiqlash"""
    from .models import Seller, NotificationTemplate

    template_id = context.user_data.get('sending_template')
    selected = context.user_data.get('selected_regions', [])

    template = NotificationTemplate.get(id=template_id)
    if not template:
        await query.answer("Shablon topilmadi!", show_alert=True)
        return

    sellers = Seller.filter(is_active=True)

    if 'all' in selected:
        target_sellers = [s for s in sellers if s.group_chat_id]
    else:
        target_sellers = [s for s in sellers if s.region in selected and s.group_chat_id]

    count = len(target_sellers)

    message = (
        f"⚠️ <b>TASDIQLANG</b>\n\n"
        f"📄 Shablon: {template.title}\n\n"
        f"Xabarnoma <b>{count}</b> ta biznesga yuboriladi.\n\n"
        f"Davom etasizmi?"
    )

    keyboard = [
        [
            InlineKeyboardButton("✅ Ha, yuborish", callback_data="notify_do_send"),
            InlineKeyboardButton("❌ Yo'q", callback_data="admin_notify")
        ]
    ]

    await query.message.edit_text(message, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def do_send_notification(query, context):
    """Xabarnomani haqiqatdan yuborish"""
    from .models import Seller, NotificationTemplate
    from .core import get_bot

    template_id = context.user_data.get('sending_template')
    selected = context.user_data.get('selected_regions', [])

    template = NotificationTemplate.get(id=template_id)
    if not template:
        await query.answer("Shablon topilmadi!", show_alert=True)
        return

    sellers = Seller.filter(is_active=True)

    if 'all' in selected:
        target_sellers = [s for s in sellers if s.group_chat_id]
    else:
        target_sellers = [s for s in sellers if s.region in selected and s.group_chat_id]

    # Yuborish boshlanganligi haqida xabar
    await query.message.edit_text(
        f"⏳ <b>YUBORILMOQDA...</b>\n\n"
        f"📄 Shablon: {template.title}\n"
        f"📤 Jami: {len(target_sellers)} ta biznes",
        parse_mode='HTML'
    )

    bot = get_bot()
    success_count = 0
    error_count = 0
    errors = []

    for seller in target_sellers:
        try:
            await bot.send_message(
                chat_id=int(seller.group_chat_id),
                text=f"📢 <b>{template.title}</b>\n\n{template.content}",
                parse_mode='HTML'
            )
            success_count += 1
        except Exception as e:
            error_count += 1
            errors.append(f"{seller.full_name}: {str(e)[:50]}")
            logger.error(f"Notification send error to {seller.full_name}: {e}")

    # Natija
    message = (
        f"✅ <b>XABARNOMA YUBORILDI</b>\n\n"
        f"📤 Yuborildi: {success_count} ta\n"
        f"❌ Xato: {error_count} ta"
    )

    keyboard = [[InlineKeyboardButton("◀️ Ortga", callback_data="admin_notify")]]

    await query.message.edit_text(message, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

    # Context tozalash
    context.user_data.pop('sending_template', None)
    context.user_data.pop('selected_regions', None)
