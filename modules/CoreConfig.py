"""
Core Configuration
"""
import os
import logging
import re
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from dotenv import load_dotenv

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

# =====================================================
# Core Enums
# =====================================================
class UserState(Enum):
    """Essential user states only"""
    IDLE = auto()
    WAITING_NATIONAL_ID = auto()
    AUTHENTICATED = auto()
    WAITING_ORDER_NUMBER = auto()
    WAITING_SERIAL = auto()
    WAITING_COMPLAINT_TEXT = auto()
    WAITING_RATING_SCORE = auto()
    WAITING_RATING_TEXT = auto()
    WAITING_REPAIR_DESC = auto()
    WAITING_REPAIR_CONTACT = auto()
    RATE_LIMITED = auto()

class OrderStatus(Enum):
    """Order status mapping to your workflow"""
    WAREHOUSE_RECEIPT = 0      # رسید انبار
    PRE_RECEPTION = 1          # پیش پذیرش  
    RECEPTION = 2              # پذیرش
    IN_REPAIR = 3              # تعمیرات
    INVOICING = 4              # صدور صورتحساب
    FINANCIAL = 5              # مالی
    EXIT_PERMIT = 6            # صدور مجوز خروج کالا
    SHIPPED = 7                # ارسال
    COMPLETED = 8              # پایان

class ComplaintType(Enum):
    """Complaint types"""
    TECHNICAL = "technical"
    PAYMENT = "payment"
    SHIPPING = "shipping"
    SERVICE = "service"
    OTHER = "other"


# =====================================================
# Workflow Steps Mapping (9-stage process)
# =====================================================
WORKFLOW_STEPS = {
    0: "ثبت اولیه",
    1: "پذیرش",
    2: "بررسی فنی", 
    3: "تعمیرات",
    4: "صدور صورتحساب",
    5: "صورتحساب",
    6: "آماده ارسال",
    7: "ارسال شده",
    8: "تحویل داده شده"
}

# Progress calculation for each step
STEP_PROGRESS = {
    0: 0,
    1: 12.5,
    2: 25,
    3: 37.5,
    4: 50,
    5: 62.5,
    6: 75,
    7: 87.5,
    8: 100
}

# Step icons for visual representation
STEP_ICONS = {
    0: "📝",
    1: "✅",
    2: "🔍",
    3: "🔧",
    4: "📄",
    5: "💳",
    6: "📦",
    7: "🚚",
    8: "✔️"
}

def get_step_display(step: int) -> str:
    """Get formatted step display with icon"""
    icon = STEP_ICONS.get(step, "▫️")
    name = WORKFLOW_STEPS.get(step, "نامشخص")
    return f"{icon} {name}"

def calculate_progress(step: int) -> int:
    """Calculate progress percentage based on step"""
    return STEP_PROGRESS.get(step, 0)

# =====================================================
# Configuration
# =====================================================
@dataclass
class BotConfig:
    """Minimal bot configuration with complete API integration"""
    
    # Core settings (required)
    telegram_token: str
    
    # Redis configuration
    redis_url: str = "redis://localhost:6379/0"
    redis_password: Optional[str] = None
    
    # API Configuration
    auth_token: str = ""
    server_urls: Dict[str, str] = field(default_factory=dict)
    
    # System features
    maintenance_mode: bool = False
    
    # Rate limiting
    max_requests_hour: int = 100
    session_timeout: int = 30  # minutes

    # Contact information
    support_phone: str = os.getenv("SUPPORT_PHONE")
    website_url: str = os.getenv("WEBSITE_URL")
    
    def __post_init__(self):
        """Validate and initialize configuration"""
        if not self.telegram_token:
            raise ValueError("TELEGRAM_BOT_TOKEN is required in .env file")
        
        # Get auth token from environment
        self.auth_token = os.getenv("AUTH_TOKEN", "")

        # Initialize server URLs from environment if not provided
        if not self.server_urls:
            self.server_urls = {
                # Core tracking endpoints
                "number": os.getenv("SERVER_URL_NUMBER", ""),
                "serial": os.getenv("SERVER_URL_SERIAL", ""),
                "national_id": os.getenv("SERVER_URL_NATIONAL_ID", ""),
                
                # User endpoints
                "user_orders": os.getenv("SERVER_URL_USER_ORDERS", ""),
                
                # Support endpoints
                "submit_complaint": os.getenv("SERVER_URL_COMPLAINT", ""),
                "submit_rating": os.getenv("SERVER_URL_RATING", ""),
                "submit_repair": os.getenv("SERVER_URL_REPAIR", ""),
            }

        # Override maintenance mode from environment if set
        env_maintenance = os.getenv("MAINTENANCE_MODE", "").lower()
        if env_maintenance in ["true", "1", "yes"]:
            self.maintenance_mode = True
        
        # Log configuration status
        logger.info(f"Config loaded: Maintenance={self.maintenance_mode}, APIs configured={len([v for v in self.server_urls.values() if v])}/{len(self.server_urls)}")

