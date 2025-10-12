"""
Message Handler - Handles all user message interactions for the Telegram bot
"""
import logging
import re
from typing import Optional, Dict, Any
from telegram import Bot, Message, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from datetime import datetime

from .CoreConfig import (
    UserState, BotConfig, Validators,ComplaintType,CallbackFormats,
    MESSAGES, COMPLAINT_TYPE_MAP, STATUS_TEXT, WORKFLOW_STEPS, STEP_ICONS, STEP_PROGRESS
)
from .SessionManager import RedisSessionManager
from .DataProvider import DataProvider

logger = logging.getLogger(__name__)

class MessageHandler:
    """Handles all message processing and state management"""
    
    def __init__(
        self,
        bot: Bot,
        config: BotConfig,
        session_manager: RedisSessionManager,
        data_provider: DataProvider
    ):
        self.bot = bot
        self.config = config
        self.sessions = session_manager
        self.data = data_provider
        self.validators = Validators()

    # =====================================================
    # Main Message Processing
    # =====================================================
    
    async def process_message(self, chat_id: int, text: str, message: Message = None):
        """Process incoming text messages based on user state"""
        try:
            # Check maintenance mode
            if self.config.maintenance_mode:
                await self.send_message(chat_id, MESSAGES['maintenance'])
                return

            # Get/create session
            async with self.sessions.session(chat_id) as session:
                # Check rate limiting
                if session.state == UserState.RATE_LIMITED:
                    remaining = session.temp_data.get('rate_limit_expires', 0) - datetime.now().timestamp()
                    if remaining > 0:
                        await self.send_message(
                            chat_id,
                            MESSAGES['rate_limited'].format(
                                minutes=int(remaining/60),
                                max_requests=self.config.max_requests_hour
                            )
                        )
                        return
                    session.state = UserState.IDLE

                # Update activity
                session.request_count += 1
                session.last_activity = datetime.now()

                # Route based on state
                state_handlers = {
                    UserState.WAITING_NATIONAL_ID: self.handle_national_id,
                    UserState.WAITING_ORDER_NUMBER: self.handle_order_number,
                    UserState.WAITING_SERIAL: self.handle_serial,
                    UserState.WAITING_COMPLAINT_TEXT: self.handle_complaint_text,
                    UserState.WAITING_RATING_SCORE: self.handle_rating_score,
                    UserState.WAITING_RATING_TEXT: self.handle_rating_text,
                    UserState.WAITING_REPAIR_DESC: self.handle_repair_description,
                }

                handler = state_handlers.get(session.state)
                if handler:
                    await handler(chat_id, text)
                else:
                    # Show appropriate menu
                    if session.is_authenticated:
                        await self.show_authenticated_menu(chat_id)
                    else:
                        await self.show_main_menu(chat_id)
                        
        except Exception as e:
            logger.error(f"Error processing message from {chat_id}: {e}", exc_info=True)
            await self.send_message(chat_id, MESSAGES.get('error', '❌ خطا در پردازش'))

    async def handle_start(self, chat_id: int):
        """Handle /start command"""
        async with self.sessions.session(chat_id) as session:
            # Clear any previous state
            session.state = UserState.IDLE
            session.temp_data.clear()
            
        # Show welcome message with main menu
        welcome_msg = MESSAGES['welcome']
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔐 ورود با کد ملی", callback_data=CallbackFormats.AUTHENTICATE)],
            [
                InlineKeyboardButton("🔢 پیگیری سفارش", callback_data=CallbackFormats.TRACK_BY_NUMBER),
                InlineKeyboardButton("#️⃣ پیگیری سریال", callback_data=CallbackFormats.TRACK_BY_SERIAL)
            ],
            [InlineKeyboardButton("❓ راهنما", callback_data=CallbackFormats.HELP)]
        ])
        
        await self.bot.send_message(
            chat_id=chat_id,
            text=welcome_msg,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )

    # =====================================================
    # State Handlers
    # =====================================================
    
    async def handle_national_id(self, chat_id: int, text: str):
        """Handle national ID input for authentication"""
        # Clean input
        nid = re.sub(r'\D', '', text.strip())
        
        # Validate format
        if not self.validators.validate_national_id(nid):
            await self.send_message(
                chat_id,
                "❌ کد ملی نامعتبر\n\nکد ملی باید 10 رقم باشد.\nمثال: 1234567890"
            )
            return

        # Show loading
        loading_msg = await self.send_message(chat_id, "🔄 در حال بررسی...")
        
        try:
            # Authenticate via API
            user_info = await self.data.authenticate_user(nid)
            
            if user_info and user_info.get('name'):
                # Success - update session
                async with self.sessions.session(chat_id) as session:
                    session.is_authenticated = True
                    session.national_id = nid
                    session.user_name = user_info.get('name', 'کاربر')
                    session.phone_number = user_info.get('phone')
                    session.state = UserState.AUTHENTICATED
                    session.extend(60)  # Extend for authenticated users
                
                # Delete loading message
                if loading_msg:
                    try:
                        await self.bot.delete_message(chat_id, loading_msg.message_id)
                    except:
                        pass
                
                # Show success and menu
                await self.send_message(
                    chat_id,
                    MESSAGES['auth_success'].format(name=user_info['name'])
                )
                await self.show_authenticated_menu(chat_id)
                
            else:
                # Failed authentication
                if loading_msg:
                    try:
                        await self.bot.delete_message(chat_id, loading_msg.message_id)
                    except:
                        pass
                
                # Show error with retry option
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 تلاش مجدد", callback_data=CallbackFormats.AUTHENTICATE)],
                    [InlineKeyboardButton("🏠 منوی اصلی", callback_data=CallbackFormats.MAIN_MENU)]
                ])
                
                await self.send_message(
                    chat_id,
                    MESSAGES['auth_failed'].format(support_phone=self.config.support_phone),
                    reply_markup=keyboard
                )
                
                # Reset state
                async with self.sessions.session(chat_id) as session:
                    session.state = UserState.IDLE
                    
        except Exception as e:
            logger.error(f"Auth error for {chat_id}: {e}")
            if loading_msg:
                try:
                    await self.bot.delete_message(chat_id, loading_msg.message_id)
                except:
                    pass
            await self.send_message(chat_id, "❌ خطا در احراز هویت. لطفاً دوباره تلاش کنید.")
            
            async with self.sessions.session(chat_id) as session:
                session.state = UserState.IDLE

    async def handle_order_number(self, chat_id: int, text: str):
        """Handle order number input"""
        order_number = text.strip().upper()
        
        if not self.validators.validate_order_number(order_number):
            await self.send_message(
                chat_id,
                "❌ شماره پذیرش نامعتبر\n\nلطفاً شماره صحیح وارد کنید."
            )
            return

        # Show loading
        loading_msg = await self.send_message(chat_id, "🔍 در حال جستجو...")
        
        try:
            # Get order data
            order_data = await self.data.get_order_by_number(order_number)
            
            # Delete loading message
            if loading_msg:
                try:
                    await self.bot.delete_message(chat_id, loading_msg.message_id)
                except:
                    pass
            
            # Check if order found
            if not order_data or not order_data.get('order_number'):
                # Not found - show error with options
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 تلاش مجدد", callback_data=CallbackFormats.TRACK_BY_NUMBER)],
                    [InlineKeyboardButton("🏠 منوی اصلی", callback_data=CallbackFormats.MAIN_MENU)]
                ])
                
                await self.send_message(
                    chat_id,
                    MESSAGES['order_not_found'],
                    reply_markup=keyboard
                )
            else:
                # Found - format and display
                await self.display_order_details(chat_id, order_data)
            
            # Clear state
            async with self.sessions.session(chat_id) as session:
                if session.is_authenticated:
                    session.state = UserState.AUTHENTICATED
                else:
                    session.state = UserState.IDLE
                    
        except Exception as e:
            logger.error(f"Order lookup error: {e}")
            if loading_msg:
                try:
                    await self.bot.delete_message(chat_id, loading_msg.message_id)
                except:
                    pass
            await self.send_message(chat_id, "❌ خطا در جستجو. لطفاً دوباره تلاش کنید.")
            
            async with self.sessions.session(chat_id) as session:
                session.state = UserState.IDLE

    async def handle_serial(self, chat_id: int, text: str):
        """Handle serial number input"""
        serial = text.strip().upper()
        
        if len(serial) < 5:
            await self.send_message(
                chat_id,
                "❌ سریال نامعتبر\n\nسریال باید حداقل 5 کاراکتر باشد."
            )
            return

        # Show loading
        loading_msg = await self.send_message(chat_id, "🔍 در حال جستجو...")
        
        try:
            # Get order data by serial
            order_data = await self.data.get_order_by_serial(serial)
            
            # Delete loading message
            if loading_msg:
                try:
                    await self.bot.delete_message(chat_id, loading_msg.message_id)
                except:
                    pass
            
            # Check if order found
            if not order_data or not order_data.get('order_number'):
                # Not found - show error with options
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 تلاش مجدد", callback_data=CallbackFormats.TRACK_BY_SERIAL)],
                    [InlineKeyboardButton("🏠 منوی اصلی", callback_data=CallbackFormats.MAIN_MENU)]
                ])
                
                await self.send_message(
                    chat_id,
                    MESSAGES['order_not_found'],
                    reply_markup=keyboard
                )
            else:
                # Found - format and display
                await self.display_order_details(chat_id, order_data)
            
            # Clear state
            async with self.sessions.session(chat_id) as session:
                if session.is_authenticated:
                    session.state = UserState.AUTHENTICATED
                else:
                    session.state = UserState.IDLE
                    
        except Exception as e:
            logger.error(f"Serial lookup error: {e}")
            if loading_msg:
                try:
                    await self.bot.delete_message(chat_id, loading_msg.message_id)
                except:
                    pass
            await self.send_message(chat_id, "❌ خطا در جستجو. لطفاً دوباره تلاش کنید.")
            
            async with self.sessions.session(chat_id) as session:
                session.state = UserState.IDLE

    async def handle_complaint_text(self, chat_id: int, text: str):
        """Handle complaint text submission"""
        if len(text) < 10:
            await self.send_message(chat_id, "⚠️ متن شکایت باید حداقل 10 کاراکتر باشد.")
            return

        async with self.sessions.session(chat_id) as session:
            complaint_type = session.temp_data.get('complaint_type', ComplaintType.OTHER)
            
            # Submit complaint
            ticket_number = await self.data.submit_complaint(
                session.national_id,
                complaint_type.value,
                text
            )
            
            if ticket_number:
                await self.send_message(
                    chat_id,
                    MESSAGES['complaint_submitted'].format(
                        ticket_number=ticket_number,
                        complaint_type=COMPLAINT_TYPE_MAP.get(complaint_type, 'سایر'),
                        date=datetime.now().strftime('%Y/%m/%d')
                    )
                )
            else:
                await self.send_message(chat_id, "❌ خطا در ثبت شکایت")
            
            # Clear state
            session.state = UserState.AUTHENTICATED
            session.temp_data.clear()

        await self.show_authenticated_menu(chat_id)

    async def handle_rating_score(self, chat_id: int, text: str):
        """Handle rating score input"""
        try:
            score = int(text)
            if not 1 <= score <= 5:
                raise ValueError
        except:
            await self.send_message(chat_id, "⚠️ لطفاً عددی بین 1 تا 5 وارد کنید.")
            return

        async with self.sessions.session(chat_id) as session:
            session.temp_data['rating_score'] = score
            session.state = UserState.WAITING_RATING_TEXT
            
        await self.send_message(chat_id, "💬 لطفاً نظر خود را بنویسید (اختیاری):")

    async def handle_rating_text(self, chat_id: int, text: str):
        """Handle rating comment"""
        if text.lower() in ['/skip', '/cancel', '/logout']:
            text = ''    

        async with self.sessions.session(chat_id) as session:
            score = session.temp_data.get('rating_score', 5)
            
            # Submit rating
            success = await self.data.submit_rating(
                session.national_id,
                score,
                text
            )
            
            if success:
                stars = "⭐" * score
                await self.send_message(
                    chat_id,
                    MESSAGES['rating_thanks'].format(
                        stars=stars,
                        comment=text if text else 'بدون نظر'
                    )
                )
            else:
                await self.send_message(chat_id, "❌ خطا در ثبت امتیاز")
            
            # Clear state
            session.state = UserState.AUTHENTICATED
            session.temp_data.clear()

        await self.show_authenticated_menu(chat_id)

    async def handle_repair_description(self, chat_id: int, text: str):
        """Handle repair request description"""
        if len(text) < 10:
            await self.send_message(chat_id, "⚠️ توضیحات باید حداقل 10 کاراکتر باشد.")
            return

        async with self.sessions.session(chat_id) as session:
            # Submit repair request
            request_number = await self.data.submit_repair_request(
                session.national_id,
                text,
                session.phone_number or ''
            )
            
            if request_number:
                await self.send_message(
                    chat_id,
                    MESSAGES['repair_submitted'].format(
                        request_number=request_number,
                        date=datetime.now().strftime('%Y/%m/%d')
                    )
                )
            else:
                await self.send_message(chat_id, "❌ خطا در ثبت درخواست")

            # Reset state
            session.state = UserState.AUTHENTICATED
            session.temp_data.clear()

        await self.show_authenticated_menu(chat_id)

    # =====================================================
    # Display Helpers
    # =====================================================
    async def display_order_details(self, chat_id: int, order: Dict[str, Any], message_id: Optional[int] = None):
        """Display formatted order details with action buttons"""
        # Format the message using the new formatter
        msg = self.format_order_details(order)
        
        buttons = [
            [InlineKeyboardButton("🔄 بروزرسانی", callback_data=CallbackFormats.REFRESH_ORDER.format(order.get('order_number')))]
        ]

        # Add devices button if multiple
        device_count = order.get('device_count', 1)
        if device_count > 1:
            buttons.append([InlineKeyboardButton(f"📋 دستگاه‌ها ({device_count})", 
                            callback_data=CallbackFormats.DEVICES.format(order.get('order_number')))])

        buttons.append([InlineKeyboardButton("🏠 منوی اصلی", callback_data=CallbackFormats.MAIN_MENU)])

        keyboard = InlineKeyboardMarkup(buttons)
        
        if message_id:
            await self.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=msg,
                reply_markup=keyboard,
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await self.send_message(chat_id, msg, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)



    async def show_main_menu(self, chat_id: int):
        """Display menu for non-authenticated users"""
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔐 ورود با کد ملی", callback_data=CallbackFormats.AUTHENTICATE)],
            [
                InlineKeyboardButton("🔢 پیگیری سفارش", callback_data=CallbackFormats.TRACK_BY_NUMBER),
                InlineKeyboardButton("#️⃣ پیگیری سریال", callback_data=CallbackFormats.TRACK_BY_SERIAL)
            ],
            [InlineKeyboardButton("❓ راهنما", callback_data=CallbackFormats.HELP)]
        ])
        await self.send_message(chat_id, "🏠 منوی اصلی\n\nلطفاً یک گزینه را انتخاب کنید:", reply_markup=keyboard)

    async def show_authenticated_menu(self, chat_id: int):
        """Display menu for authenticated users"""
        async with self.sessions.session(chat_id) as session:
            name = session.user_name or "کاربر"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("👤 اطلاعات من", callback_data=CallbackFormats.MY_INFO)],
            [InlineKeyboardButton("📦 سفارشات من", callback_data=CallbackFormats.MY_ORDERS)],
            [
                InlineKeyboardButton("🔢 پیگیری سفارش", callback_data=CallbackFormats.TRACK_BY_NUMBER),
                InlineKeyboardButton("#️⃣ پیگیری سریال", callback_data=CallbackFormats.TRACK_BY_SERIAL)
            ],
            [InlineKeyboardButton("🔧 درخواست تعمیر", callback_data=CallbackFormats.REPAIR_REQUEST)],
            [InlineKeyboardButton("📝 ثبت شکایت", callback_data=CallbackFormats.SUBMIT_COMPLAINT)],
            [InlineKeyboardButton("⭐ امتیازدهی", callback_data=CallbackFormats.RATE_SERVICE)],
            [InlineKeyboardButton("🚪 خروج", callback_data=CallbackFormats.LOGOUT)]
        ])
        await self.send_message(
            chat_id,
            f"👋 سلام {name} عزیز!\n\n📋 به پنل کاربری خوش آمدید. از منوی زیر انتخاب کنید:",
            reply_markup=keyboard
        )

    async def show_devices_page(self, chat_id: int, message_id: int, page: int, order_number: str):
        """Paginate devices list for multi-device orders"""
        order = await self.data.get_order_by_number(order_number)
        if not order:
            await self.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=MESSAGES['order_not_found']
            )
            return

        devices = order.get('devices', [])
        per_page = 5
        total_pages = max(1, (len(devices) + per_page - 1) // per_page)
        start, end = (page - 1) * per_page, min(page * per_page, len(devices))

        text = f"📦 دستگاه‌های سفارش {order_number}\nصفحه {page}/{total_pages}\n\n"
        for d in devices[start:end]:
            text += f"• {d.get('model', '')} - {d.get('serial', '')}\n"

        nav_btns = []
        if page > 1:
            nav_btns.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"page_{page-1}_devices_{order_number}"))
        if page < total_pages:
            nav_btns.append(InlineKeyboardButton("➡️ بعدی", callback_data=f"page_{page+1}_devices_{order_number}"))

        keyboard = InlineKeyboardMarkup([nav_btns, [InlineKeyboardButton("🔙 بازگشت", callback_data=CallbackFormats.MAIN_MENU)]])
        await self.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=keyboard)

    def generate_progress_bar(self, step: int) -> str:
        """Generate visual progress bar based on actual progress"""
        
        progress = STEP_PROGRESS.get(step, 0)
        filled = int(progress / 12.5)  # Each block = 12.5%
        empty = 8 - filled
        return "█" * filled + "░" * empty

    def format_order_details(self, order: Dict[str, Any]) -> str:
        """Format order details for display with improved UI/UX"""
        parts = ["📦 **جزئیات سفارش**\n"]
        
        # Order number (always show)
        order_num = order.get('order_number', '')
        if order_num:
            parts.append(f"🔢 شماره پذیرش: `{order_num}`")
        
        # Customer name (only if exists and not 'نامشخص')
        name = order.get('customer_name', '')
        if name and name != 'نامشخص':
            parts.append(f"👤 نام: {name}")
        
        # Device model
        device = order.get('device_model', '')
        if device:
            parts.append(f"📱 دستگاه: {device}")
        
        # Status display using STATUS_TEXT (for display)
        status_code = order.get('status')
        if status_code is not None:
            status_display = STATUS_TEXT.get(status_code, 'نامشخص')
            if status_display and status_display != 'نامشخص':
                icon = STEP_ICONS.get(status_code, '📍')
                parts.append(f"{icon} وضعیت: **{status_display}**")
        
        # Progress calculation and bar
        step = order.get('steps', 0)
        progress_percent = STEP_PROGRESS.get(step, 0)
        progress_bar = self.generate_progress_bar(step)
        
        parts.append(f"\n📊 پیشرفت: {progress_percent}%")
        parts.append(f"{progress_bar}")
        if progress_percent == 100:
            parts.append("✨ **سفارش تکمیل شده**")
            
        # Current workflow step using WORKFLOW_STEPS
        if step is not None:
            workflow_step = WORKFLOW_STEPS.get(step, '')
            if workflow_step:
                icon = STEP_ICONS.get(step, '📍')
                parts.append(f"{icon} مرحله فعلی: **{workflow_step}**")
        
        # Dates (without time)
        reg_date = order.get('registration_date', '')
        if reg_date and '/' in reg_date:
            date_only = reg_date.split(' ')[0] if ' ' in reg_date else reg_date
            parts.append(f"\n📅 تاریخ ثبت: {date_only}")
        
        pre_date = order.get('pre_reception_date', '')
        if pre_date and '/' in pre_date:
            date_only = pre_date.split(' ')[0] if ' ' in pre_date else pre_date
            parts.append(f"📅 پیش‌پذیرش: {date_only}")
        
        # Tracking code (if exists)
        tracking = order.get('tracking_code', '')
        if tracking and tracking != '---':
            parts.append(f"\n🔍 کد رهگیری: `{tracking}`")
        
        # Repair description (if exists)
        repair_desc = order.get('repair_description', '')
        if repair_desc and repair_desc != '---':
            # Truncate long descriptions
            if len(repair_desc) > 50:
                repair_desc = repair_desc[:50] + "..."
            parts.append(f"🔧 شرح تعمیرات: {repair_desc}")
        
        # Technician name (if exists)
        tech_name = order.get('technician_name', '')
        if tech_name and tech_name != '---':
            parts.append(f"👨‍🔧 کارشناس: {tech_name}")
        
        # Cost information (if exists)
        total_cost = order.get('total_cost')
        if total_cost and total_cost > 0:
            formatted_cost = f"{total_cost:,}"
            parts.append(f"💰 هزینه: {formatted_cost} تومان")
        
        # Update timestamp
        parts.append(f"\n🔄 _آخرین بروزرسانی: {datetime.now().strftime('%H:%M:%S')}_")
        
        return "\n".join(parts)


    # =====================================================
    # Utility
    # =====================================================

    async def send_message(self, chat_id: int, text: str,
                parse_mode: Optional[str] = None,
                reply_markup: Optional[InlineKeyboardMarkup] = None) -> Optional[Message]:
        """Wrapper to send messages safely"""
        try:
            return await self.bot.send_message(chat_id=chat_id, text=text,
                                               parse_mode=parse_mode,
                                               reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Send message error → {e}")
            try:
                return await self.bot.send_message(chat_id=chat_id, text="⚠️ ارسال پیام ناموفق. دوباره تلاش کنید.")
            except:
                return None
