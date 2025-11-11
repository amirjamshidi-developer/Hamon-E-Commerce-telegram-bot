"""
Unified and structured CallbackData factories for Aiogram 3.
This replaces the mixed model of static strings and generic callbacks.
"""
from aiogram.filters.callback_data import CallbackData
from typing import Optional
from src.config.enums import ComplaintType

class MenuCallback(CallbackData, prefix="menu"):
    """For simple, top-level navigation actions."""
    target: str  # e.g., 'main_menu', 'auth_menu', 'help', 'cancel', 'back'

class AuthCallback(CallbackData, prefix="auth"):
    """For all authentication-related actions."""
    action: str  # e.g., 'start', 'logout_prompt', 'my_info' & 'orders_list'

class OrderCallback(CallbackData, prefix="order"):
    """For actions related to a specific order."""
    action: str  # e.g., 'order_details', 'refresh' & 'devices_list' & 'orders_list'
    order_number: Optional[str] = None 
    page: Optional[int] = None

class ServiceCallback(CallbackData, prefix="service"):
    """For service requests like repairs or complaints."""
    action: str # e.g., 'repair_start', 'complaint_start', 'select_complaint'
    type_id: Optional[int] = None

class TrackCallback(CallbackData, prefix="track"):
    """For prompting tracking flows."""
    action: str # e.g., 'prompt_number' & 'prompt_serial'

REPLY_BUTTON_TO_CALLBACK_ACTION = {
    "👤 اطلاعات من": AuthCallback(action="my_info"),
    "📦 لیست سفارشات من": OrderCallback(action="order_list"),
    "📞 درخواست تعمیرات": ServiceCallback(action="repair_start"),
    "📝 ثبت شکایات": ServiceCallback(action="complaint_start"),
    "🚪 خروج از حساب": AuthCallback(action="logout_prompt"),
    "🔐 ورود با کد/شناسه ملی": AuthCallback(action="start"),
    "🔢 پیگیری با شماره پذیرش": TrackCallback(action="prompt_number"),
    "#️⃣ پیگیری با سریال": TrackCallback(action="prompt_serial"),
    "❓ راهنما": MenuCallback(target="help"),
    "🏠 منوی اصلی": MenuCallback(target="main_menu"),
    "🔙 بازگشت به منوی اصلی": MenuCallback(target="main_menu"),
    "❌ انصراف": MenuCallback(target="cancel"),
    "🔄 بروزرسانی اطلاعات":OrderCallback(action="refresh"),
    "🔍 بازگشت به جزئیات سفارش ":OrderCallback(action="order_details"),
    "🔍 مشاهده لیست کامل دستگاه‌ها":OrderCallback(action="devices_list"),
    "🔧 خرابی و تعمیرات دستگاه": ServiceCallback(action="select_complaint", type_id=ComplaintType.DEVICE_ISSUE.id),
    "🚚 ارسال و دریافت دستگاه": ServiceCallback(action="select_complaint", type_id=ComplaintType.SHIPPING.id),
    "💰 بخش مالی و حسابداری": ServiceCallback(action="select_complaint", type_id=ComplaintType.FINANCIAL.id),
    "👤 پشتیبانی و رفتار پرسنل": ServiceCallback(action="select_complaint", type_id=ComplaintType.PERSONNEL.id),
    "📈 بخش فروش و توسعه بازار": ServiceCallback(action="select_complaint", type_id=ComplaintType.SALES.id),
    "📝 سایر موارد": ServiceCallback(action="select_complaint", type_id=ComplaintType.OTHER.id),
}