# =====================================================
# Metrics
# =====================================================
@dataclass
class BotMetrics:
    """Simple metrics tracker"""
    total_sessions: int = 0
    active_sessions: int = 0
    authenticated_users: int = 0
    total_requests: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    
    def increment_request(self):
        self.total_requests += 1
    
    def get_cache_ratio(self) -> float:
        total = self.cache_hits + self.cache_misses
        return self.cache_hits / total if total > 0 else 0.0

# =====================================================
# Validators
# =====================================================
class Validators:
    """Input validators"""
    
    @staticmethod
    def validate_national_id(nid: str) -> bool:
        """Validate Iranian national ID"""
        if not nid or not nid.isdigit() or len(nid) != 10:
            return False
        
        check = sum(int(nid[i]) * (10 - i) for i in range(9)) % 11
        return check == int(nid[9]) if check < 2 else check == 11 - int(nid[9])
    
    @staticmethod
    def validate_phone(phone: str) -> bool:
        """Validate Iranian phone number"""
        pattern = r'^(\+98|0)?9\d{9}$'
        return bool(re.match(pattern, phone))
    
    @staticmethod
    def validate_order_number(order_num: str) -> bool:
        """Validate order number format"""
        return bool(order_num and (order_num.isdigit() or 
                   re.match(r'^[A-Z0-9-]+$', order_num)))

# =====================================================
# Message Templates
# =====================================================
MESSAGES = {
    'welcome': """🌟 سلام! به ربات پشتیبانی خوش آمدید

🤝 من دستیار هوشمند شما هستم و در این موارد کمکتون می‌کنم:
• 📦 پیگیری سفارشات
• 🔧 درخواست تعمیرات
• 💬 ثبت نظرات و شکایات
• ⭐ امتیازدهی به خدمات

از منو انتخاب کنید 👇""",

    'maintenance': """🔧 سیستم در حال به‌روزرسانی

سیستم موقتاً در دسترس نیست.
لطفاً لحظاتی دیگر مجدداً تلاش کنید.

☎️ پشتیبانی: 03133127""",

    'rate_limited': """⚠️ محدودیت درخواست

شما به حد مجاز درخواست رسیده‌اید.
لطفا {minutes} دقیقه صبر کنید.

💡 نکته: حداکثر {max_requests} درخواست در ساعت مجاز است.""",

    'auth_request': "🔐لطفا کد ملی خود را به صورت کامل وارد کنید.",
    
    'auth_success': "✅ احراز هویت موفق\n\nخوش آمدید {name} عزیز!",
    
    'auth_failed': "❌ کد ملی یافت نشد",
    
    'order_not_found': """❌ سفارش یافت نشد
لطفا شماره پذیرش یا سریال دستگاه را بررسی و دوباره وارد کنید!
""",

    'order_details': """📦 جزئیات سفارش

🔢 شماره پذیرش: {order_number}
👤 نام: {customer_name}
📱 دستگاه: {device_model}
📍 وضعیت: {status}
📊 پیشرفت: {progress}%
📅 تاریخ ثبت: {registration_date}

{additional_info}""",

    'help': """📚 راهنمای استفاده از ربات

1️⃣ **احراز هویت:** ابتدا با کد ملی خود وارد شوید
2️⃣ **پیگیری:** از شماره پذیرش یا سریال دستگاه استفاده کنید
3️⃣ **خدمات ویژه:** پس از ورود به امکانات زیر دسترسی دارید:
   • مشاهده تمام سفارشات
   • درخواست تعمیر جدید
   • ثبت شکایت و پیشنهاد
   • امتیازدهی به خدمات

💡 **نکات:**
• برای خروج از هر بخش از دکمه 'بازگشت' استفاده کنید
• جلسه شما پس از 30 دقیقه غیرفعالی منقضی می‌شود

☎️ پشتیبانی: 03133127
🌐 وب‌سایت: hamoonpay.com
📧 ایمیل: support@hamoonpay.com""",

    'repair_submitted': """✅ درخواست تعمیر با موفقیت ثبت شد

📋 شماره پیگیری: {request_number}
📅 تاریخ ثبت: {date}

⏰ کارشناسان ما طی 24 ساعت آینده با شما تماس خواهند گرفت.

🙏 از صبر و شکیبایی شما سپاسگزاریم""",

    'rating_thanks': """🙏 سپاس از نظر ارزشمند شما

⭐ امتیاز شما: {stars}
💬 نظر شما: {comment}

نظرات شما به ما کمک می‌کند خدمات بهتری ارائه دهیم.
با آرزوی روزهای خوش برای شما 🌹""",

    'complaint_submitted': """✅ شکایت/پیشنهاد شما ثبت شد

🎫 شماره تیکت: {ticket_number}
📋 نوع: {complaint_type}
📅 تاریخ: {date}

⏰ واحد پشتیبانی حداکثر تا 48 ساعت آینده با شما تماس خواهد گرفت.

از صبر شما سپاسگزاریم 🙏""",

    'invalid_input': "❌ ورودی نامعتبر\n\nلطفاً مجدداً با فرمت صحیح وارد کنید.",
    
    'session_expired': """⏱ جلسه شما منقضی شد

برای ادامه، لطفا دوباره با /start شروع کنید.""",
    
    'error': """❌ خطا در پردازش درخواست

متاسفانه خطایی رخ داده است.
لطفاً دوباره تلاش کنید یا با پشتیبانی تماس بگیرید.

☎️ پشتیبانی: 03133127"""
}


