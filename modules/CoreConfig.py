"""
Core Configuration - All constants and utilities
ENHANCED VERSION - Complete and consistent
"""
import os
import logging
import re
from enum import Enum, auto
from telegram import KeyboardButton, InlineKeyboardButton
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Tuple
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()
logger = logging.getLogger(__name__)

class UserState(Enum):
    """User session states"""
    IDLE = auto()
    WAITING_nationalId = auto()
    AUTHENTICATED = auto()
    WAITING_ORDER_NUMBER = auto()
    WAITING_SERIAL = auto()
    WAITING_COMPLAINT_TYPE = auto()
    WAITING_COMPLAINT_TEXT = auto()
    WAITING_REPAIR_DESC = auto()
    RATE_LIMITED = auto()

class ComplaintType(Enum):
    """Complaint categories"""
    TECHNICAL = "technical"
    PAYMENT = "payment"
    SHIPPING = "shipping"
    SERVICE = "service"
    OTHER = "other"

class CallbackFormats:
    """Standard callback data patterns"""
    
    # Navigation
    MAIN_MENU = "main_menu"
    BACK = "back"
    CANCEL = "cancel"
    
    # Authentication
    AUTHENTICATE = "authenticate"
    LOGOUT = "logout"
    
    # User actions
    MY_INFO = "my_info"
    MY_ORDERS = "my_orders"
    
    # Tracking
    TRACK_BY_NUMBER = "track_by_number"
    TRACK_BY_SERIAL = "track_by_serial"
    
    # Services
    REPAIR_REQUEST = "repair_request"
    SUBMIT_COMPLAINT = "submit_complaint"
    
    # Help
    HELP = "help"
    
    # Dynamic patterns
    ORDER_DETAILS = "order_{}"
    REFRESH_ORDER = "refresh_order:{}"
    COMPLAINT_TYPE = "complaint:{}"
    NOOP = "noop"

    @staticmethod
    def parse_callback(data: str) -> tuple:
        """Parse callback data"""
        if ":" in data:
            parts = data.split(":", 1)
            return parts[0], parts[1]
        return data, None

# ========== KEYBOARDS - FIXED SIZING ==========
MAIN_INLINE_KEYBOARD = [
    [InlineKeyboardButton("🔐 ورود با کد ملی", callback_data=CallbackFormats.AUTHENTICATE)],
    [InlineKeyboardButton("🔢 پیگیری سفارش", callback_data=CallbackFormats.TRACK_BY_NUMBER),
     InlineKeyboardButton("#️⃣ پیگیری سریال", callback_data=CallbackFormats.TRACK_BY_SERIAL)],
    [InlineKeyboardButton("❓ راهنما", callback_data=CallbackFormats.HELP)]
]

AUTHENTICATED_INLINE_KEYBOARD = [
    [InlineKeyboardButton("👤 اطلاعات من", callback_data=CallbackFormats.MY_INFO)],
    [InlineKeyboardButton("📦 سفارشات من", callback_data=CallbackFormats.MY_ORDERS)],
    [InlineKeyboardButton("🔢 پیگیری سفارش", callback_data=CallbackFormats.TRACK_BY_NUMBER)],
    [InlineKeyboardButton("🔧 درخواست تعمیر", callback_data=CallbackFormats.REPAIR_REQUEST)],
    [InlineKeyboardButton("📝 ثبت شکایت", callback_data=CallbackFormats.SUBMIT_COMPLAINT)],
    [InlineKeyboardButton("🚪 خروج", callback_data=CallbackFormats.LOGOUT)]
]

MAIN_REPLY_KEYBOARD = [
    [KeyboardButton("🔐 ورود با کد ملی")],
    [KeyboardButton("🔢 پیگیری سفارش"), KeyboardButton("#️⃣ پیگیری سریال")],
    [KeyboardButton("❓ راهنما")]
]

CANCEL_REPLY_KEYBOARD = [[KeyboardButton("❌ انصراف")]]

REPLY_BUTTON_TO_CALLBACK = {
    "🔐 ورود با کد ملی": CallbackFormats.AUTHENTICATE,
    "🔢 پیگیری سفارش": CallbackFormats.TRACK_BY_NUMBER,
    "#️⃣ پیگیری سریال": CallbackFormats.TRACK_BY_SERIAL,
    "📦 سفارشات من": CallbackFormats.MY_ORDERS,
    "❓ راهنما": CallbackFormats.HELP,
    "❌ انصراف": CallbackFormats.CANCEL
}

