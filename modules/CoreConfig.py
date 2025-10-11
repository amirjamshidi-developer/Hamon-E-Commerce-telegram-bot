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

# Logging setup
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
    """User state machine"""
    IDLE = auto()
    WAITING_NATIONAL_ID = auto()
    AUTHENTICATED = auto()
    WAITING_ORDER_NUMBER = auto()
    WAITING_SERIAL = auto()
    WAITING_COMPLAINT_TEXT = auto()
    WAITING_RATING_SCORE = auto()
    WAITING_RATING_TEXT = auto()
    WAITING_REPAIR_DESC = auto()
    RATE_LIMITED = auto()

class OrderStatus(Enum):
    """Order workflow stages"""
    WAREHOUSE_RECEIPT = 0
    PRE_RECEPTION = 1
    RECEPTION = 2
    IN_REPAIR = 3
    INVOICING = 4
    FINANCIAL = 5
    EXIT_PERMIT = 6
    SHIPPED = 7
    COMPLETED = 8

class ComplaintType(Enum):
    """Complaint categories"""
    TECHNICAL = "technical"
    PAYMENT = "payment"
    SHIPPING = "shipping"
    SERVICE = "service"
    OTHER = "other"

# =====================================================
# Workflow Configuration
# =====================================================
WORKFLOW_STEPS = {
    0: "ثبت اولیه",
    1: "پذیرش",
    2: "بررسی فنی",
    3: "در حال تعمیر",
    4: "صدور صورتحساب",
    5: "پرداخت",
    6: "آماده ارسال",
    7: "ارسال شده",
    8: "تحویل داده شده"
}

STEP_PROGRESS = {
    0: 0, 1: 12.5, 2: 25, 3: 37.5, 4: 50,
    5: 62.5, 6: 75, 7: 87.5, 8: 100
}

STEP_ICONS = {
    0: "📝", 1: "✅", 2: "🔍", 3: "🔧",
    4: "📄", 5: "💳", 6: "📦", 7: "🚚", 8: "✔️"
}

STATUS_TEXT = {
    0: "رسید انبار",
    1: "پیش پذیرش",
    2: "پذیرش",
    3: "تعمیرات",
    4: "صدور صورتحساب",
    5: "مالی",
    6: "صدور مجوز خروج کالا",
    7: "ارسال",
    8: "پایان"
}

COMPLAINT_TYPE_MAP = {
    ComplaintType.TECHNICAL: "فنی",
    ComplaintType.PAYMENT: "مالی و پرداخت",
    ComplaintType.SHIPPING: "ارسال و تحویل",
    ComplaintType.SERVICE: "خدمات و پشتیبانی",
    ComplaintType.OTHER: "سایر موارد"
}

# =====================================================
# Helper Functions
# =====================================================
def get_step_display(step: int) -> str:
    """Get step with icon"""
    return f"{STEP_ICONS.get(step, '▫️')} {WORKFLOW_STEPS.get(step, 'نامشخص')}"

def calculate_progress(step: int) -> float:
    """Calculate progress percentage"""
    return STEP_PROGRESS.get(step, 0)

def generate_progress_bar(progress: float, width: int = 10) -> str:
    """Generate visual progress bar"""
    progress = max(0, min(100, progress))
    filled = int((progress / 100) * width)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {progress:.1f}%"

def get_status_info(status: int, steps: Optional[int] = None) -> Dict[str, Any]:
    """Get status information"""
    step = steps if steps is not None else status
    progress = calculate_progress(step)
    
    return {
        'status_text': STATUS_TEXT.get(status, "نامشخص"),
        'step_text': WORKFLOW_STEPS.get(step, "نامشخص"),
        'icon': STEP_ICONS.get(step, "📍"),
        'progress': progress,
        'progress_bar': generate_progress_bar(progress),
        'is_completed': status == 8
    }

# =====================================================
# Configuration
# =====================================================
@dataclass
class BotConfig:
    """Bot configuration"""
    telegram_token: str
    redis_url: str = "redis://localhost:6379/0"
    redis_password: Optional[str] = None
    auth_token: str = ""
    server_urls: Dict[str, str] = field(default_factory=dict)
    maintenance_mode: bool = False
    max_requests_hour: int = 100
    session_timeout: int = 30
    support_phone: str = "03133127"
    website_url: str = "https://hamoonpay.com"
    support_email: str = "support@hamoonpay.com"
    
    def __post_init__(self):
        """Initialize configuration"""
        if not self.telegram_token:
            raise ValueError("TELEGRAM_BOT_TOKEN required")
        
        # Load from environment
        self.auth_token = os.getenv("AUTH_TOKEN", "")
        self.support_phone = os.getenv("SUPPORT_PHONE", "03133127")
        self.website_url = os.getenv("WEBSITE_URL", "https://hamoonpay.com")
        
        # Server URLs
        if not self.server_urls:
            base_url = "http://192.168.41.41:8010/api/v1"
            self.server_urls = {
                "number": os.getenv("SERVER_URL_NUMBER", f"{base_url}/ass-process/GetByNumber"),
                "serial": os.getenv("SERVER_URL_SERIAL", f"{base_url}/ass-process/GetBySerial"),
                "national_id": os.getenv("SERVER_URL_NATIONAL_ID", ""),
                "user_orders": os.getenv("SERVER_URL_USER_ORDERS", ""),
                "submit_complaint": os.getenv("SERVER_URL_COMPLAINT", ""),
                "submit_rating": os.getenv("SERVER_URL_RATING", ""),
                "submit_repair": os.getenv("SERVER_URL_REPAIR", ""),
            }
        
        # Check maintenance mode
        if os.getenv("MAINTENANCE_MODE", "").lower() in ["true", "1", "yes"]:
            self.maintenance_mode = True