# Status mappings
STATUS_TEXT = {
    0: "رسید انبار",           # Warehouse Receipt
    1: "پیش پذیرش",           # Pre-Reception
    2: "پذیرش",               # Reception
    3: "تعمیرات",              # Repairs
    4: "صدور صورتحساب",        # Invoice Issuance
    5: "مالی",                 # Financial
    6: "صدور مجوز خروج کالا",   # Exit Permit Issuance
    7: "ارسال",                # Shipping
    8: "پایان"                 # Completed
}

COMPLAINT_TYPE_MAP = {
    ComplaintType.TECHNICAL: "فنی",
    ComplaintType.PAYMENT: "مالی و پرداخت",
    ComplaintType.SHIPPING: "ارسال و تحویل",
    ComplaintType.SERVICE: "خدمات و پشتیبانی",
    ComplaintType.OTHER: "سایر موارد"
}
# =====================================================
# Initialize
# =====================================================
def initialize_core():
    """Initialize core components with environment variables"""
    
    # Load environment variables
    load_dotenv()
    
    # Create configuration
    config = BotConfig(
        telegram_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        auth_token=os.getenv("AUTH_TOKEN", ""),
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        redis_password=os.getenv("REDIS_PASSWORD"),
        server_urls={
            "number": "http://192.168.41.41:8010/api/v1/ass-process/GetByNumber",
            "serial": "http://192.168.41.41:8010/api/v1/ass-process/GetBySerial",
        },
        maintenance_mode=os.getenv("MAINTENANCE_MODE", "false").lower() == "true",
        max_requests_hour=int(os.getenv("MAX_REQUESTS_HOUR", "100")),
        session_timeout=int(os.getenv("SESSION_TIMEOUT", "30")),
        support_phone=os.getenv("SUPPORT_PHONE"),
        website_url=os.getenv("WEBSITE_URL")
    )
    
    # Server URLs will be loaded in __post_init__
    
    # Create other components
    metrics = BotMetrics()
    validators = Validators()
    
    logger.info(f"✅ Core initialized successfully")
    logger.info(f"📊 Config: Token={'✓' if config.telegram_token else '✗'}, "
                f"Redis={config.redis_url}, "
                f"Maintenance={config.maintenance_mode}")
    
    return config, validators, metrics