# ========== WORKFLOW DEFINITIONS ==========
WORKFLOW_STEPS = {
    0: "ورود مرسوله",
    1: "پیش‌پذیرش", 
    2: "پذیرش نهایی",
    3: "در حال تعمیر",
    4: "صدور صورتحساب",
    5: "پرداخت و خزانه",
    6: "آماده ارسال",
    7: "در حال ارسال",
    8: "تحویل شده",
    9: "منتظر پرداخت",
    10: "راکد/معلق",
    50: "تکمیل شده"
}

STEP_ICONS = {
    0: "📥", 1: "📝", 2: "✅", 3: "🔧", 4: "📄",
    5: "💰", 6: "📦", 7: "🚚", 8: "📬", 9: "⏳",
    10: "⏸️", 50: "✔️"
}

STEP_PROGRESS = {
    0: 0, 1: 15, 2: 25, 3: 45, 4: 60, 5: 75,
    6: 85, 7: 90, 8: 95, 9: 80, 10: 20, 50: 100
}

DEVICE_STATUS = {
    0: "نامشخص",
    1: "در انتظار",
    2: "پذیرش شده", 
    3: "در حال تعمیر",
    4: "آماده تحویل",
    5: "تحویل شده",
    99: "لغو شده"
}

COMPLAINT_TYPE_MAP = {
    ComplaintType.TECHNICAL: "مشکل فنی",
    ComplaintType.PAYMENT: "مشکل پرداخت", 
    ComplaintType.SHIPPING: "مشکل ارسال",
    ComplaintType.SERVICE: "پشتیبانی",
    ComplaintType.OTHER: "سایر موارد"
}

STATE_LABELS = {
    UserState.IDLE: "آماده",
    UserState.WAITING_nationalId: "انتظار احراز هویت",
    UserState.AUTHENTICATED: "احراز شده",
    UserState.WAITING_ORDER_NUMBER: "انتظار شماره سفارش",
    UserState.WAITING_SERIAL: "انتظار شماره سریال"
}

# ========== UTILITY FUNCTIONS ==========
def get_step_info(step: int) -> Dict[str, Any]:
    """Get complete step information - FIXED"""
    step_num = int(step) if step is not None else 0
    progress = STEP_PROGRESS.get(step_num, 0)
    icon = STEP_ICONS.get(step_num, '📍')
    text = WORKFLOW_STEPS.get(step_num, 'نامشخص')
    
    # Safe progress bar calculation
    filled = int((progress / 100) * 10)
    bar = "█" * filled + "░" * (10 - filled)
    
    return {
        'text': text,
        'icon': icon,
        'progress': progress,
        'display': f"{icon} {text}",
        'bar': bar,
        'step_num': step_num
    }

def get_step_display(step: int) -> str:
    """Get formatted step display"""
    info = get_step_info(step)
    return info['display']

def safe_format_date(date_str: Any, default: str = "نامشخص") -> str:
    """Safely format dates - FIXED"""
    if not date_str or date_str == "None":
        return default
    
    try:
        if isinstance(date_str, datetime):
            return date_str.strftime('%Y/%m/%d')
        
        date_str = str(date_str).strip()
        if ' ' in date_str:
            date_str = date_str.split(' ')[0]
        
        # Handle Jalali dates (YYYY/MM/DD format)
        if '/' in date_str:
            parts = date_str.split('/')
            if len(parts) == 3 and all(part.isdigit() for part in parts):
                year = int(parts[0])
                if 1300 <= year <= 1500:  # Jalali year range
                    return f"{parts[0]}/{parts[1]}/{parts[2]}"
        
        return date_str
    except:
        return default

