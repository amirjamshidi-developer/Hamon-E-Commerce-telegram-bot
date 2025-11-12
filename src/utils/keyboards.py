"""
Centralized, dynamic, and consistent keyboard generation factory for Aiogram 3.
Ensures a strict separation between Inline and Reply keyboard types.
"""
from typing import Optional, Any
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from src.config.callbacks import MenuCallback, AuthCallback, OrderCallback, ServiceCallback, TrackCallback
from src.config.enums import ComplaintType
from src.models.user import UserSession
from src.utils.messages import get_message

class KeyboardFactory:
    """A factory for creating standardized Telegram keyboards with a clear distinction between Inline and Reply types."""

    @staticmethod
    def main_inline_menu(is_auth: Optional[bool] = False) -> InlineKeyboardMarkup:
        """Generates the main inline menu, dynamically adjusting for auth status."""
        builder = InlineKeyboardBuilder()
        if is_auth:
            builder.row(
                InlineKeyboardButton(text="👤 اطلاعات حساب کاربری", callback_data=AuthCallback(action="my_info").pack()),
                InlineKeyboardButton(text="📦 لیست سفارشات ", callback_data=OrderCallback(action="orders_list").pack())
            )
            builder.row(
                InlineKeyboardButton(text="📝 ثبت شکایات/نظرات", callback_data=ServiceCallback(action="complaint_start").pack()),
                InlineKeyboardButton(text="📞 درخواست تعمیر", callback_data=ServiceCallback(action="repair_start").pack())
            )
            builder.row(
                InlineKeyboardButton(text="❓ راهنما", callback_data=MenuCallback(target="help").pack()),
                InlineKeyboardButton(text="🚪 خروج از حساب", callback_data=AuthCallback(action="logout_prompt").pack())
                )
        else:
            builder.row(InlineKeyboardButton(text="🔐 ورود با کد/شناسه ملی", callback_data=AuthCallback(action="start").pack()))
            builder.row(
                InlineKeyboardButton(text="🔢 پیگیری شماره", callback_data=TrackCallback(action="prompt_number").pack()),
                InlineKeyboardButton(text="#️⃣ پیگیری سریال", callback_data=TrackCallback(action="prompt_serial").pack())
            )
            builder.row(InlineKeyboardButton(text="❓ راهنما", callback_data=MenuCallback(target="help").pack()))
        return builder.as_markup()

    @staticmethod
    def order_actions(order_number: str, order, extra_buttons: Optional[Any] = None) -> InlineKeyboardMarkup:
        """Generates actions for a specific order (Refresh, Pay)."""

        builder = InlineKeyboardBuilder()

        if order.has_payment_link:
            text = "📄 مشاهده فاکتور پرداخت" if order.is_paid else "💳 مشاهده و پرداخت فاکتور"
            builder.row(InlineKeyboardButton(text=text, url=order.payment_link))
        
        builder.row(InlineKeyboardButton(
            text = get_message('refresh_order'), 
            callback_data=OrderCallback(action="refresh", order_number=order_number).pack()
        ))

        if extra_buttons:
            for btn in extra_buttons:
                builder.row(InlineKeyboardButton(text=btn['text'], callback_data=btn['callback']))

        builder.row(InlineKeyboardButton(text=get_message('cancel_text'),
        callback_data=MenuCallback(target="main_menu").pack()))

        return builder.as_markup()

    @staticmethod
    def device_list_actions(order_number: str, page: int, total_pages: int) -> InlineKeyboardMarkup:
        """Keyboard for the dedicated, paginated device list view - Includes Start, Prev, Next, End, and Back to Order Details."""
        builder = InlineKeyboardBuilder()

        if total_pages > 1:
            nav_row = [InlineKeyboardButton(text=f"📄 {page}/{total_pages}", callback_data="noop")]

            if page > 1:
                nav_row.insert(0, InlineKeyboardButton(
                    text="⏪ اول",
                    callback_data=OrderCallback(action="devices_list", order_number=order_number, page=1).pack()
                ))
                nav_row.insert(1, InlineKeyboardButton(
                    text="◀️ قبل",
                    callback_data=OrderCallback(action="devices_list", order_number=order_number, page=page - 1).pack()
                ))

            if page < total_pages:
                nav_row.append(InlineKeyboardButton(
                    text="بعدی ▶️",
                    callback_data=OrderCallback(action="devices_list", order_number=order_number, page=page + 1).pack()
                ))
                nav_row.append(InlineKeyboardButton(
                    text="آخر ⏩",
                    callback_data=OrderCallback(action="devices_list", order_number=order_number, page=total_pages).pack()
                ))

            builder.row(*nav_row)

        builder.row(
            InlineKeyboardButton(
                text="🔍 بازگشت به جزئیات سفارش ",
                callback_data=OrderCallback(action="order_details", order_number=order_number).pack()
            )
        )
        builder.row(
            InlineKeyboardButton(text=get_message('cancel_text'), callback_data=MenuCallback(target="main_menu").pack())
        )
        return builder.as_markup()

    @staticmethod
    def my_orders_actions(session: 'UserSession') -> InlineKeyboardMarkup:
        """Generates action buttons for the 'My Orders' summary view."""
        builder = InlineKeyboardBuilder()
        
        raw = session.temp_data.get("raw_auth_data", {})
        payment_link = raw.get("payment_link")
        factor_paid = bool(raw.get("payment") or raw.get("factorPayment"))
        order_number = session.order_number or raw.get("order_number", "")
        
        if payment_link:
            text = "🧾 مشاهده فاکتور پرداخت" if factor_paid else "💳 پرداخت فاکتور"
            builder.row(InlineKeyboardButton(text=text, url=payment_link))
            
        builder.row(InlineKeyboardButton(
            text="📋 مشاهده جزئیات سفارش",
            callback_data=OrderCallback(action="order_details", order_number=order_number).pack()
        ))
        builder.row(InlineKeyboardButton(
            text="🏠 بازگشت به منو",
            callback_data=MenuCallback(target="main_menu").pack()
        ))

        return builder.as_markup()
    
    @staticmethod
    def complaint_types_inline() -> InlineKeyboardMarkup:
        """Creates an inline keyboard for complaint category selection."""
        builder = InlineKeyboardBuilder()
        for option in ComplaintType.get_keyboard_options():
            builder.button(
                text=option["text"],
                callback_data=ServiceCallback(
                    action="select_complaint",
                    type_id=option["type_id"]
                ).pack()
            )
        builder.adjust(2)
        builder.row(
            InlineKeyboardButton(
                text=get_message("cancel_text"),
                callback_data=MenuCallback(target="main_menu").pack()
            )
        )
        return builder.as_markup()

    @staticmethod
    def single_button(text: str, callback_data: str) -> InlineKeyboardMarkup:
        """Creates an inline keyboard with a single, specific button."""
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text=text, callback_data=callback_data))
        return builder.as_markup()

    @staticmethod
    def cancel_inline() -> InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text=get_message("cancel_text"), callback_data=MenuCallback(target="main_menu").pack()))
        return builder.as_markup()

    @staticmethod
    def back_inline(is_auth: bool = False, extra_buttons: list | None = None) -> InlineKeyboardMarkup:
        """
        Context-aware Back button → always main menu.
        Extra buttons preserved.
        """
        builder = InlineKeyboardBuilder()

        if extra_buttons:
            for btn in extra_buttons:
                builder.row(InlineKeyboardButton(text=btn["text"], callback_data=btn["callback"]))

        builder.row(
            InlineKeyboardButton(
                text=get_message("cancel_text"),
                callback_data=MenuCallback(target="main_menu").pack()
            )
        )
        return builder.as_markup()

    @staticmethod
    def main_reply_menu(is_auth: Optional[bool] = False) -> ReplyKeyboardMarkup:
        """Generates the main reply keyboard based on authentication status."""
        builder = ReplyKeyboardBuilder()
        desired_buttons = {
            "👤 اطلاعات من", "📦 لیست سفارشات من",
            "📞 درخواست تعمیرات", "📝 ثبت شکایات",
            "❓ راهنما", "🚪 خروج از حساب"
        } if is_auth else {
            "🔐 ورود با کد/شناسه ملی",
            "🔢 پیگیری با شماره پذیرش", "#️⃣ پیگیری با سریال",
            "❓ راهنما"
        }
        buttons = [KeyboardButton(text=txt) for txt in desired_buttons]
        builder.add(*buttons)
        builder.adjust(2)
        return builder.as_markup(resize_keyboard=True)

    def complaint_types_reply() -> ReplyKeyboardMarkup:
        """Returns a ready reply keyboard listing all ComplaintType labels."""
        buttons = []
        row = []
        for i, ct in enumerate(ComplaintType):
            row.append(KeyboardButton(text=ct.display))
            if len(row) == 2 or i == len(ComplaintType) - 1:
                buttons.append(row)
                row = []
                
        buttons.append([KeyboardButton(text=get_message('cancel_text'))])
        return ReplyKeyboardMarkup(
            keyboard=buttons,
            resize_keyboard=True,
            one_time_keyboard=False,
            input_field_placeholder="نوع شکایت خود را انتخاب کنید..."
        )

    @staticmethod
    def cancel_reply(extra_text: str | None = None) -> ReplyKeyboardMarkup:
        """Creates a standard REPLY keyboard with a single 'Cancel' button for text input prompts."""
        builder = ReplyKeyboardBuilder()
        if extra_text:
            builder.row(KeyboardButton(text=extra_text))
        builder.add(KeyboardButton(text=get_message('cancel_text')))
        return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)

    @staticmethod
    def remove() -> ReplyKeyboardRemove:
        """Generates a command to remove the reply keyboard."""
        return ReplyKeyboardRemove()
    