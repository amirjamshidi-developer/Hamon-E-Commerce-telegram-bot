"""
Callback Handler - Handles all inline keyboard interactions
"""
import logging
import asyncio
from typing import Optional, Dict, Any
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from telegram.constants import ParseMode
from telegram.error import BadRequest

from .CoreConfig import (
    UserState, ComplaintType, CallbackFormats, MESSAGES, WORKFLOW_STEPS,
    STEP_ICONS, STEP_PROGRESS, MAIN_INLINE_KEYBOARD, MAIN_REPLY_KEYBOARD,
    get_step_display, get_step_info, COMPLAINT_TYPE_MAP
)
from .SessionManager import RedisSessionManager
from .DataProvider import DataProvider

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .MessageHandler import MessageHandler

logger = logging.getLogger(__name__)

class CallbackHandler:
    """Handles all callback queries from inline keyboards"""
    
    def __init__(self, message_handler: "MessageHandler", session_manager: RedisSessionManager, data_provider: DataProvider):
        """Match main.py expectations - NO bot/config required"""
        self.msg = message_handler  # Reference to MessageHandler
        self.sessions = session_manager
        self.data = data_provider
        self.ORDERS_PER_PAGE = 5

    async def handle_callback(self, update: Update):
        """Main callback router - handles all button clicks"""
        query: Optional[CallbackQuery] = update.callback_query
        if not query or not query.data:
            return

        # Answer callback immediately
        try:
            await query.answer()
        except BadRequest as e:
            if "query is too old" in str(e).lower():
                logger.debug("Ignoring old callback query")
                return
            raise e

        user_id = query.from_user.id
        chat_id = query.message.chat.id
        message_id = query.message.message_id
        data = query.data

        logger.info(f"Callback '{data}' from user {user_id} in chat {chat_id}")

        try:
            async with self.sessions.session(chat_id) as session:
                session.temp_data["last_bot_message_id"] = message_id

                # Route to specific handlers
                await self._route_callback(query, chat_id, message_id, data, session)

        except Exception as e:
            logger.error(f"Callback error [{data}]: {e}", exc_info=True)
            try:
                await query.answer("❌ خطایی رخ داد", show_alert=True)
                await self._show_error(chat_id, message_id)
            except:
                pass

    async def _route_callback(
        self, query: CallbackQuery, chat_id: int, message_id: int, data: str, session
    ):
        """Route callbacks to appropriate handlers"""

        if data in [CallbackFormats.MAIN_MENU, "main_menu"]:
            await self.handle_main_menu(chat_id, message_id, session)
        elif data in [CallbackFormats.BACK, "back"]:
            await self.handle_back(chat_id, message_id, session)
        elif data in [CallbackFormats.CANCEL, "cancel"]:
            await self.handle_cancel(chat_id, message_id, session)
        elif data in [CallbackFormats.AUTHENTICATE, "authenticate"]:
            await self.handle_authenticate(chat_id, message_id, session)
        elif data in [CallbackFormats.LOGOUT, "logout"]:
            await self.handle_logout(chat_id, message_id, session)
        elif data in [CallbackFormats.MY_INFO, "my_info"]:
            await self.handle_my_info(chat_id, message_id, session)
        elif data in [CallbackFormats.MY_ORDERS, "my_orders"]:
            await self.handle_my_orders(chat_id, message_id, session, page=1)
        elif data in [CallbackFormats.TRACK_BY_NUMBER, "track_by_number"]:
            await self.handle_track_by_number(chat_id, message_id, session)
        elif data in [CallbackFormats.TRACK_BY_SERIAL, "track_by_serial"]:
            await self.handle_track_by_serial(chat_id, message_id, session)
        elif data in [CallbackFormats.REPAIR_REQUEST, "repair_request"]:
            await self.handle_repair_request(chat_id, message_id, session)
        elif data in [CallbackFormats.SUBMIT_COMPLAINT, "submit_complaint"]:
            await self.handle_submit_complaint(chat_id, message_id, session)
        elif data.startswith("complaint_"):
            await self.handle_complaint_type(chat_id, message_id, data, session)
        elif data.startswith("my_orders_page_"):
            page = self._extract_page_number(data)
            await self.handle_my_orders(chat_id, message_id, session, page)
        elif data.startswith("order_"):
            order_number = self._extract_order_number(data)
            await self.handle_order_details(chat_id, message_id, order_number, session)
        elif data.startswith("refresh_order:"):
            order_number = data.split(":", 1)[1]
            await self.handle_refresh_order(chat_id, message_id, order_number, session)
        elif data.startswith("devices_"):
            order_number = self._extract_order_number(data)
            await self.handle_devices_list(
                chat_id, message_id, order_number, session, page=1
            )
        elif data.startswith("page_") and "devices" in data:
            page, order_number = self._extract_device_page(data)
            await self.handle_devices_list(
                chat_id, message_id, order_number, session, page
            )
        elif data in [CallbackFormats.HELP, "help"]:
            await self.handle_help(chat_id, message_id, session)
        elif data in [CallbackFormats.NOOP, "noop"]:
            pass
        else:
            logger.warning(f"Unhandled callback data: {data}")
            await self._show_error(chat_id, message_id, "عملیات نامشخص")

    # ========== UTILITY METHODS ==========
    def _extract_page_number(self, data: str) -> int:
        """Extract page number from callback data"""
        try:
            return int(data.replace("my_orders_page_", ""))
        except:
            return 1

    def _extract_order_number(self, data: str) -> str:
        """Extract order number from callback data"""
        try:
            return data.replace("order_", "")
        except:
            return ""

    def _extract_device_page(self, data: str) -> tuple:
        """Extract page and order from device pagination data"""
        try:
            parts = data.replace("page_", "").split("_devices_")
            page = int(parts[0])
            order_number = parts[1]
            return page, order_number
        except:
            return 1, ""

    async def _show_error(self, chat_id: int, message_id: int, error_msg: str = None):
        """Show error message with back button"""
        text = error_msg or "❌ خطایی رخ داد"
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 بازگشت", callback_data=CallbackFormats.MAIN_MENU)
        ]])

        try:
            await self.msg.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=keyboard
            )
        except Exception as e:
            logger.error(f"Error showing error message: {e}")

    # ========== MENU HANDLERS ==========
    async def handle_main_menu(self, chat_id: int, message_id: int, session):
        """Show main menu based on authentication"""
        is_authenticated = session.is_authenticated and bool(session.nationalId)
        
        if is_authenticated:
            name = session.user_name or "کاربر"
            text = f"👋 سلام {name} عزیز!\n\n📋 پنل کاربری - انتخاب کنید:"
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("👤 اطلاعات من", callback_data="my_info")],
                [InlineKeyboardButton("📦 سفارشات من", callback_data="my_orders")],
                [InlineKeyboardButton("🔢 پیگیری سفارش", callback_data="track_by_number"),
                 InlineKeyboardButton("🔍 پیگیری سریال", callback_data="track_by_serial")],
                [InlineKeyboardButton("🔧 درخواست تعمیر", callback_data="repair_request")],
                [InlineKeyboardButton("📝 ثبت شکایت", callback_data="submit_complaint")],
                [InlineKeyboardButton("🚪 خروج", callback_data="logout")]
            ])
        else:
            text = "🏠 منوی اصلی\n\nلطفاً یک گزینه را انتخاب کنید:"
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔐 ورود", callback_data="authenticate")],
                [InlineKeyboardButton("🔢 پیگیری سفارش", callback_data="track_by_number"),
                 InlineKeyboardButton("🔍 پیگیری سریال", callback_data="track_by_serial")],
                [InlineKeyboardButton("❓ راهنما", callback_data="help")]
            ])

        try:
            await self.msg.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML
            )
            await self.msg.activate_main_keyboard(chat_id)
        except Exception as e:
            if "message is not modified" not in str(e).lower():
                logger.error(f"Error editing main menu: {e}")

    async def handle_back(self, chat_id: int, message_id: int, session):
        """Handle back navigation"""
        await self.handle_main_menu(chat_id, message_id, session)

    async def handle_cancel(self, chat_id: int, message_id: int, session):
        """Handle cancel operation"""
        session.state = UserState.IDLE if not session.is_authenticated else UserState.AUTHENTICATED
        session.temp_data.clear()
        await self.handle_main_menu(chat_id, message_id, session)

    # ========== AUTHENTICATION ==========
    async def handle_authenticate(self, chat_id: int, message_id: int, session):
        """Initiate authentication"""
        if session.is_authenticated:
            await self.handle_main_menu(chat_id, message_id, session)
            return

        session.state = UserState.WAITING_nationalId
        text = MESSAGES.get('auth_request', "🔐 لطفاً کد ملی ۱۰ رقمی را وارد کنید:")
        
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")
        ]])

        await self.msg.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN
        )
        await self.msg.activate_cancel_keyboard(chat_id)

    async def handle_logout(self, chat_id: int, message_id: int, session):
        """Handle logout"""
        session.is_authenticated = False
        session.nationalId = None
        session.user_name = None
        session.state = UserState.IDLE
        session.temp_data.clear()

        text = "✅ با موفقیت خارج شدید"
        keyboard = InlineKeyboardMarkup(MAIN_INLINE_KEYBOARD)

        await self.msg.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=keyboard
        )
        await self.msg.activate_main_keyboard(chat_id)

    # ========== ORDER TRACKING ==========
    async def handle_track_by_number(self, chat_id: int, message_id: int, session):
        """Start order number tracking"""
        session.state = UserState.WAITING_ORDER_NUMBER
        text = "🔢 لطفاً شماره پذیرش را وارد کنید:"
        
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")
        ]])

        await self.msg.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=keyboard
        )
        await self.msg.activate_cancel_keyboard(chat_id)

    async def handle_track_by_serial(self, chat_id: int, message_id: int, session):
        """Start serial number tracking"""
        session.state = UserState.WAITING_SERIAL
        text = "#️⃣ لطفاً شماره سریال دستگاه را وارد کنید:"
        
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")
        ]])

        await self.msg.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=keyboard
        )
        await self.msg.activate_cancel_keyboard(chat_id)

    async def handle_order_details(self, chat_id: int, message_id: int, order_number: str, session):
        """Show order details - USE MessageHandler method"""
        # Show loading
        await self.msg.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text="🔄 در حال دریافت جزئیات..."
        )

        # Fetch order data
        order_data = await self.data.get_order_by_number(order_number)
        
        # Use MessageHandler's display method (clean separation)
        await self.msg.display_order_details(chat_id, order_data, message_id)

    async def handle_refresh_order(self, chat_id: int, message_id: int, order_number: str, session):
        """Refresh order status - SIMPLIFIED"""
        try:
            # Show loading
            await self.msg.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text="🔄 در حال بروزرسانی..."
            )

            # Fetch fresh data
            order_data = await self.data.get_order_by_number(order_number, force_refresh=True)
            
            if not order_data or isinstance(order_data, dict) and "error" in order_data:
                error_text = order_data.get("error", "❌ خطا در بروزرسانی")
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 منوی اصلی", callback_data="main_menu")]
                ])
                
                await self.msg.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=error_text,
                    reply_markup=keyboard
                )
                return

            # Extract status info safely (DICTIONARY ACCESS)
            steps = order_data.get("steps", 0)
            current_step = WORKFLOW_STEPS.get(steps, f"مرحله {steps}")
            progress = STEP_PROGRESS.get(steps, 0)
            status_icon = STEP_ICONS.get(steps, "📍")
            order_number = order_data.get("order_number", order_number)

            # Simple success message
            text = f"""✅ **سفارش بروزرسانی شد**

**شماره:** `{order_number}`
**وضعیت:** {status_icon} {current_step}
**پیشرفت:** {progress}%

⏰ زمان: {datetime.now().strftime('%H:%M:%S')}"""

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("👁️ جزئیات", callback_data=f"order_{order_number}")],
                [InlineKeyboardButton("🔙 منوی اصلی", callback_data="main_menu")]
            ])

            await self.msg.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=keyboard,
                parse_mode=ParseMode.MARKDOWN
            )

        except Exception as e:
            logger.error(f"Refresh error: {e}", exc_info=True)
            await self._show_error(chat_id, message_id, "❌ خطا در بروزرسانی")

    # ========== MY ORDERS - FIXED PYLANCE ERROR ==========
    async def handle_my_orders(self, chat_id: int, message_id: int, session, page: int = 1):
        """Show user's orders - FIXED: No query reference"""
        try:
            if not session.is_authenticated or not session.nationalId:
                # FIXED: Use MessageHandler's send method instead of query.answer
                await self.msg.send_message(
                    chat_id, 
                    "⚠️ ابتدا وارد حساب کاربری شوید", 
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔐 ورود", callback_data="authenticate")],
                        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="main_menu")]
                    ]),
                    activate_keyboard=True
                )
                return

            # Show loading
            if message_id:
                await self.msg.bot.edit_message_text(
                    chat_id=chat_id, 
                    message_id=message_id, 
                    text="🔄 در حال بارگذاری سفارشات..."
                )

            # Fetch orders
            orders_data = await self.data.get_user_orders(session.nationalId)
            
            if not orders_data or "error" in orders_data:
                text = "📦 **سفارشات شما**\n\nهیچ سفارشی یافت نشد."
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 منوی اصلی", callback_data="main_menu")]
                ])
            else:
                # Simple display (first 5 orders)
                orders = orders_data if isinstance(orders_data, list) else [orders_data]
                
                text = "📦 **سفارشات شما**\n\n"
                if len(orders) == 0:
                    text += "هیچ سفارشی یافت نشد."
                else:
                    for i, order in enumerate(orders[:5], 1):
                        steps = order.get("steps", 0)  # SAFE dictionary access
                        status_icon = STEP_ICONS.get(steps, "📍")
                        order_num = order.get("order_number", "نامشخص")
                        
                        text += f"{i}. {status_icon} `{order_num}`\n"
                        
                        if "registration_date" in order:
                            reg_date = order.get("registration_date", "---")
                            if " " in reg_date:
                                reg_date = reg_date.split(" ")[0]
                            text += f"   📅 {reg_date}\n"
                        text += "\n"

                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 بارگذاری مجدد", callback_data="my_orders")],
                    [InlineKeyboardButton("🔙 منوی اصلی", callback_data="main_menu")]
                ])

            if message_id:
                await self.msg.bot.edit_message_text(
                    chat_id=chat_id, 
                    message_id=message_id, 
                    text=text, 
                    reply_markup=keyboard,
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await self.msg.send_message(chat_id, text, reply_markup=keyboard)

        except Exception as e:
            logger.error(f"My orders error: {e}")
            await self.msg.send_message(
                chat_id, "❌ خطا در بارگذاری سفارشات", 
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 منوی اصلی", callback_data="main_menu")]
                ])
            )

    # ========== COMPLAINTS - FIXED PYLANCE ERROR ==========
    async def handle_submit_complaint(self, chat_id: int, message_id: int, session):
        """Handle complaint submission flow - FIXED: No query reference"""
        try:
            if not session.is_authenticated:
                # FIXED: Use MessageHandler's send method instead of query.answer
                await self.msg.send_message(
                    chat_id, 
                    "⚠️ ابتدا وارد حساب کاربری شوید", 
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔐 ورود", callback_data="authenticate")],
                        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="main_menu")]
                    ]),
                    activate_keyboard=True
                )
                return

            # Set state for complaint type selection
            session.state = UserState.WAITING_COMPLAINT_TYPE  # Add this to UserState enum if needed
            text = "📝 **ثبت شکایت**\n\nنوع مشکل را انتخاب کنید:"

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("⚠️ تاخیر در تحویل", callback_data="complaint:delay")],
                [InlineKeyboardButton("🔧 مشکل فنی", callback_data="complaint:technical")],
                [InlineKeyboardButton("📦 مشکل بسته‌بندی", callback_data="complaint:packaging")],
                [InlineKeyboardButton("💰 مشکل پرداخت", callback_data="complaint:payment")],
                [InlineKeyboardButton("📞 پشتیبانی", callback_data="complaint:support")],
                [InlineKeyboardButton("🔙 انصراف", callback_data="main_menu")]
            ])

            if message_id:
                await self.msg.bot.edit_message_text(
                    chat_id=chat_id, 
                    message_id=message_id, 
                    text=text, 
                    reply_markup=keyboard,
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await self.msg.send_message(chat_id, text, reply_markup=keyboard)

        except Exception as e:
            logger.error(f"Submit complaint error: {e}")
            await self._show_error(chat_id, message_id, "❌ خطا در ثبت شکایت")

    async def handle_complaint_type(self, chat_id: int, message_id: int, data: str, session):
        """Handle complaint type selection"""
        complaint_type = data.replace("complaint:", "")
        session.state = UserState.WAITING_COMPLAINT_TEXT
        session.temp_data['complaint_type'] = complaint_type
        
        text = f"📝 **{COMPLAINT_TYPE_MAP.get(complaint_type, 'شکایت')}\n\nلطفاً متن شکایت خود را بنویسید:"
        
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 انصراف", callback_data="main_menu")
        ]])

        await self.msg.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN
        )
        await self.msg.activate_cancel_keyboard(chat_id)

    # ========== REPAIR REQUESTS ==========
    async def handle_repair_request(self, chat_id: int, message_id: int, session):
        """Handle repair request"""
        if not session.is_authenticated:
            await self.msg.send_message(
                chat_id, 
                "⚠️ ابتدا وارد حساب کاربری شوید", 
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔐 ورود", callback_data="authenticate")]
                ])
            )
            return

        session.state = UserState.WAITING_REPAIR_DESC
        text = "🔧 **درخواست تعمیر**\n\nلطفاً مشکل دستگاه خود را شرح دهید:"
        
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 انصراف", callback_data="main_menu")
        ]])

        await self.msg.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN
        )
        await self.msg.activate_cancel_keyboard(chat_id)

    # ========== OTHER HANDLERS ==========
    async def handle_my_info(self, chat_id: int, message_id: int, session):
        """Show complete user information"""
        if not session.is_authenticated:
            await self._show_error(chat_id, message_id, "⚠️ ابتدا وارد حساب کاربری شوید")
            return

        # Get all user data from session
        name = session.user_name or 'نامشخص'
        national_id = session.nationalId or 'نامشخص'
        phone = session.phone_number or 'ثبت نشده'
        city = session.city or 'ثبت نشده'
        
        text = f"""👥 **اطلاعات کاربری**

     **نام:** {name}
     **کد ملی:** {national_id}
     **شماره همراه:** {phone}
     **شهر/استان:** {city}
     **وضعیت:** احراز هویت شده ✅

    📞 برای بروزرسانی اطلاعات با پشتیبانی تماس بگیرید."""
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 منوی اصلی", callback_data="main_menu")]
        ])

        await self.msg.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN
        )


    async def handle_help(self, chat_id: int, message_id: int, session):
        """Show help information"""
        help_text = MESSAGES.get('help', """❓ **راهنمای استفاده**

🔢 **پیگیری سفارش:** شماره ۵ رقمی پذیرش
#️⃣ **پیگیری سریال:** ۱۰ کاراکتر (حروف+اعداد)

🔐 **ورود:** کد ملی ۱۰ رقمی
📦 **سفارشات:** مشاهده تاریخچه
🔧 **تعمیر:** ثبت درخواست تعمیر
📝 **شکایت:** ثبت مشکل و پیشنهاد

📞 **پشتیبانی:** ۰۲۱-۱۲۳۴۵۶۷۸""")

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 منوی اصلی", callback_data="main_menu")]
        ])

        await self.msg.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=help_text,
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN
        )

    # ========== DEVICE HANDLING (SIMPLIFIED - NO PAGINATION) ==========
    async def handle_devices_list(self, chat_id: int, message_id: int, order_number: str, session, page: int = 1):
        """Show devices for order - SIMPLIFIED (no complex pagination)"""
        try:
            # Fetch order to get devices
            order_data = await self.data.get_order_by_number(order_number)
            if not order_data or "error" in order_data:
                await self._show_error(chat_id, message_id, "❌ خطا در دریافت اطلاعات دستگاه")
                return

            devices = order_data.get("devices", [])
            if not devices:
                text = "📱 **دستگاه‌های سفارش**\n\nهیچ دستگاهی ثبت نشده است."
            else:
                text = "📱 **دستگاه‌های سفارش**\n\n"
                for i, device in enumerate(devices[:3], 1):  # Show max 3 devices
                    model = device.get("model", "---")
                    serial = device.get("serial", "---")
                    status = device.get("status", "---")
                    
                    text += f"{i}. `{model}`\n"
                    text += f"   سریال: `{serial}`\n"
                    text += f"   وضعیت: {status}\n\n"

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 جزئیات سفارش", callback_data=f"order_{order_number}")],
                [InlineKeyboardButton("🔙 منوی اصلی", callback_data="main_menu")]
            ])

            await self.msg.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=keyboard,
                parse_mode=ParseMode.MARKDOWN
            )

        except Exception as e:
            logger.error(f"Devices list error: {e}")
            await self._show_error(chat_id, message_id)
