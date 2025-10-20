"""
Message Handler - Handles all user message interactions for the Telegram bot
FIXED VERSION - Safe dictionary access and formatting
"""
import logging
import asyncio
from typing import Optional, Dict, Any
from telegram import Bot, Message, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.constants import ParseMode
from datetime import datetime
from functools import wraps

from .CoreConfig import (
    UserState, BotConfig, Validators, ComplaintType, CallbackFormats,
    MESSAGES, COMPLAINT_TYPE_MAP, WORKFLOW_STEPS, STEP_ICONS, STEP_PROGRESS,
    STATE_LABELS, MAIN_INLINE_KEYBOARD, MAIN_REPLY_KEYBOARD, REPLY_BUTTON_TO_CALLBACK,
    CANCEL_REPLY_KEYBOARD,safe_format_date
)
from .SessionManager import RedisSessionManager
from .DataProvider import DataProvider

logger = logging.getLogger(__name__)

def with_error_handling(func):
    """Error handling decorator"""
    @wraps(func)
    async def wrapper(self, chat_id: int, *args, **kwargs):
        try:
            return await func(self, chat_id, *args, **kwargs)
        except Exception as e:
            logger.error(f"Error in {func.__name__}: {e}")
            await self.send_message(chat_id, MESSAGES.get('error', '❌ خطا'))
            return None
    return wrapper