# ========== MESSAGES - COMPLETE SET ==========
MESSAGES = {
    'welcome': """🌟 **سلام!** به ربات پشتیبانی هامون خوش آمدید

🤖 من دستیار هوشمند شما هستم و آماده کمک در موارد زیر:

🛒 پیگیری سفارش و مرسولات
🔧 ثبت درخواست تعمیرات  
📦 مشاهده سفارشات فعال
📝 ثبت شکایت و پیشنهاد
❓ راهنمای کامل استفاده

👇 از منوی زیر شروع کنید 👇""",

    'maintenance': """🔧 **سیستم در حال به‌روزرسانی**

لطفاً چند دقیقه صبر کنید و دوباره تلاش کنید.

☎️ **پشتیبانی:** {support_phone}""",

    'rate_limited': """⚠️ **محدودیت موقت**

برای جلوگیری از سوءاستفاده، لطفاً {minutes} دقیقه صبر کنید.

حداکثر {max_requests} درخواست در ساعت مجاز است.""",

    'auth_request': """🔐 **احراز هویت**

لطفاً کد ملی ۱۰ رقمی خود را وارد کنید:

`1234567890`

💡 نکته: فقط ارقام، بدون خط تیره""",

    'auth_success': """✅ **احراز هویت موفق**

خوش آمدید {name} عزیز!

📱 شماره: {phone}
🏙️ شهر: {city}

حالا به تمام امکانات دسترسی دارید ✅""",

    'auth_failed': """❌ **کد ملی یافت نشد**

لطفاً:
• از صحت کد ملی مطمئن شوید
• اتصال اینترنت را بررسی کنید
• دوباره تلاش کنید""",

    'order_not_found': """❌ **سفارش یافت نشد**

{lookup_type}: `{value}`

ممکن است:
• شماره اشتباه وارد شده باشد
• سفارش هنوز ثبت نشده باشد
• از فرمت صحیح استفاده نکرده باشید

💡 مثال صحیح: `12345`""",

    'order_details': """📦 **جزئیات سفارش {order_number}**

👤 **مشتری:** {customer_name}
📱 **دستگاه:** {device_model}

{progress_bar}
📍 **وضعیت:** {status_text}

💰 **هزینه:** {total_cost} تومان
📅 **ثبت:** {registration_date}

{additional_info}""",

    "help": """📚 راهنمای کامل استفاده

━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔹 شروع سریع

1️⃣ ورود - کد/شناسی ملی
2️⃣ پیگیری - شماره پذیرش  یا سریال  
3️⃣ سفارشات - مشاهده تاریخچه
4️⃣ تعمیر - ثبت درخواست
5️⃣ شکایت - گزارش مشکل

━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 فرمت‌های صحیح

🔢 شماره سفارش: `123456` (فقط اعداد)
#️⃣ شماره سریال: `01HEC23456` (حروف+اعداد)
🔐 کد/شناسه ملی: `1234567890` (۱۰ یا ۱۱ رقمی)

━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚡ امکانات ویژه

⭐ سفارشات من - تمام سفارشات فعال
🔍 جستجوی سریع - با شماره پذیرش یا سریال
📊 گزارش پیشرفت - وضعیت لحظه‌ای سفارش شما
📞 پشتیبانی ۲۴/۷ - پاسخگویی فوری

━━━━━━━━━━━━━━━━━━━━━━━━━━━
💡 نکات کاربردی

• ⏰ جلسه ۳۰ دقیقه‌ای - برای تمدید فعال بمانید
• 🔄 بروزرسانی - دکمه refresh را بزنید
• ❌ انصراف - هر زمان می‌توانید لغو کنید
• 📱 موبایل - بهترین تجربه در تلگرام

━━━━━━━━━━━━━━━━━━━━━━━━━━━
📞 تماس با ما

🏢 آدرس: اصفهان، خیابان توحید ساختمان آریا واحد ۲۰۱
☎️ تلفن: {support_phone}
🌐 وب‌سایت: {website_url}

🕐 ساعات کاری:
شنبه تا چهارشنبه: ۸:۰۰ - ۱۶:۳۰
پنجشنبه: ۸:۰۰ - ۱۲:۰۰

━━━━━━━━━━━━━━━━━━━━━━━━━━━
💙 ممنون که همراه ما هستید!""",
    
    'payment_link': """💳 **لینک پرداخت آنلاین**

💰 **مبلغ:** {amount:,} تومان
📄 **شماره فاکتور:** {invoice_id}

🔗 **[پرداخت آنلاین]({link})**

⚠️ این لینک شامل جزئیات کامل فاکتور است
✅ پس از پرداخت، وضعیت بروزرسانی می‌شود""",

    'payment_completed': """✅ **پرداخت موفق**

🎫 **شماره فاکتور:** {invoice_id}
💳 **کد پیگیری:** {reference_code}
💰 **مبلغ:** {amount:,} تومان  
📅 **تاریخ:** {payment_date}

سفارش شما در صف پردازش قرار گرفت ✅""",

    'repair_submitted': """🔧 **درخواست تعمیر ثبت شد**

📋 **شماره درخواست:** `{request_number}`
📅 **تاریخ ثبت:** {date}
⏳ **وضعیت:** در حال بررسی

📞 تیم فنی ظرف ۲۴ ساعت با شما تماس خواهد گرفت""",

    'complaint_submitted': """📝 **شکایت ثبت شد**

🎫 **شماره تیکت:** `{ticket_number}`
📅 **تاریخ:** {date}
🏷️ **دسته‌بندی:** {complaint_type}

👥 تیم پشتیبانی ظرف ۴۸ ساعت پاسخ خواهد داد

💡 می‌توانید از منوی اصلی، وضعیت را پیگیری کنید""",

    'invalid_input': """❌ **ورودی نامعتبر**

لطفاً:
• فقط اعداد وارد کنید
• فرمت صحیح را رعایت کنید  
• از مثال‌های راهنما استفاده کنید

🔙 برای بازگشت به منو، "منوی اصلی" را بزنید""",

    'session_expired': """⏱️ **جلسه منقضی شد**

فعالیت شما بیش از ۳۰ دقیقه طول کشید.

🔄 لطفاً با /start دوباره شروع کنید""",

    'error': """❌ **خطای سیستمی**

متأسفانه خطایی رخ داد.

💡 راه‌حل‌ها:
• اتصال اینترنت را بررسی کنید
• چند دقیقه صبر کنید
• دوباره تلاش کنید

📞 در صورت ادامه مشکل: {support_phone}""",

    'loading': "⏳ **در حال بارگذاری...**",

    'no_orders_found': "📭 **سفارش فعال ندارید**\n\nاولین سفارش خود را ثبت کنید! 🚀",

    'contact_info': """📞 **اطلاعات تماس**

🏢 **آدرس:** اصفهان، خیابان توحید میانی
☎️ **تلفن:** {support_phone}
🌐 **وب‌سایت:** {website_url}

🕐 **ساعات کاری:**
شنبه-چهارشنبه: ۸:۰۰-۱۶:۳۰
پنجشنبه: ۸:۰۰-۱۲:۰۰""",

    'enter_complaint_text': """📝 **ثبت شکایت**

لطفاً مشکل خود را با جزئیات شرح دهید:

💡 نکات:
• حداقل ۱۰ کلمه بنویسید
• تاریخ و زمان مشکل را ذکر کنید  
• راه ارتباطی خود را بنویسید

متن خود را در ادامه بنویسید...""",

    'enter_repair_description': """🔧 **درخواست تعمیر**

مشکل دستگاه خود را با جزئیات شرح دهید:

📱 **مثال:**
"گوشی سامسونگ A52، صفحه نمایش شکسته، افتاده از ارتفاع ۱ متر"

مشکل خود را بنویسید...""",

    'order_tracking_prompt': """🔢 **پیگیری با شماره سفارش**

شماره پذیرش ۵-۶ رقمی خود را وارد کنید:

💡 **مثال:** `12345`

فقط اعداد، بدون فاصله یا خط تیره""",

    'serial_tracking_prompt': """#️⃣ **پیگیری با شماره سریال**

شماره سریال ۱۰ کاراکتری دستگاه را وارد کنید:

💡 **مثال:** `01HEC23456`

ترکیب حروف و اعداد، بدون فاصله"""
}

