"""
Callback Handler - Process Inline Keyboard Callbacks
Complete Production Version
"""
import logging
import asyncio
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from .CoreConfig import UserState, ComplaintType, MESSAGES, STATUS_TEXT  
from .SessionManager import RedisSessionManager
from .DataProvider import DataProvider

logger = logging.getLogger(__name__)

class CallbackHandler:
    """Handle callback queries from inline keyboards"""
    
    def __init__(
        self,
        message_handler,
        session_manager: RedisSessionManager,
        data_provider: DataProvider
    ):
        self.msg = message_handler
        self.sessions = session_manager
        self.data = data_provider
    
    async def handle_callback(self, update: Update):
        """Main callback handler"""
        query = update.callback_query
        if not query:
            return

        chat_id = query.message.chat_id
        message_id = query.message.message_id
        callback_data = query.data
        
        # Answer callback to remove loading state
        await query.answer()
        
        # Route to appropriate handler
        try:
            # Navigation callbacks
            if callback_data == "main_menu":
                await self.handle_main_menu(chat_id, message_id)
            
            elif callback_data == "back":
                await self.handle_back(chat_id, message_id)
            
            # Authentication
            elif callback_data == "authenticate":
                await self.handle_authenticate(chat_id, message_id)
            
            elif callback_data == "logout":
                await self.handle_logout(chat_id, message_id)
            
            # User info
            elif callback_data == "my_info":
                await self.handle_my_info(chat_id, message_id)
            
            elif callback_data == "my_orders":
                await self.handle_my_orders(chat_id, message_id)
            
            # Tracking
            elif callback_data == "track_by_number":
                await self.handle_track_by_number(chat_id, message_id)
            
            elif callback_data == "track_by_serial":
                await self.handle_track_by_serial(chat_id, message_id)
            
            # Services
            elif callback_data == "repair_request":
                await self.handle_repair_request(chat_id, message_id)
            
            elif callback_data == "submit_complaint":
                await self.handle_submit_complaint(chat_id, message_id)
            
            elif callback_data == "rate_service":
                await self.handle_rate_service(chat_id, message_id)
            
            # Complaint types
            elif callback_data.startswith("complaint_"):
                await self.handle_complaint_type(chat_id, message_id, callback_data)
            
            # Rating scores
            elif callback_data.startswith("rating_"):
                await self.handle_rating_score(chat_id, message_id, callback_data)
            
            # Order details
            elif callback_data.startswith("order_"):
                await self.handle_order_details(chat_id, message_id, callback_data)
            
            # Devices pagination
            elif callback_data.startswith("devices_"):
                await self.handle_devices(chat_id, message_id, callback_data)
            
            elif callback_data.startswith("page_"):
                await self.handle_pagination(chat_id, message_id, callback_data)
            
            # Refresh order
            elif callback_data.startswith("refresh_"):
                await self.handle_refresh_order(chat_id, message_id, callback_data)
            
            # Info pages
            elif callback_data == "contact_info":
                await self.handle_contact_info(chat_id, message_id)
            
            elif callback_data == "help":
                await self.handle_help(chat_id, message_id)
            
            # Cancel operation
            elif callback_data == "cancel":
                await self.handle_cancel(chat_id, message_id)

            elif callback_data.startswith("refresh_order:"):
                order_number = callback_data.split(":")[1]
                await self.handle_refresh_order(chat_id, message_id, order_number)

        except Exception as e:
            logger.error(f"Error handling callback {callback_data}: {e}")
            await query.edit_message_text("❌ خطایی رخ داد. لطفاً مجدداً تلاش کنید.")
    

    async def handle_refresh_order(self, chat_id: int, message_id: int, order_number: str):
        """Refresh order details"""
        try:
            # Get fresh data
            order_data = await self.data.get_order_by_number(order_number)
            
            if order_data:
                # Format the updated message
                msg = await self.msg.format_order_details(order_data)
                
                # Keep the same keyboard
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 بروزرسانی", callback_data=f"refresh_order:{order_number}")],
                    [InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")]
                ])
                
                # Edit the message
                await self.msg.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=msg,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=keyboard
                )
            else:
                await self.msg.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text="❌ خطا در بروزرسانی. لطفاً دوباره تلاش کنید.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")
                    ]])
                )
        except Exception as e:
            logger.error(f"Error refreshing order: {e}")


    async def edit_to_main_menu(self, chat_id: int, message_id: int):
        """Edit message to show main menu"""
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔐 ورود با کد ملی", callback_data="authenticate")],
            [
                InlineKeyboardButton("🔢 پیگیری با شماره", callback_data="track_by_number"),
                InlineKeyboardButton("#️⃣ پیگیری با سریال", callback_data="track_by_serial")
            ],
            [InlineKeyboardButton("📞 اطلاعات تماس", callback_data="contact_info")],
            [InlineKeyboardButton("❓ راهنما", callback_data="help")]
        ])
        
        await self.msg.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text="🏠 **منوی اصلی**\n\nلطفاً یکی از گزینه‌ها را انتخاب کنید:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )
    
    async def edit_to_authenticated_menu(self, chat_id: int, message_id: int, name: str = "کاربر"):
        """Edit message to show authenticated menu"""
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("👤 اطلاعات من", callback_data="my_info")],
            [InlineKeyboardButton("📦 سفارشات من", callback_data="my_orders")],
            [
                InlineKeyboardButton("🔢 پیگیری سفارش", callback_data="track_by_number"),
                InlineKeyboardButton("#️⃣ پیگیری سریال", callback_data="track_by_serial")
            ],
            [InlineKeyboardButton("🔧 درخواست تعمیر", callback_data="repair_request")],
            [InlineKeyboardButton("📝 ثبت شکایت", callback_data="submit_complaint")],
            [InlineKeyboardButton("⭐ امتیازدهی", callback_data="rate_service")],
            [InlineKeyboardButton("🚪 خروج", callback_data="logout")]
        ])
        
        await self.msg.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=f"👋 **سلام {name} عزیز!**\n\n📋 به پنل کاربری خود خوش آمدید.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )

    # =====================================================
    # Navigation Handlers
    # =====================================================
    
    async def handle_main_menu(self, chat_id: int, message_id: int):
        """Return to main menu"""
        async with self.sessions.session(chat_id) as session:
            session.state = UserState.AUTHENTICATED if session.is_authenticated else UserState.IDLE
            session.temp_data.clear()
            
            if session.is_authenticated:
                await self.edit_to_authenticated_menu(chat_id, message_id, session.user_name)
            else:
                await self.edit_to_main_menu(chat_id, message_id)
    
    async def handle_back(self, chat_id: int, message_id: int):
        """Handle back button"""
        async with self.sessions.session(chat_id) as session:
            # Clear temporary data
            session.temp_data.clear()
            
            # Reset to appropriate state
            if session.is_authenticated:
                session.state = UserState.AUTHENTICATED
                await self.edit_to_authenticated_menu(chat_id, message_id, session.user_name)
            else:
                session.state = UserState.IDLE
                await self.edit_to_main_menu(chat_id, message_id)
    
    async def handle_cancel(self, chat_id: int, message_id: int):
        """Cancel current operation"""
        async with self.sessions.session(chat_id) as session:
            session.state = UserState.AUTHENTICATED if session.is_authenticated else UserState.IDLE
            session.temp_data.clear()
        
        await self.msg.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text="❌ عملیات لغو شد."
        )
        
        await asyncio.sleep(1)
        await self.handle_main_menu(chat_id, message_id)
    
    # =====================================================
    # Authentication Handlers
    # =====================================================
    
    async def handle_authenticate(self, chat_id: int, message_id: int):
        """Start authentication process"""
        async with self.sessions.session(chat_id) as session:
            session.state = UserState.WAITING_NATIONAL_ID
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ انصراف", callback_data="cancel")]
        ])
        
        await self.msg.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=MESSAGES['auth_request'],
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )
    
    async def handle_logout(self, chat_id: int, message_id: int):
        """Handle user logout"""
        await self.sessions.logout(chat_id)
        
        await self.msg.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text="👋 با موفقیت خارج شدید."
        )
        
        # Show main menu after logout
        await asyncio.sleep(1)
        await self.edit_to_main_menu(chat_id, message_id)
    
    # =====================================================
    # User Info Handlers
    # =====================================================
    
    async def handle_my_info(self, chat_id: int, message_id: int):
        """Show user information"""
        async with self.sessions.session(chat_id) as session:
            if not session.is_authenticated:
                await self.edit_to_main_menu(chat_id, message_id)
                return
            
            text = f"""👤 **اطلاعات حساب کاربری**

نام: {session.user_name or 'ثبت نشده'}
کد ملی: `{session.national_id}`
شماره تماس: {session.phone_number or 'ثبت نشده'}
تاریخ ورود: {session.created_at.strftime('%Y/%m/%d %H:%M')}
"""
            
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]
            ])
            
            await self.msg.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )
    
    async def handle_my_orders(self, chat_id: int, message_id: int):
        """Show authenticated user's orders"""
        async with self.sessions.session(chat_id) as session:
            if not session.is_authenticated:
                await self.edit_to_main_menu(chat_id, message_id)
                return

            orders = await self.data.get_orders_by_user(session.national_id)
            if not orders:
                await self.msg.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text="❌ هیچ سفارشی یافت نشد.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]])
                )
                return

            text = "📦 **سفارشات شما**\n"
            keyboard_buttons = []
            for order in orders:
                status_text = STATUS_TEXT.get(order.get('status'), 'نامشخص')
                text += f"- شماره پذیرش: `{order.get('number')}` | وضعیت: {status_text}\n"
                keyboard_buttons.append([InlineKeyboardButton(f"مشاهده {order.get('number')}", callback_data=f"order_{order.get('number')}")])

            keyboard_buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")])

            await self.msg.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(keyboard_buttons)
            )

    # =====================================================
    # Tracking Handlers
    # =====================================================
    async def handle_track_by_number(self, chat_id: int, message_id: int):
        """Handle track by number callback"""
        async with self.sessions.session(chat_id) as session:
            session.state = UserState.WAITING_ORDER_NUMBER
            session.temp_data.clear() 
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ انصراف", callback_data="main_menu")]  
        ])
        
        await self.msg.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text="🔢 لطفاً شماره پذیرش خود را وارد کنید:\n\n💡 مثال: 123456",
            reply_markup=keyboard
        )

    async def handle_track_by_serial(self, chat_id: int, message_id: int):
        async with self.sessions.session(chat_id) as session:
            session.state = UserState.WAITING_SERIAL
        await self.msg.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text="#️⃣ لطفاً سریال دستگاه را وارد کنید:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ انصراف", callback_data="main_menu")]])
        )

    # =====================================================
    # Service Request Handlers
    # =====================================================
    async def handle_repair_request(self, chat_id: int, message_id: int):
        async with self.sessions.session(chat_id) as session:
            session.state = UserState.WAITING_REPAIR_DESCRIPTION
        await self.msg.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text="🔧 لطفاً توضیحات درخواست تعمیر را وارد کنید:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ انصراف", callback_data="cancel")]])
        )

    async def handle_submit_complaint(self, chat_id: int, message_id: int):
        """Choose complaint category"""
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⚙️ فنی", callback_data="complaint_technical"),
             InlineKeyboardButton("💳 مالی", callback_data="complaint_payment")],
            [InlineKeyboardButton("🚚 ارسال", callback_data="complaint_shipping"),
             InlineKeyboardButton("📞 خدمات", callback_data="complaint_service")],
            [InlineKeyboardButton("📝 سایر", callback_data="complaint_other")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]
        ])
        await self.msg.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text="📝 لطفاً نوع شکایت خود را انتخاب کنید:",
            reply_markup=keyboard
        )

    async def handle_complaint_type(self, chat_id: int, message_id: int, callback_data: str):
        category_key = callback_data.split("_")[1]
        category_map = {
            "technical": ComplaintType.TECHNICAL,
            "payment": ComplaintType.PAYMENT,
            "shipping": ComplaintType.SHIPPING,
            "service": ComplaintType.SERVICE,
            "other": ComplaintType.OTHER
        }
        async with self.sessions.session(chat_id) as session:
            session.temp_data['complaint_type'] = category_map.get(category_key, ComplaintType.OTHER).value
            session.state = UserState.WAITING_COMPLAINT_TEXT
        await self.msg.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text="✏️ لطفاً متن شکایت خود را وارد کنید:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ انصراف", callback_data="cancel")]])
        )

    # =====================================================
    # Rating Handlers
    # =====================================================
    async def handle_rate_service(self, chat_id: int, message_id: int):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⭐", callback_data="rating_1"), InlineKeyboardButton("⭐⭐", callback_data="rating_2"),
             InlineKeyboardButton("⭐⭐⭐", callback_data="rating_3")],
            [InlineKeyboardButton("⭐⭐⭐⭐", callback_data="rating_4"), InlineKeyboardButton("⭐⭐⭐⭐⭐", callback_data="rating_5")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]
        ])
        await self.msg.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text="⭐ لطفاً امتیاز خود را انتخاب کنید:",
            reply_markup=keyboard
        )

    async def handle_rating_score(self, chat_id: int, message_id: int, callback_data: str):
        score = int(callback_data.split("_")[1])
        async with self.sessions.session(chat_id) as session:
            session.temp_data['rating_score'] = score
            session.state = UserState.WAITING_RATING_TEXT
        await self.msg.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=f"⭐ امتیاز {score} ثبت شد.\nاکنون نظر خود را وارد کنید (یا 'بدون نظر'):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ انصراف", callback_data="cancel")]])
        )

    # =====================================================
    # Order & Devices Handlers
    # =====================================================
    async def handle_order_details(self, chat_id: int, message_id: int, callback_data: str):
        order_number = callback_data.split("_")[1]
        order = await self.data.get_order_by_number(order_number)
        if not order:
            await self.msg.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text="❌ سفارش یافت نشد.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]])
            )
            return
        msg = self.msg.format_order_details(order)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 دستگاه‌ها", callback_data=f"devices_{order_number}")],
            [InlineKeyboardButton("🔄 بروزرسانی", callback_data=f"refresh_{order_number}")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]
        ])
        await self.msg.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=msg,
                                             parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)

    async def handle_devices(self, chat_id: int, message_id: int, callback_data: str):
        order_number = callback_data.split("_")[1]
        await self.msg.show_devices_page(chat_id, message_id, page=1, order_number=order_number)

    async def handle_pagination(self, chat_id: int, message_id: int, callback_data: str):
        match = re.match(r"page_(\d+)_devices_(.+)", callback_data)
        if match:
            page = int(match.group(1))
            order_number = match.group(2)
            await self.msg.show_devices_page(chat_id, message_id, page=page, order_number=order_number)

    async def handle_refresh_order(self, chat_id: int, message_id: int, callback_data: str):
        order_number = callback_data.split("_")[1]
        await self.handle_order_details(chat_id, message_id, f"order_{order_number}")

    # =====================================================
    # Info Pages
    # =====================================================
    async def handle_contact_info(self, chat_id: int, message_id: int):
        await self.msg.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=f"☎️ پشتیبانی: {self.msg.config.support_phone}\n🌐 وب‌سایت: {self.msg.config.website_url}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]])
        )

    async def handle_help(self, chat_id: int, message_id: int):
        await self.msg.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=MESSAGES['help'].format(support_phone=self.msg.config.support_phone, website_url=self.msg.config.website_url),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]])
        )
