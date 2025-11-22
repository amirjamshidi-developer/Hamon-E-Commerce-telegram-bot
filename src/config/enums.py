""" Centralized enumerations for type safety and consistency """
from enum import Enum, IntEnum, auto
from typing import Dict, Any

class UserState(Enum):
    """User session states with helper methods"""
    IDLE = auto()
    RATE_LIMITED = auto()
    WAITING_NATIONAL_ID = auto()  
    AUTHENTICATED = auto()
    WAITING_ORDER_NUMBER = auto()
    WAITING_SERIAL = auto()
    WAITING_COMPLAINT_TYPE = auto()
    WAITING_COMPLAINT_TEXT = auto()
    WAITING_REPAIR_DESC = auto()

    def is_waiting(self) -> bool:
        """Check if state is waiting for input"""
        return self.name.startswith('WAITING_')

    def is_authenticated(self) -> bool:
        """Check if user is authenticated"""
        return self == self.AUTHENTICATED

    def requires_auth(self) -> bool:
        """Check if state requires authentication"""
        return self in {
            self.WAITING_COMPLAINT_TYPE,
            self.WAITING_COMPLAINT_TEXT,
            self.WAITING_REPAIR_DESC
        }

class WorkflowSteps(IntEnum):
    """ Order workflow steps as integers - It encapsulates state values, display metadata, and business logic."""
    ENTRY = 0         
    PRE_ACCEPTANCE = 1
    ACCEPTANCE = 2    
    REPAIR = 3        
    INVOICING = 4     
    TREASURY = 5      
    READY_TO_SHIP = 6 
    SHIPPING = 7      
    INFO_COMPLETE = 8 
    PENDING_PAYMENT = 9
    STALLED = 10      
    COMPLETED = 50    

    @property
    def display_name(self) -> str:
        """Gets the Persian display name, prioritizing dynamically set names."""
        _static_names = {
            0: "ورود مرسوله", 1: "پیش پذیرش", 2: "پذیرش", 3: "تعمیرات",
            4: "صدور صورتحساب", 5: "خزانه داری", 6: "آماده ارسال",
            7: "در حال ارسال", 8: "تکمیل اطلاعات", 9: "منتظر پرداخت",
            10: "راکد", 50: "پایان عملیات"
        }
        
        if hasattr(self.__class__, '_dynamic_names'):
            dynamic_name = self.__class__._dynamic_names.get(self.value)
            if dynamic_name is not None:
                return dynamic_name
                
        return _static_names.get(self.value, "نامشخص")

    @property
    def progress(self) -> int:
        """Gets the progress percentage (0-100) for this step."""
        _progress_map = {
            0: 0, 1: 10, 2: 20, 3: 35, 4: 50, 
            5: 60, 6: 70, 7: 80, 8: 85, 9: 90,
            10: 95, 50: 100
        }
        return _progress_map.get(self.value, 0)

    @property
    def icon(self) -> str:
        """Gets the representative emoji icon for this step."""
        _icons = {
            0: "📥", 1: "📝", 2: "✅", 3: "🔧", 4: "📄",
            5: "💰", 6: "📦", 7: "🚚", 8: "📋", 9: "⏳",
            10: "⏸️", 50: "✔️"
        }
        return _icons.get(self.value, "📍")
    
    def get_emoji_progress_bar(self, width: int = 10) -> str:
        """Generates an emoji-based progress bar string."""
        filled_count = int((self.progress / 100) * width)
        return "🔵" * filled_count + "⚪" * (width - filled_count)

    def is_active(self) -> bool:
        """Checks if the order is in an active, non-terminal state."""
        return 0 <= self.value < 50
    
    def is_completed(self) -> bool:
        """Checks if the order is in the completed state."""
        return self.value == self.COMPLETED
    
    def is_stalled(self) -> bool:
        """Checks if the order is in a stalled state."""
        return self.value == self.STALLED
    
    def is_payable(self) -> bool:
        """Checks if payment is expected or possible at this step."""
        return self in {self.INVOICING, self.PENDING_PAYMENT, self.READY_TO_SHIP}

    def can_edit(self) -> bool:
        """Checks if order details can still be edited by the user."""
        return self.value < self.REPAIR  # e.g., only before repair stage

    @classmethod
    def get_step_info(cls, step_value: int) -> Dict[str, Any]:
        """Factory method to get a complete information dictionary from a raw integer."""
        try:
            workflow_step = cls(step_value)
            return {
                'step_obj': workflow_step,
                'name': workflow_step.display_name,
                'icon': workflow_step.icon,
                'progress': workflow_step.progress,
                'bar': workflow_step.get_emoji_progress_bar(),
                'display': f"{workflow_step.icon} {workflow_step.display_name}"
            }
        except ValueError:
            return {
                'step_obj': None,
                'name': 'نامشخص', 'icon': '❓', 'progress': 0,
                'bar': "⚪" * 10,
                'display': "❓ نامشخص"
            }

    @classmethod
    def update_display_names(cls, names: Dict[int, str]):
        """Dynamically updates or overrides the display names for workflow steps."""
        if not hasattr(cls, '_dynamic_names'):
            cls._dynamic_names = {}
        cls._dynamic_names.update(names)