# =====================================================
# Metrics
# =====================================================
@dataclass
class BotMetrics:
    """Metrics tracker"""
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
        """Validate phone number"""
        return bool(re.match(r'^(\+98|0)?9\d{9}$', phone))
    
    @staticmethod
    def validate_order_number(order_num: str) -> bool:
        """Validate order number"""
        return bool(order_num and re.match(r'^[A-Z0-9-]+$', order_num, re.I))

# =====================================================
# Message Templates
# =====================================================
MESSAGES = {
    'welcome': """🌟 سلام! به ربات پشتیبانی خوش آمدید

🤝 من دستیار هوشمند شما هستم:
• 📦 پیگیری سفارشات
• 🔧 درخواست تعمیرات
• 💬 ثبت نظرات و شکایات
• ⭐ امتیازدهی به خدمات

از منو انتخاب کنید 👇""",

    'maintenance': "🔧 سیستم در حال به‌روزرسانی\n\n☎️ پشتیبانی: {support_phone}",
    
    'rate_limited': "⚠️ محدودیت درخواست\n\nلطفا {minutes} دقیقه صبر کنید.",
    
    'auth_request': "🔐 لطفا کد ملی خود را وارد کنید:",
    
    'auth_success': "✅ احراز هویت موفق\n\nخوش آمدید {name} عزیز!",
    
    'auth_failed': "❌ کد ملی یافت نشد",
    
    'order_not_found': "❌ سفارش یافت نشد\n\nلطفا شماره را بررسی کنید.",
    
    'order_details': """📦 جزئیات سفارش

🔢 شماره: {order_number}
👤 نام: {customer_name}
📱 دستگاه: {device_model}

{progress_bar}
📍 {status}

📅 ثبت: {registration_date}

{additional_info}""",

    'help': """📚 راهنمای ربات

1️⃣ با کد ملی وارد شوید
2️⃣ از شماره پذیرش یا سریال استفاده کنید
3️⃣ به خدمات ویژه دسترسی داشته باشید

☎️ {support_phone}
🌐 {website_url}""",

    'repair_submitted': "✅ درخواست تعمیر ثبت شد\n\n📋 شماره: {request_number}",
    
    'rating_thanks': "🙏 سپاس از نظر شما\n\n⭐ امتیاز: {stars}",
    
    'complaint_submitted': "✅ شکایت ثبت شد\n\n🎫 شماره: {ticket_number}",
    
    'invalid_input': "❌ ورودی نامعتبر",
    
    'session_expired': "⏱ جلسه منقضی شد\n\nدوباره /start کنید",
    
    'error': "❌ خطا در پردازش\n لطفا دوباره امتحان کنید.",
    
    'loading': "⏳ در حال جستجو...",
    
    'no_orders_found': "📭 سفارشی یافت نشد",
    
    'contact_info': """📞 اطلاعات تماس

☎️ {support_phone}
🌐 {website_url}
📧 {support_email}""",

    'enter_complaint_text': "📝 متن شکایت را بنویسید:",
    
    'enter_rating_score': "⭐ امتیاز (1-5):",
    
    'enter_repair_description': "🔧 توضیحات تعمیر:",
    
    'order_tracking_prompt': "🔢 شماره پذیرش:",
    
    'serial_tracking_prompt': "#️⃣ سریال دستگاه:",
}

# =====================================================
# Initialize
# =====================================================
def initialize_core():
    """Initialize core components"""
    config = BotConfig(
        telegram_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        redis_password=os.getenv("REDIS_PASSWORD"),
        maintenance_mode=os.getenv("MAINTENANCE_MODE", "false").lower() == "true",
        max_requests_hour=int(os.getenv("MAX_REQUESTS_HOUR", "100")),
        session_timeout=int(os.getenv("SESSION_TIMEOUT", "30")),
    )
    
    metrics = BotMetrics()
    validators = Validators()
    
    logger.info(f"✅ Core initialized - Maintenance: {config.maintenance_mode}")
    
    return config, validators, metrics

# =====================================================
# Exports
# =====================================================
__all__ = [
    'UserState', 'OrderStatus', 'ComplaintType',
    'BotConfig', 'BotMetrics', 'Validators',
    'WORKFLOW_STEPS', 'STEP_PROGRESS', 'STEP_ICONS',
    'STATUS_TEXT', 'COMPLAINT_TYPE_MAP', 'MESSAGES',
    'get_step_display', 'calculate_progress', 
    'generate_progress_bar', 'get_status_info',
    'initialize_core'
]