# ========== CONFIGURATION ==========
@dataclass
class BotConfig:
    """Bot configuration with defaults"""
    telegram_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    redis_password: str = field(default_factory=lambda: os.getenv("REDIS_PASSWORD", None))
    auth_token: str = field(default_factory=lambda: os.getenv("AUTH_TOKEN", ""))
    
    # API endpoints
    server_urls: Dict[str, str] = field(default_factory=lambda: {
        "number": os.getenv("SERVER_URL_NUMBER", "http://192.168.41.41:8010/api/v1/ass-process/GetByNumber"),
        "serial": os.getenv("SERVER_URL_SERIAL", "http://192.168.41.41:8010/api/v1/ass-process/GetBySerial"),
        "national_id": os.getenv("SERVER_URL_NATIONAL_ID", "http://192.168.41.41:8010/api/v1/ass-process/GetByNationalID"),
        "user_orders": os.getenv("SERVER_URL_USER_ORDERS", "http://192.168.41.41:8010/api/v1/ass-process/GetByNationalID"),
        "submit_complaint": os.getenv("SERVER_URL_COMPLAINT", "http://192.168.41.41:8010/api/v1/complaints"),
        "submit_repair": os.getenv("SERVER_URL_REPAIR", "http://192.168.41.41:8010/api/v1/repairs"),
    })
    
    # Bot settings
    maintenance_mode: bool = field(default_factory=lambda: os.getenv("MAINTENANCE_MODE", "false").lower() == "true")
    max_requests_hour: int = field(default_factory=lambda: int(os.getenv("MAX_REQUESTS_HOUR", "100")))
    session_timeout: int = field(default_factory=lambda: int(os.getenv("SESSION_TIMEOUT", "1800")))  # 30 minutes
    
    # Contact info
    support_phone: str = field(default_factory=lambda: os.getenv("SUPPORT_PHONE", "031-33127"))
    website_url: str = field(default_factory=lambda: os.getenv("WEBSITE_URL", "https://hamoonpay.com"))

    def __post_init__(self):
        """Validate required config"""
        if not self.telegram_token:
            raise ValueError("TELEGRAM_BOT_TOKEN is required in environment variables")
        
        logger.info(f"BotConfig initialized - Maintenance: {self.maintenance_mode}")