class ComplaintType(Enum):
    """Categorized complaint types with GUID ↔ Unit mapping."""
    DEVICE_ISSUE = (1, "device_issue", "🔧 خرابی و تعمیرات دستگاه")
    SHIPPING     = (2, "shipping",     "🚚 ارسال و دریافت دستگاه")
    FINANCIAL    = (3, "financial",    "💰 بخش مالی و حسابداری")
    PERSONNEL    = (4, "personnel",    "👤 پشتیبانی و رفتار پرسنل")
    SALES        = (5, "sales",        "📈 بخش فروش و توسعه بازار")
    OTHER        = (6, "other",        "📝 سایر موارد")

    def __init__(self, type_id: int, code: str, label: str):
        self.id = type_id
        self.code = code
        self.display = label

    @classmethod
    def get_keyboard_options(cls) -> list[dict]:
        """List options for Telegram inline keyboard."""
        return [{"text": ct.display, "type_id": ct.id} for ct in cls]

    @classmethod
    def from_id(cls, type_id: int) -> "ComplaintType":
        for c in cls:
            if c.id == type_id:
                return c
        raise ValueError(f"Invalid ComplaintType ID: {type_id}")

    @classmethod
    def map_to_server(cls, type_id: int) -> Dict[str, Any]:
        """Return corresponding GUID + unit mapping for C# endpoint payload."""
        mapping = {
            1: {"subject_guid": "b97cc769-1743-4d1b-921a-533f2029fcd7", "unit": 2},  # DEVICE_ISSUE
            2: {"subject_guid": "66d2e05e-3a4f-4729-b28a-20688366eacd", "unit": 3},  # SHIPPING
            3: {"subject_guid": "1c8d9167-ad1f-4a96-ad46-c9e07c7152ac", "unit": 4},  # FINANCIAL
            4: {"subject_guid": "9419941c-bc73-4dab-9169-11651517e151", "unit": 3},  # PERSONNEL
            5: {"subject_guid": "20e10aee-87ec-47c9-b1ce-a9e5b3ae369f", "unit": 1},  # SALES
            6: {"subject_guid": "d369c193-95ce-4d7b-8028-7d961c339f28", "unit": 0},  # OTHER
        }
        return mapping.get(type_id) or {"subject_guid": None, "unit": 0}

class DeviceStatus(IntEnum):
    """Device repair status tracking"""
    REGISTERED = 0
    WAITING = 1
    INITIAL_TEST = 2
    REPAIRING = 3
    FINAL_TEST = 4
    INVOICED = 5
    COMPLETED = 50

    @property
    def display_name(self) -> str:
        names = {
            0: "ثبت اولیه",
            1: "پذیرش",
            2: "تست اولیه",
            3: "در حال تعمیر",
            4: "تست نهایی",
            5: "صورتحساب",
            50: "تکمیل"
        }
        return names.get(self.value, "نامشخص")

    @property
    def icon(self) -> str:
        icons = {
            0: "📝",
            1: "📋",
            2: "🔍",
            3: "🔧",
            4: "🧪",
            5: "📄",
            50: "✅"
        }
        return icons.get(self.value, "❓")

    @classmethod
    def get_display(cls, value: int | str) -> str:
        """Safely resolve numeric or Persian textual status into 'icon name'."""
        if value is None:
            return "❓ نامشخص"
    
        try:
            v = int(value)
            status = cls(v)
            return f" {status.display_name} {status.icon}"
        except (ValueError, TypeError):
            pass

        if isinstance(value, str):
            name_to_code = {
                "ثبت اولیه": 0,
                "در انتظار": 1,
                "تست اولیه": 2,
                "در حال تعمیر": 3,
                "تست نهایی": 4,
                "صورتحساب": 5,
                "تکمیل": 50,
            }
            code = name_to_code.get(value.strip())
            if code is not None:
                status = cls(code)
                return f"{status.icon} {status.display_name}"

        return "❓ نامشخص"