class MessageHandler:
    """Handles all message processing and state management"""

    def __init__(self, bot: Bot, config: BotConfig, session_manager: RedisSessionManager, data_provider: DataProvider , callback_handler: None):
        self.bot = bot
        self.config = config
        self.sessions = session_manager
        self.data = data_provider
        self.validators = Validators()
        self._in_callback_context = False
        self.callback_handler = callback_handler

        # State handlers mapping
        self.state_handlers = {
            UserState.WAITING_nationalId: self.handle_nationalId,
            UserState.WAITING_ORDER_NUMBER: self.handle_order_number,
            UserState.WAITING_SERIAL: self.handle_serial,
            UserState.WAITING_COMPLAINT_TEXT: self.handle_complaint_text,
            UserState.WAITING_REPAIR_DESC: self.handle_repair_description,
        }

    # ========== KEYBOARD MANAGEMENT ==========
    async def activate_main_keyboard(self, chat_id: int):
        """Activate main reply keyboard"""
        try:
            msg = await self.bot.send_message(
                chat_id=chat_id,
                text=" ",
                reply_markup=ReplyKeyboardMarkup(
                    MAIN_REPLY_KEYBOARD,
                    resize_keyboard=True,
                    one_time_keyboard=False,
                    input_field_placeholder="از منوی زیر انتخاب کنید..."
                )
            )
            await asyncio.sleep(0.1)
            await self.bot.delete_message(chat_id, msg.message_id)
        except Exception as e:
            logger.debug(f"Could not activate main keyboard: {e}")

    async def activate_cancel_keyboard(self, chat_id: int):
        """Activate cancel-only keyboard"""
        try:
            msg = await self.bot.send_message(
                chat_id=chat_id,
                text=" ",
                reply_markup=ReplyKeyboardMarkup(
                    CANCEL_REPLY_KEYBOARD,
                    resize_keyboard=True,
                    one_time_keyboard=False,
                    input_field_placeholder="برای انصراف، دکمه انصراف را بزنید"
                )
            )
            await asyncio.sleep(0.1)
            await self.bot.delete_message(chat_id, msg.message_id)
        except Exception as e:
            logger.debug(f"Could not activate cancel keyboard: {e}")

    # ========== MESSAGE UTILITIES ==========
    async def send_message(self, chat_id: int, text: str, reply_markup=None, parse_mode=None, activate_keyboard=False):
        """Send message with optional keyboard activation"""
        try:
            msg = await self.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode or ParseMode.HTML
            )
            
            if activate_keyboard:
                if "cancel" in text.lower() or "انصراف" in text:
                    await self.activate_cancel_keyboard(chat_id)
                else:
                    await self.activate_main_keyboard(chat_id)
                    
            return msg
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            return None

    async def edit_message(self, chat_id: int, message_id: int, text: str, reply_markup=None, parse_mode=None):
        """Edit message with error handling"""
        try:
            await self.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode or ParseMode.HTML
            )
            return True
        except Exception as e:
            error_str = str(e).lower()
            if "message is not modified" in error_str or "message to edit not found" in error_str:
                logger.debug(f"Edit skipped for message {message_id}: {error_str}")
                return False
            else:
                logger.error(f"Error editing message {message_id}: {e}")
                return False

    async def delete_message(self, chat_id: int, message_id: int):
        """Delete message safely"""
        try:
            await self.bot.delete_message(chat_id=chat_id, message_id=message_id)
            return True
        except Exception as e:
            logger.debug(f"Could not delete message {message_id}: {e}")
            return False

    # ========== MAIN PROCESSOR ==========
    @with_error_handling
    async def process_message(self, chat_id: int, text: str, message: Message = None):
        """Process incoming text messages"""
        # Delete user message for clean interface
        if message:
            await self.delete_message(chat_id, message.message_id)

        if self.config.maintenance_mode:
            await self.send_message(chat_id, MESSAGES['maintenance'])
            return

        async with self.sessions.session(chat_id) as session:
            # Handle rate limiting
            if session.state == UserState.RATE_LIMITED:
                remaining = session.temp_data.get('rate_limit_expires', 0) - datetime.now().timestamp()
                if remaining > 0:
                    await self.send_message(
                        chat_id, 
                        MESSAGES['rate_limited'].format(minutes=int(remaining/60)),
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]])
                    )
                    return
                session.state = UserState.IDLE

            # Update activity
            session.request_count += 1
            session.last_activity = datetime.now()

            # Check for reply keyboard buttons
            callback_data = REPLY_BUTTON_TO_CALLBACK.get(text.strip())
            if callback_data:
                await self._handle_reply_button(chat_id, callback_data, session)
                return

            # Process based on state
            handler = self.state_handlers.get(session.state)
            if handler:
                last_bot_message_id = session.temp_data.get('last_bot_message_id')
                await handler(chat_id, text, last_bot_message_id)
            else:
                await self.show_menu(chat_id, session.is_authenticated)

    async def _handle_reply_button(self, chat_id: int, callback_data: str, session):
        """Handle reply keyboard button presses"""
        try:
            if callback_data == "cancel":
                session.state = UserState.IDLE
                await self.activate_main_keyboard(chat_id)
                await self.show_menu(chat_id, session.is_authenticated)
            elif callback_data == "track_by_number":
                session.state = UserState.WAITING_ORDER_NUMBER
                await self.send_message(chat_id, "🔢 لطفاً شماره سفارش را وارد کنید:")
            elif callback_data == "track_by_serial":
                session.state = UserState.WAITING_SERIAL
                await self.send_message(chat_id, "#️⃣ لطفاً شماره سریال را وارد کنید:")
            elif callback_data == "authenticate":
                session.state = UserState.WAITING_nationalId
                await self.send_message(chat_id, "🔐 لطفاً کد ملی ۱۰ رقمی را وارد کنید:")
            elif callback_data == "my_orders":
                if session.is_authenticated:
                    await self.show_my_orders(chat_id, session)
                else:
                    await self.send_message(chat_id, "⚠️ ابتدا وارد حساب کاربری شوید")
            elif callback_data == "help":
                await self.show_help(chat_id)
            else:
                await self.show_menu(chat_id, session.is_authenticated)
        except Exception as e:
            logger.error(f"Reply button error: {e}")
            await self.send_message(chat_id, MESSAGES['error'])

    # ========== STATE HANDLERS ==========
    @with_error_handling
    async def handle_nationalId(self, chat_id: int, nationalId: str, message_id: int = None):
        """Handle national ID authentication - FIXED"""
        # Validate input
        if not nationalId.isdigit() or len(nationalId) != 10:
            error_text = "❌ کد ملی باید دقیقاً ۱۰ رقم باشد\n\nمثال: 1234567890"
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 تلاش مجدد", callback_data="authenticate")],
                [InlineKeyboardButton("🔙 منوی اصلی", callback_data="main_menu")]
            ])
            if message_id:
                await self.edit_message(chat_id, message_id, error_text, keyboard)
            else:
                await self.send_message(chat_id, error_text, keyboard)
            return

        # Show loading
        loading_text = "🔄 در حال بررسی احراز هویت..."
        if message_id:
            await self.edit_message(chat_id, message_id, loading_text)
        else:
            loading_msg = await self.send_message(chat_id, loading_text)
            message_id = loading_msg.message_id if loading_msg else None

        try:
            # Authenticate
            user_data = await self.data.authenticate_user(nationalId)
            
            if user_data and user_data.get('authenticated', False):
                # Success - update session
                async with self.sessions.session(chat_id) as session:
                    session.is_authenticated = True
                    session.nationalId = nationalId
                    session.user_name = user_data.get('name', 'کاربر گرامی')
                    session.phone_number = user_data.get('phone_number', 'نامشخص')
                    session.city = user_data.get('city', 'نامشخص')
                    session.state = UserState.AUTHENTICATED
                    session.extend(3600)  # 1 hour session

                success_text = f"✅ **احراز هویت موفق**\n\n👤 {session.user_name} عزیز، خوش آمدید!"
                await self.edit_message(
                    chat_id, message_id, success_text,
                    parse_mode=ParseMode.MARKDOWN
                )
                await asyncio.sleep(1)
                await self.show_authenticated_menu(chat_id, message_id)
                
            else:
                error_text = "❌ **کد ملی یافت نشد**\n\nلطفاً از صحت اطلاعات اطمینان حاصل کنید"
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 تلاش مجدد", callback_data="authenticate")],
                    [InlineKeyboardButton("🔙 منوی اصلی", callback_data="main_menu")]
                ])
                await self.edit_message(chat_id, message_id, error_text, keyboard, ParseMode.MARKDOWN)

        except Exception as e:
            logger.error(f"Authentication error: {e}")
            error_text = "❌ خطا در احراز هویت. لطفاً دوباره تلاش کنید."
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 منوی اصلی", callback_data="main_menu")]])
            await self.edit_message(chat_id, message_id, error_text, keyboard)

    @with_error_handling
    async def handle_order_lookup(self, chat_id: int, value: str, lookup_type: str, message_id: int = None):
        """Handle order lookup by number or serial - FIXED"""
        value = value.strip()
        logger.info(f"Looking up {lookup_type}: {value}")

        # Store lookup info
        async with self.sessions.session(chat_id) as session:
            session.temp_data['lookup_type'] = lookup_type
            session.temp_data['lookup_value'] = value

        # Show loading
        loading_text = "🔄 در حال جستجوی سفارش..."
        if message_id:
            await self.edit_message(chat_id, message_id, loading_text)
        else:
            loading_msg = await self.send_message(chat_id, loading_text)
            message_id = loading_msg.message_id if loading_msg else None

        try:
            # Fetch order data
            if lookup_type == 'number':
                order_data = await self.data.get_order_by_number(value)
            else:  # serial
                order_data = await self.data.get_order_by_serial(value)

            # Display results
            if order_data and not order_data.get('error'):
                await self.display_order_details(chat_id, order_data, message_id)
            else:
                error_text = f"❌ سفارشی با این {'شماره' if lookup_type == 'number' else 'سریال'} یافت نشد"
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 تلاش مجدد", callback_data=f"track_by_{lookup_type}")],
                    [InlineKeyboardButton("🔙 منوی اصلی", callback_data="main_menu")]
                ])
                await self.edit_message(chat_id, message_id, error_text, keyboard)

            # Reset state
            async with self.sessions.session(chat_id) as session:
                session.state = UserState.AUTHENTICATED if session.is_authenticated else UserState.IDLE
                session.temp_data['last_bot_message_id'] = message_id

        except Exception as e:
            logger.error(f"Order lookup error: {e}", exc_info=True)
            error_text = "❌ خطا در جستجو. لطفاً دوباره تلاش کنید."
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 منوی اصلی", callback_data="main_menu")]])
            await self.edit_message(chat_id, message_id, error_text, keyboard)

    async def handle_order_number(self, chat_id: int, text: str, message_id: int = None):
        """Handle order number input"""
        await self.handle_order_lookup(chat_id, text, "number", message_id)
        await self.activate_main_keyboard(chat_id)

    async def handle_serial(self, chat_id: int, text: str, message_id: int = None):
        """Handle serial number input"""
        await self.handle_order_lookup(chat_id, text, "serial", message_id)
        await self.activate_main_keyboard(chat_id)

    @with_error_handling
    async def handle_complaint_text(self, chat_id: int, text: str, message_id: int = None):
        """Handle complaint text - FIXED validation"""
        if len(text.strip()) < 10:
            error_text = "⚠️ متن شکایت باید حداقل ۱۰ کاراکتر باشد\n\nلطفاً توضیحات کامل‌تری بنویسید:"
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 انصراف", callback_data="main_menu")]])
            if message_id:
                await self.edit_message(chat_id, message_id, error_text, keyboard)
            else:
                await self.send_message(chat_id, error_text, keyboard)
            return

        async with self.sessions.session(chat_id) as session:
            if not session.is_authenticated:
                await self.send_message(chat_id, "⚠️ ابتدا وارد حساب کاربری شوید")
                return

            complaint_type = session.temp_data.get('complaint_type', 'other')
            ticket_number = await self.data.submit_complaint(
                session.nationalId, 
                complaint_type, 
                text.strip()
            )

            if ticket_number and not ticket_number.get('error'):
                success_text = MESSAGES['complaint_submitted'].format(
                    ticket_number=ticket_number.get('ticket_id', 'نامشخص'),
                    complaint_type=COMPLAINT_TYPE_MAP.get(complaint_type, 'سایر'),
                    date=datetime.now().strftime('%Y/%m/%d')
                )
                await self.send_message(chat_id, success_text)
            else:
                await self.send_message(chat_id, "❌ خطا در ثبت شکایت. لطفاً دوباره تلاش کنید.")

            # Reset state
            session.state = UserState.AUTHENTICATED
            session.temp_data.clear()
            await self.show_menu(chat_id, True)

    @with_error_handling
    async def handle_repair_description(self, chat_id: int, text: str, message_id: int = None):
        """Handle repair request - FIXED"""
        if not text.strip():
            await self.send_message(chat_id, "⚠️ لطفاً توضیحات را وارد کنید")
            return

        async with self.sessions.session(chat_id) as session:
            if not session.is_authenticated:
                await self.send_message(chat_id, "⚠️ ابتدا وارد حساب کاربری شوید")
                return

            if len(text.strip()) < 10:
                await self.send_message(chat_id, "⚠️ توضیحات باید حداقل ۱۰ کاراکتر باشد")
                return

            request_number = await self.data.submit_repair_request(
                session.nationalId, 
                text.strip()
            )

            if request_number and not request_number.get('error'):
                success_text = MESSAGES['repair_submitted'].format(
                    request_number=request_number.get('request_id', 'نامشخص'),
                    date=datetime.now().strftime('%Y/%m/%d')
                )
                await self.send_message(chat_id, success_text)
            else:
                await self.send_message(chat_id, "❌ خطا در ثبت درخواست تعمیر")

            # Reset state
            session.state = UserState.AUTHENTICATED
            session.temp_data.clear()
            await self.show_menu(chat_id, True)

    # ========== DISPLAY METHODS - FIXED FORMATTING ==========
    async def display_order_details(self, chat_id: int, order_data: Dict[str, Any], message_id: int = None):
        """Display order details"""
        try:
            logger.info(f"Display order details called with data: {order_data}")
            
            if not order_data:
                error_text = MESSAGES.get('order_not_found', '❌ سفارش یافت نشد')
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 منوی اصلی", callback_data="main_menu")]
                ])
                
                if message_id:
                    await self.edit_message(chat_id, message_id, error_text, keyboard)
                else:
                    await self.send_message(chat_id, error_text, keyboard)
                return

            if isinstance(order_data, dict):
                if order_data.get('success') == False or order_data.get('error'):
                    error_text = order_data.get('message', order_data.get('error', MESSAGES.get('order_not_found', '❌ سفارش یافت نشد')))
                    keyboard = InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="main_menu")]
                    ])
                    
                    if message_id:
                        await self.edit_message(chat_id, message_id, error_text, keyboard)
                    else:
                        await self.send_message(chat_id, error_text, keyboard)
                    return

                meaningful_data = any(
                    str(order_data.get(key, '')).strip() not in ['نامشخص', '', '---', '0'] 
                    for key in ['order_number', 'customer_name', 'device_model']
                )
                
                if not meaningful_data:
                    error_text = MESSAGES.get('order_not_found', '❌ سفارشی با این مشخصات یافت نشد')
                    keyboard = InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="main_menu")]
                    ])
                    
                    if message_id:
                        await self.edit_message(chat_id, message_id, error_text, keyboard)
                    else:
                        await self.send_message(chat_id, error_text, keyboard)
                    return

            additional_info = ""
            
            order_number = str(order_data.get('order_number', 'نامشخص') or 'نامشخص').strip()
            customer_name = str(order_data.get('customer_name', 'نامشخص') or 'نامشخص').strip()
            device_model = str(order_data.get('device_model', 'نامشخص') or 'نامشخص').strip()
            serial_number = str(order_data.get('serial_number', '---') or '---').strip()
            phone_number = str(order_data.get('phone_number', '---') or '---').strip()
            city = str(order_data.get('city', 'نامشخص') or 'نامشخص').strip()
            
            registration_date_raw = order_data.get('registration_date', '')
            pre_reception_date_raw = order_data.get('pre_reception_date', '')
            
            registration_date = safe_format_date(registration_date_raw, "نامشخص")
            pre_reception_date = safe_format_date(pre_reception_date_raw, "نامشخص")
            
            total_cost_raw = order_data.get('total_cost')
            if total_cost_raw is None or total_cost_raw == 0 or str(total_cost_raw).strip() in ['', 'null']:
                total_cost = "رایگان"
                total_cost_formatted = "رایگان"
            else:
                try:
                    total_cost_value = float(str(total_cost_raw).strip())
                    if total_cost_value > 0:
                        total_cost_formatted = f"{int(total_cost_value):,}"
                        additional_info += f"💰 **هزینه کل:** {total_cost_formatted} تومان"
                    else:
                        total_cost = "رایگان"
                        total_cost_formatted = "رایگان"
                except (ValueError, TypeError, AttributeError):
                    total_cost = "نامشخص"
                    total_cost_formatted = "نامشخص"

            current_step_num = int(order_data.get('steps', 0))
            current_step_text = WORKFLOW_STEPS.get(current_step_num, f"مرحله {current_step_num}")
            progress_percent = STEP_PROGRESS.get(current_step_num, 0)
            status_icon = STEP_ICONS.get(current_step_num, "📍")
            
            total_bars = 10
            filled_bars = max(0, min(int((progress_percent / 100) * total_bars), total_bars))
            progress_bar = "█" * filled_bars + "░" * (total_bars - filled_bars)

            notes = str(order_data.get('notes', '') or '').strip()
            if notes and notes not in ['نامشخص', '']:
                additional_info += f"\n📝 **یادداشت:** {notes}"

            delivery_date_raw = order_data.get('delivery_date', '')
            if delivery_date_raw:
                delivery_date = safe_format_date(delivery_date_raw, "")
                if delivery_date and delivery_date not in ['نامشخص', '']:
                    additional_info += f"\n📅 **تاریخ تحویل:** {delivery_date}"

            tracking_code = str(order_data.get('tracking_code', '') or '').strip()
            if tracking_code and tracking_code not in ['نامشخص', '']:
                additional_info += f"\n📦 **کد رهگیری:** `{tracking_code}`"

            repair_desc = str(order_data.get('repair_description', '') or '').strip()
            if repair_desc and repair_desc not in ['نامشخص', '']:
                additional_info += f"\n🔧 **توضیحات تعمیر:** {repair_desc}"

            order_details_text = f"""📦 **جزئیات سفارش #{order_number}**

    👤 **مشتری:** {customer_name}
    📞 **تلفن:** `{phone_number}`
    🏙️ **استان/شهر:** {city}

    📱 **دستگاه:**
    ├ مدل: {device_model}
    ├ سریال: `{serial_number}`
    └ وضعیت: {order_data.get('device_status', 'نامشخص')}

    📊 ** سفارش وضعیت:**
    ├ مرحله: {status_icon} {current_step_text}
    └ پیشرفت:
            {progress_bar} **{progress_percent}%**

    📅 **تاریخ‌ها:**
    ├ ثبت: {registration_date}
    └ پیش‌پذیرش: {pre_reception_date}

    {additional_info if additional_info.strip() else ''}

    ⏰ **آخرین بروزرسانی:** {datetime.now().strftime('%Y/%m/%d - %H:%M')}"""

            buttons = []
            payment_link = order_data.get('payment_link')
            factor_payment = order_data.get('factor_payment', {})
            
            if payment_link:
                if isinstance(factor_payment, dict) and factor_payment:  # Payment completed
                    buttons.append([InlineKeyboardButton("💳 مشاهده فاکتور", url=payment_link)])
                elif not factor_payment or factor_payment == {}:  # Payment pending
                    buttons.append([InlineKeyboardButton("💳 مشاهده فاکتور و پرداخت", url=payment_link)])
            
            buttons.extend([
                [InlineKeyboardButton("🔄 بروزرسانی", callback_data=f"refresh_order:{order_number}")],
                [InlineKeyboardButton("🔙 منوی اصلی", callback_data="main_menu")]
            ])
            
            keyboard = InlineKeyboardMarkup(buttons)

            if message_id:
                try:
                    success = await self.edit_message(
                        chat_id, message_id, order_details_text, 
                        keyboard, parse_mode=ParseMode.MARKDOWN
                    )
                    if not success:
                        await self.send_message(
                            chat_id, order_details_text, 
                            keyboard, parse_mode=ParseMode.MARKDOWN
                        )
                except Exception as edit_error:
                    logger.warning(f"Edit failed, sending new message: {edit_error}")
                    await self.send_message(
                        chat_id, order_details_text, 
                        keyboard, parse_mode=ParseMode.MARKDOWN
                    )
            else:
                await self.send_message(
                    chat_id, order_details_text, 
                    keyboard, parse_mode=ParseMode.MARKDOWN
                )

            logger.info(f"✅ Order details displayed successfully for {order_number}")

        except Exception as e:
            logger.error(f"❌ Display order details error: {e}", exc_info=True)
            error_text = "❌ خطا در نمایش جزئیات سفارش. لطفاً دوباره تلاش کنید."
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 منوی اصلی", callback_data="main_menu")]])
            
            try:
                if message_id:
                    await self.edit_message(chat_id, message_id, error_text, keyboard)
                else:
                    await self.send_message(chat_id, error_text, keyboard)
            except Exception as send_error:
                logger.error(f"Failed to send error message: {send_error}")


    async def show_menu(self, chat_id: int, authenticated: bool = False, message_id: int = None):
        """Show main menu - FIXED keyboard sizing"""
        try:
            if authenticated is None:
                async with self.sessions.session(chat_id) as session:
                    authenticated = session.is_authenticated and bool(session.nationalId)

            if authenticated:
                async with self.sessions.session(chat_id) as session:
                    name = session.user_name or "کاربر"
                    session.temp_data.pop('last_menu_type', None)

                text = f"👋 **سلام {name}!**\n\n📋 از پنل کاربری انتخاب کنید:"
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("👤 اطلاعات من", callback_data="my_info")],
                    [InlineKeyboardButton("📦 سفارشات من", callback_data="my_orders")],
                    [InlineKeyboardButton("🔢 پیگیری سفارش", callback_data="track_by_number")],
                    [InlineKeyboardButton("🔢 پیگیری سریال", callback_data="track_by_serial")],
                    [InlineKeyboardButton("🔧 درخواست تعمیر", callback_data="repair_request")],
                    [InlineKeyboardButton("📝 ثبت شکایت", callback_data="submit_complaint")],
                    [InlineKeyboardButton("🚪 خروج", callback_data="logout")]
                ])
            else:
                async with self.sessions.session(chat_id) as session:
                    session.temp_data.pop('last_menu_type', None)

                text = "🏠 **منوی اصلی**\n\nلطفاً یک گزینه را انتخاب کنید:"
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔐 ورود با کد ملی", callback_data="authenticate")],
                    [InlineKeyboardButton("🔢 پیگیری سفارش", callback_data="track_by_number")],
                    [InlineKeyboardButton("🔢 پیگیری سریال", callback_data="track_by_serial")],
                    [InlineKeyboardButton("❓ راهنما", callback_data="help")]
                ])

            if message_id:
                await self.edit_message(chat_id, message_id, text, keyboard, ParseMode.MARKDOWN)
            else:
                await self.send_message(chat_id, text, keyboard, ParseMode.MARKDOWN, activate_keyboard=True)

        except Exception as e:
            logger.error(f"Show menu error: {e}")
            fallback_text = "🏠 منوی اصلی"
            fallback_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 شروع", callback_data="main_menu")]])
            await self.send_message(chat_id, fallback_text, fallback_keyboard)

    async def show_authenticated_menu(self, chat_id: int, message_id: int = None):
        """Show authenticated user menu"""
        await self.show_menu(chat_id, authenticated=True, message_id=message_id)

    async def show_my_orders(self, chat_id: int, session):
        """Show user's orders list"""
        try:
            if not session.is_authenticated or not session.nationalId:
                await self.send_message(
                    chat_id, 
                    "⚠️ **ابتدا وارد حساب کاربری شوید**",
                    InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔐 ورود", callback_data="authenticate")],
                        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="main_menu")]
                    ]),
                    ParseMode.MARKDOWN
                )
                return

            # Show loading
            loading_msg = await self.send_message(chat_id, "🔄 در حال بارگذاری سفارشات...")
            
            # Fetch orders
            orders_data = await self.data.get_user_orders(session.nationalId)
            
            if not orders_data or orders_data.get('error') or not orders_data.get('orders'):
                text = "📦 **سفارشات شما**\n\nهیچ سفارشی یافت نشد.\n\nبرای ثبت سفارش جدید با پشتیبانی تماس بگیرید."
                keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 منوی اصلی", callback_data="main_menu")]])
            else:
                orders = orders_data.get('orders', [])
                text = "📦 **سفارشات فعال شما**\n\n"
                
                for i, order in enumerate(orders[:5], 1):  # Show max 5
                    order_num = str(order.get('order_number', f'سفارش {i}') or f'سفارش {i}')
                    steps = order.get('steps', 0)
                    status_icon = STEP_ICONS.get(steps, "📍")
                    status_text = WORKFLOW_STEPS.get(steps, "در حال بررسی")
                    reg_date = str(order.get('registration_date', '---') or '---')
                    
                    if ' ' in reg_date:
                        reg_date = reg_date.split(' ')[0]
                    
                    text += f"{i}. {status_icon} `{order_num}`\n"
                    text += f"   📅 {reg_date} | {status_text}\n\n"
                
                if len(orders) > 5:
                    text += f"... و {len(orders) - 5} سفارش دیگر"
                
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 بروزرسانی", callback_data="my_orders")],
                    [InlineKeyboardButton("🔙 منوی اصلی", callback_data="main_menu")]
                ])

            await self.delete_message(chat_id, loading_msg.message_id)
            await self.send_message(chat_id, text, keyboard, ParseMode.MARKDOWN)

        except Exception as e:
            logger.error(f"Show my orders error: {e}")
            await self.send_message(
                chat_id, 
                "❌ خطا در بارگذاری سفارشات",
                InlineKeyboardMarkup([[InlineKeyboardButton("🔙 منوی اصلی", callback_data="main_menu")]])
            )

    async def show_help(self, chat_id: int, message_id: int = None):
        """Show help using MESSAGES['help']"""
        try:
            # Use MESSAGES['help'] but replace config vars with hardcoded values
            help_text = MESSAGES['help'].format(
                support_phone=self.config.support_phone,
                website_url=self.config.website_url 
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 منوی اصلی", callback_data="main_menu")]
            ])
            if message_id:
                await self.edit_message(chat_id, message_id, help_text, 
                                    reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
            else:
                msg = await self.send_message(chat_id, help_text, 
                                            reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
                async with self.sessions.session(chat_id) as session:
                    if msg: session.temp_data['last_bot_message_id'] = msg.message_id
                    
        except Exception as e:
            logger.error(f"Help error: {e}")

    # ========== START COMMAND ==========
    async def handle_start(self, chat_id: int):
        """Handle /start command"""
        async with self.sessions.session(chat_id) as session:
            session.state = UserState.IDLE
            session.temp_data.clear()

        await self.send_message(
            chat_id=chat_id,
            text=MESSAGES['welcome'],
            reply_markup=InlineKeyboardMarkup(MAIN_INLINE_KEYBOARD),
            parse_mode=ParseMode.HTML,
            activate_keyboard=True
        )