class Validators:
    """Input validation utilities"""
    
    @staticmethod
    def validate_national_id(nid: str) -> bool:
        """Validate 10-digit Iranian national ID"""
        if not nid or not nid.isdigit() or len(nid) != 10:
            return False
        
        # Check digit validation
        check_sum = sum(int(nid[i]) * (10 - i) for i in range(9)) % 11
        if check_sum < 2:
            return check_sum == int(nid[9])
        return 11 - check_sum == int(nid[9])
    
    @staticmethod
    def validate_order_number(order_number: str) -> Tuple[bool, Optional[str]]:
        """Validate order number format - 3-12 digits only"""
        if not order_number:
            return False, "شماره سفارش نمی‌تواند خالی باشد"
        
        cleaned = order_number.strip()
        if re.match(r'^\d{3,12}$', cleaned):
            return True, None
        
        return False, (
            "فرمت شماره سفارش نامعتبر است. لطفاً:\n"
            "• فقط عدد شماره پذیرش (مثال: 123456)\n"
            "را وارد کنید"
        )
    
    @staticmethod
    def validate_serial(serial: str) -> Tuple[bool, Optional[str]]:
        """Validate device serial (alphanumeric, 8-12 chars)"""
        if not serial:
            return False, "سریال نمی‌تواند خالی باشد"
        cleaned = re.sub(r"[ \-\_]", "", serial.strip().upper())
        if len(cleaned) == 0:
            return False, "سریال نامعتبر است"
        
        # Validate SHORT SERIAL (last 6 digits)
        if re.match(r"^\d{6}$", cleaned):
            if cleaned != "000000":
                return True, None
            else:
                return False, "سریال نمی‌تواند تمام صفر باشد"
        
        # Validate FULL SERIAL (10-12 alphanumeric chars)
        if 10 <= len(cleaned) <= 12 and re.match(r"^[A-Z0-9]+$", cleaned):
            return True, None
        
        # ❌ Invalid format
        return False, (
            "فرمت سریال نامعتبر است. لطفاً:\n"
            "• 6 رقم آخر سریال (مثال: 234567)\n"
            "• یا سریال کامل (مثال: 01HEC2345678)\n"
            "را وارد کنید ❌"
        )
    
    @staticmethod
    def validate_complaint_text(text: str) -> bool:
        """Validate complaint text (min 10 chars)"""
        return bool(text and len(text.strip()) >= 10)
    
    @staticmethod
    def validate_repair_description(text: str) -> bool:
        """Validate repair description (min 10 chars)"""
        return bool(text and len(text.strip()) >= 10)

class BotMetrics:
    """Simple metrics tracking"""
    def __init__(self):
        self.total_sessions = 0
        self.active_sessions = 0
        self.authenticated_users = 0
        self.total_requests = 0
        self.api_calls = 0
        self.errors = 0
        self.cache_hits = 0
        self.cache_misses = 0
    
    def increment_request(self):
        self.total_requests += 1
    
    def increment_error(self):
        self.errors += 1
    
    def get_stats(self) -> Dict[str, Any]:
        return {
            'total_requests': self.total_requests,
            'error_rate': (self.errors / max(self.total_requests, 1)) * 100,
            'active_sessions': self.active_sessions
        }

# ========== INITIALIZATION ==========
def initialize_core() -> tuple:
    """Initialize core components"""
    try:
        config = BotConfig()
        validators = Validators()
        metrics = BotMetrics()
        
        logger.info("Core components initialized successfully")
        return config, validators, metrics
    except Exception as e:
        logger.error(f"Core initialization failed: {e}")
        raise

# Global instances for convenience (in production, use DI)
CORE_CONFIG, VALIDATORS, METRICS = initialize_core()
