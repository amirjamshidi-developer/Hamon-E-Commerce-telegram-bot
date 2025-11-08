""" Unified formatting module for all display and text formatting needs - Combines display layouts with utility formatters """
from dataclasses import dataclass
from typing import Dict, List, Any, Tuple
from src.config.enums import WorkflowSteps, DeviceStatus
from src.config.callbacks import OrderCallback
from src.models.user import UserSession
from src.utils.helpers import safe_get, get_current_jalali_date

@dataclass
class FormatConfig:
    """Centralized formatting configuration"""
    max_items_per_page: int = 5
    max_devices_preview: int = 3
    devices_per_page: int = 8
    min_text_length: int = 10
    max_text_length: int = 1000

class Formatters:
    """Atomic + structured text formatters used throughout bot"""
    
    config = FormatConfig()

    @classmethod
    def user_info(cls, session_data: Dict) -> str:
        """Format complete user profile"""
        name = safe_get(session_data, 'user_name', default='نامشخص')
        national_id = safe_get(session_data, 'nationalId', 
                    default=safe_get(session_data, 'national_id', default='نامشخص'))
        phone = safe_get(session_data, 'phone_number')
        city = safe_get(session_data, 'city', default='ثبت نشده')

        is_authenticated = safe_get(session_data, 'is_authenticated', default=False)
        auth_status = "احراز هویت شده" if is_authenticated else "عدم احراز هویت"
        last_visit = get_current_jalali_date()

        formatted_text =  f"""👤 **اطلاعات حساب کاربری**
━━━━━━━━━━━━━━━━━━━━━━

👨‍💼 **مشتری:** {name}
🌐 **کد/شناسه ملی:** `{national_id}`
📱 **شماره همراه:** `{phone}`
📍 **استان/شهر:** {city}
🔐 **وضعیت:** {auth_status}

⏰ **آخرین بازدید:** {last_visit}"""

        return formatted_text, []

    @classmethod
    def my_orders_summary(cls, session: 'UserSession') -> Tuple[str, list]:
        """Generate order summary using the cached AuthResponse/Order models."""
        auth_raw = session.temp_data.get("raw_auth_data", {})
        orders = session.last_orders or []
        
        order_number = auth_raw.get("number") or auth_raw.get("order_number")
        factor_info = auth_raw.get("factorPayment")
        payment_link = auth_raw.get("factorId_paymentLink")
        
        #total_orders = sum(len(auth_raw.get("number")))
        total_devices = sum(len(o.get("devices", [])) or 1 for o in orders)

        if factor_info:
            payment_line = f"🧾 فاکتور پرداخت شده (شماره: `{auth_raw.get('$$_factorId')}`)"
        elif payment_link:
            payment_line = f"💳 فاکتور آماده پرداخت (شماره: `{auth_raw.get('$$_factorId')}`)"
        else:
            payment_line = "⚠️ هنوز فاکتور پرداختی ثبت نشده است."

        text = (
            f"📦 **وضعیت سفارشات شما**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔢 شماره پذیرش شما: `{order_number}`\n"
            #f"📋 تعداد سفارش‌ها: {total_orders}\n"
            f"📱 تعداد کل دستگاه‌ها: {total_devices}\n\n"
            f"{payment_line}\n"
        )
        return text.strip(), []

    @classmethod
    def order_list(cls, orders: List[Dict], page: int = 1) -> str:
        """ Format paginated orders list """
        if not orders:
            return "📦 **سفارشات شما**\n\nهیچ سفارشی یافت نشد."
        
        per_page = cls.config.max_items_per_page
        total_pages = max(1, (len(orders) + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        start, end = (page - 1) * per_page, min(page * per_page, len(orders))
        display_orders = orders[start:end]
        
        total_devices = sum(len(order.get('devices', [])) for order in orders)
        total_orders = len(orders)
        text = f"📦 *سفارشات شما* (مجموع: {total_orders})\nصفحه {page}/{total_pages}\n\n"
        text += f"تعداد دستگاه‌های شما: {total_devices}\n"

        for i, order in enumerate(display_orders, start=start + 1):
            order_num = order.get('order_number', '---')
            step = order.get('steps', 0)
            step_info = WorkflowSteps.get_step_info(step)
            text += f"{i}. **شماره پذیرش:**  `{order_num}`\n"
            text += f"📊 **وضعیت کلی سفارش:**\n {step_info['name']} {step_info['icon']} \n"
            text += f"{step_info['bar']} % {step_info['progress']}\n\n"
        return text
    
    @classmethod
    def order_detail(cls, order: Dict[str, Any], is_auth: bool = False) -> Tuple[str, List]:
        """Format detailed customer's order information."""
        if not order:
            return "❌ اطلاعات سفارش یافت نشد",[]       
        
        order_number = safe_get(order, "order_number", default="---")
        tracking_code = safe_get(order, "tracking_code", default="---")
        current_step = safe_get(order, "current_step", default=0)
        step_info = WorkflowSteps.get_step_info(current_step)
        registration_date = safe_get(order, "registration_date", default="نامشخص")
        last_visit = get_current_jalali_date()

        devices = safe_get(order, "devices", default=[])
        total_devices = len(devices)
        preview_count = cls.config.max_devices_preview
        visible_devices = devices[:preview_count]

        device_text = ""
        if total_devices <= 0:
            device_text = "📱 هیچ دستگاهی ثبت نشده است."
        elif total_devices == 1:
            dev = devices[0]
            model = safe_get(dev, "model", default="نامشخص")
            serial = safe_get(dev, "serial", default="---")
            status_raw = safe_get(dev, "status_code") or safe_get(dev, "status", default=0)
            device_status = DeviceStatus.get_display(status_raw)
            device_text += (
                f"**📱 مشخصات دستگاه:**\n"
                f"- مدل: {model}\n"
                f"- سریال: `{serial}`\n"
                f"- وضعیت: {device_status}\n\n"
            )
        else:
            device_text += f"📱 تعداد کل دستگاه‌ها: {total_devices}\n\n"
            for i, dev in enumerate(visible_devices, start=1):
                model = safe_get(dev, "model", default="نامشخص")
                serial = safe_get(dev, "serial", default="---")
                status_raw = safe_get(dev, "status_code") or safe_get(dev, "status", default=0)
                device_status = DeviceStatus.get_display(status_raw)
                device_text += f"**دستگاه {i}:**\n- مدل: {model}\n- سریال: `{serial}`\n- وضعیت: {device_status}\n\n"

            if total_devices > preview_count:
                device_text += f"و {total_devices - preview_count} دستگاه دیگر ...\n"

        payment = safe_get(order, "payment")
        payment_caption = ""
        if payment and payment.get("payment_link"):
            invoice = payment.get("invoice_id") or "نامشخص"
            if payment.get("payment_completed"):
                payment_caption = f"🧾 فاکتور پرداخت شده (شماره فاکتور: {invoice})\n"
            else:
                payment_caption = f"💳 فاکتور قابل پرداخت (شماره فاکتور: {invoice})\n"
            
        formatted_text = (
            f"📋 **جزئیات سفارش**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔢 شماره پذیرش: `{order_number}`\n"
            f"🗂 کد رهگیری پذیرش: `{tracking_code}`\n"
            f"📅 تاریخ ثبت انبار: {registration_date}\n\n"
            f"📊 **وضعیت کلی سفارش:**\n {step_info['name']} {step_info['icon']} \n{step_info['bar']} % {step_info['progress']}\n\n"
            f"{device_text}\n"
            f"{payment_caption}"
            f"\n⏰ **آخرین بازدید:** {last_visit}"
        )   
            
        extra_buttons = []
        if total_devices > preview_count:
            extra_buttons.append({
                    "text": "🔍 مشاهده لیست کامل دستگاه‌ها",
                    "callback":  OrderCallback(
                    action="devices_list", 
                    order_number=order_number, 
                    page=1
                ).pack()
                })
            
        if is_auth:
            extra_buttons.append({
                "text": "🔙 بازگشت به سفارش‌های من",
                "callback": OrderCallback(action="orders_list").pack()
            })

        return formatted_text, extra_buttons

    @classmethod
    def device_list_paginated(cls, order: Dict[str, Any], page: int = 1) -> str:
        """Formats a dedicated, paginated list of devices for an order - Shows 8 devices per page."""
        order_number = safe_get(order, "order_number", default="---")
        devices = safe_get(order, "devices", default=[])
        total_devices = len(devices)

        if total_devices == 0:
            return "📱 هیچ دستگاهی برای این سفارش ثبت نشده است."

        per_page = cls.config.devices_per_page
        total_pages = max(1, (total_devices + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))

        start_index = (page - 1) * per_page
        end_index = start_index + per_page
        visible_devices = devices[start_index:end_index]

        text = (
            f"📱 **لیست دستگاه‌های سفارش `{order_number}`**\n"
            f"صفحه {page}/{total_pages} (نمایش {start_index + 1} تا {min(end_index, total_devices)} از {total_devices})\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        )

        for i, dev in enumerate(visible_devices, start=start_index + 1):
            model = safe_get(dev, "model", default="نامشخص")
            serial = safe_get(dev, "serial", default="---")
            status_raw = safe_get(dev, "status_code") or safe_get(dev, "status", default=0)
            device_status = DeviceStatus.get_display(status_raw)

            text += (
                f"**دستگاه {i}:**\n"
                f"- مدل: {model}\n"
                f"- سریال: `{serial}`\n"
                f"- وضعیت: {device_status}\n\n"
            )
        return text

    @classmethod
    def complaint_submitted(cls, ticket_number: str, complaint_type: str) -> str:
        """Formats the complaint submission confirmation message."""
        date = get_current_jalali_date()
        return (
            f"✅ **شکایت شما با موفقیت ثبت شد**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎫 **شماره پیگیری درخواست(تیکت):** `{ticket_number}`\n"
            f"📌 **نوع شکایت:** {complaint_type}\n"
            f"📅 **تاریخ ثبت:** {date}\n\n"
            f"همکاران ما در اسرع وقت به درخواست شما رسیدگی خواهند کرد."
        )

    @classmethod
    def repair_submitted(cls, ticket_number: str) -> str:
        """Formats the repair request submission confirmation message."""
        date = get_current_jalali_date()
        return (
            f"✅ **درخواست تعمیر شما با موفقیت ثبت شد**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎫 **شماره پیگیری درخواست(تیکت):** `{ticket_number}`\n"
            f"📅 **تاریخ ثبت:** {date}\n\n"
            f"نتیجه بررسی و هماهنگی‌های بعدی به شما اطلاع‌رسانی خواهد شد."
        )
