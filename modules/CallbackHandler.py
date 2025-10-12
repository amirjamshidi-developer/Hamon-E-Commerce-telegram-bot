"""
Callback Handler - Handles all inline keyboard interactions
"""
import logging,asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from .CoreConfig import UserState, ComplaintType, MESSAGES, STATUS_TEXT, CallbackFormats
from .SessionManager import RedisSessionManager
from .DataProvider import DataProvider

logger = logging.getLogger(__name__)

class CallbackHandler:
    """Handles all callback queries from inline keyboards"""
    def __init__(self, message_handler, session_manager: RedisSessionManager, data_provider: DataProvider):
        self.msg = message_handler
        self.sessions = session_manager
        self.data = data_provider
    
    async def handle_callback(self, update: Update):
        """Main callback router - handles all button clicks"""
        query = update.callback_query
        if not query:
            return
        
        try:
            # Extract context
            chat_id = query.message.chat_id
            message_id = query.message.message_id
            callback_data = query.data
            
            # Acknowledge callback immediately
            await query.answer()
            
            # Route to appropriate handler
            await self._route_callback(query, chat_id, message_id, callback_data)
            
        except Exception as e:
            logger.error(f"Callback error [{query.data}]: {e}", exc_info=True)
            try:
                await query.answer("❌ خطایی رخ داد", show_alert=True)
            except:
                pass
    
    async def _route_callback(self, query, chat_id: int, message_id: int, data: str):
        """Route callbacks to specific handlers"""
        
        # Static routes (exact match)
        static_routes = {
            CallbackFormats.MAIN_MENU: self.handle_main_menu,
            CallbackFormats.BACK: self.handle_back,
            CallbackFormats.CANCEL: self.handle_cancel,
            CallbackFormats.AUTHENTICATE: self.handle_authenticate,
            CallbackFormats.LOGOUT: self.handle_logout,
            CallbackFormats.MY_INFO: self.handle_my_info,
            CallbackFormats.MY_ORDERS: self.handle_my_orders,
            CallbackFormats.TRACK_BY_NUMBER: self.handle_track_by_number,
            CallbackFormats.TRACK_BY_SERIAL: self.handle_track_by_serial,
            CallbackFormats.REPAIR_REQUEST: self.handle_repair_request,
            CallbackFormats.SUBMIT_COMPLAINT: self.handle_submit_complaint,
            CallbackFormats.RATE_SERVICE: self.handle_rate_service,
            CallbackFormats.CONTACT_INFO: self.handle_contact_info,
            CallbackFormats.HELP: self.handle_help
        }
        
        # Check static routes first
        if data in static_routes:
            await static_routes[data](chat_id, message_id)
            return
        
        # Dynamic routes (pattern match)
        if data.startswith("complaint_"):
            await self.handle_complaint_type(chat_id, message_id, data)
        elif data.startswith("rating_"):
            await self.handle_rating_score(chat_id, message_id, data)
        elif data.startswith("order_"):
            order_num = data.split("_", 1)[1]
            await self.handle_order_details(chat_id, message_id, order_num)
        elif data.startswith("refresh_order:"):
            order_num = data.split(":", 1)[1]
            await self.handle_refresh_order(query, order_num)
        elif data.startswith("devices_"):
            order_num = data.split("_", 1)[1]
            await self.msg.show_devices_page(chat_id, message_id, 1, order_num)
        elif data.startswith("page_"):
            # Format: page_2_devices_12345
            parts = data.split("_")
            if len(parts) >= 4 and parts[2] == "devices":
                page = int(parts[1])
                order_num = parts[3]
                await self.msg.show_devices_page(chat_id, message_id, page, order_num)
        else:
            logger.warning(f"Unhandled callback: {data}")
    
    # =====================================================
    # Menu Navigation
    # =====================================================
    
    async def handle_main_menu(self, chat_id: int, message_id: int):
        """Return to appropriate main menu"""
        try:
            async with self.sessions.session(chat_id) as session:
                session.temp_data.clear()
                
                if session.is_authenticated:
                    session.state = UserState.AUTHENTICATED
                    await self._show_auth_menu(chat_id, message_id, session.user_name)
                else:
                    session.state = UserState.IDLE
                    await self._show_main_menu(chat_id, message_id)
        except Exception as e:
            logger.error(f"Main menu error: {e}")
            await self._show_error(chat_id, message_id)
    
    async def handle_back(self, chat_id: int, message_id: int):
        """Go back to previous menu"""
        await self.handle_main_menu(chat_id, message_id)
    
    async def handle_cancel(self, chat_id: int, message_id: int):
        """Cancel current operation"""
        async with self.sessions.session(chat_id) as session:
            session.temp_data.clear()
            session.state = UserState.AUTHENTICATED if session.is_authenticated else UserState.IDLE
        
        await self.msg.bot.edit_message_text(
            chat_id=chat_id, message_id=message_id,
            text="❌ عملیات لغو شد"
        )
        await asyncio.sleep(1)
        await self.handle_main_menu(chat_id, message_id)
    
    # =====================================================
    # Authentication
    # =====================================================
    
    async def handle_authenticate(self, chat_id: int, message_id: int):
        """Start authentication flow"""
        async with self.sessions.session(chat_id) as session:
            session.state = UserState.WAITING_NATIONAL_ID
        
        await self.msg.bot.edit_message_text(
            chat_id=chat_id, message_id=message_id,
            text=MESSAGES['auth_request'],
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ انصراف", callback_data=CallbackFormats.CANCEL)
            ]])
        )
    
    async def handle_logout(self, chat_id: int, message_id: int):
        """Logout user"""
        await self.sessions.logout(chat_id)
        await self.msg.bot.edit_message_text(
            chat_id=chat_id, message_id=message_id,
            text="👋 با موفقیت خارج شدید"
        )
        await asyncio.sleep(1)
        await self._show_main_menu(chat_id, message_id)
    
    # =====================================================
    # User Information
    # =====================================================
    
    async def handle_my_info(self, chat_id: int, message_id: int):
        """Display user profile"""
        async with self.sessions.session(chat_id) as session:
            if not session.is_authenticated:
                await self._show_main_menu(chat_id, message_id)
                return
            
            info = f"""👤 **اطلاعات کاربری**
            نام: {session.user_name or 'ثبت نشده'}
            کد ملی: `{session.national_id}`
            تماس: {session.phone_number or 'ثبت نشده'}"""
            
            await self.msg.bot.edit_message_text(
                chat_id=chat_id, message_id=message_id,
                text=info, parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 بازگشت", callback_data=CallbackFormats.MAIN_MENU)
                ]])
            )
    
    async def handle_my_orders(self, chat_id: int, message_id: int):
        """Display user's orders"""
        async with self.sessions.session(chat_id) as session:
            if not session.is_authenticated:
                await self._show_main_menu(chat_id, message_id)
                return
            
            # Show loading
            await self.msg.bot.edit_message_text(
                chat_id=chat_id, message_id=message_id,
                text="⏳ در حال دریافت سفارشات..."
            )
            
            orders = await self.data.get_user_orders(session.national_id)
            
            if not orders:
                await self.msg.bot.edit_message_text(
                    chat_id=chat_id, message_id=message_id,
                    text="❌ سفارشی یافت نشد",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 بازگشت", callback_data=CallbackFormats.MAIN_MENU)
                    ]])
                )
                return
            
            # Build orders list
            text = "📦 **سفارشات شما:**\n\n"
            buttons = []
            
            for order in orders[:10]:  # Limit to 10 orders
                status = STATUS_TEXT.get(order.get('status', 0), 'نامشخص')
                text += f"• `{order['order_number']}` - {status}\n"
                buttons.append([InlineKeyboardButton(
                    f"📋 {order['order_number']}", 
                    callback_data=CallbackFormats.ORDER_DETAILS.format(order['order_number'])
                )])
            
            buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data=CallbackFormats.MAIN_MENU)])
            
            await self.msg.bot.edit_message_text(
                chat_id=chat_id, message_id=message_id,
                text=text, parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(buttons)
            )
    
    # =====================================================
    # Order Management
    # =====================================================
    
    async def handle_order_details(self, chat_id: int, message_id: int, order_number: str):
        """Show detailed order information"""
        try:
            # Show loading
            await self.msg.bot.edit_message_text(
                chat_id=chat_id, message_id=message_id,
                text="⏳ دریافت اطلاعات..."
            )
            
            order = await self.data.get_order_by_number(order_number)
            
            if not order:
                await self._show_error(chat_id, message_id, "سفارش یافت نشد")
                return
            
            # Format order details
            text = self.msg.format_order_details(order)
            
            # Build action buttons
            buttons = [
                [InlineKeyboardButton("🔄 بروزرسانی", 
                    callback_data=CallbackFormats.REFRESH_ORDER.format(order_number))]
            ]
            
            # Add devices button if multiple devices
            if order.get('device_count', 1) > 1:
                buttons.append([InlineKeyboardButton("📋 دستگاه‌ها", 
                    callback_data=CallbackFormats.DEVICES.format(order_number))])
            
            buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data=CallbackFormats.MAIN_MENU)])
            
            await self.msg.bot.edit_message_text(
                chat_id=chat_id, message_id=message_id,
                text=text, parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(buttons)
            )
            
        except Exception as e:
            logger.error(f"Order details error: {e}")
            await self._show_error(chat_id, message_id)
    
    async def handle_refresh_order(self, query, order_number: str):
        """Refresh order information"""
        chat_id = query.message.chat_id
        message_id = query.message.message_id
        
        try:
            # Fetch fresh data
            fresh_order = await self.data.get_order_by_number(order_number)
            
            if not fresh_order:
                await query.answer("❌ خطا در بروزرسانی", show_alert=True)
                return
            
            # Format updated details
            text = self.msg.format_order_details(fresh_order)
            
            # Try to edit message
            try:
                await query.edit_message_text(
                    text=text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 بروزرسانی مجدد",
                            callback_data=CallbackFormats.REFRESH_ORDER.format(order_number))],
                        [InlineKeyboardButton("🔙 بازگشت", callback_data=CallbackFormats.MAIN_MENU)]
                    ])
                )
                await query.answer("✅ بروزرسانی شد")
            except:
                # Message unchanged
                await query.answer("✅ اطلاعات به‌روز است", show_alert=False)
                
        except Exception as e:
            logger.error(f"Refresh error: {e}")
            await query.answer("❌ خطا در بروزرسانی", show_alert=True)
    
    # =====================================================
    # Order Tracking
    # =====================================================
    
    async def handle_track_by_number(self, chat_id: int, message_id: int):
        """Start tracking by order number"""
        async with self.sessions.session(chat_id) as session:
            session.state = UserState.WAITING_ORDER_NUMBER
        
        await self.msg.bot.edit_message_text(
            chat_id=chat_id, message_id=message_id,
            text="🔢 شماره پذیرش را وارد کنید:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ انصراف", callback_data=CallbackFormats.MAIN_MENU)
            ]])
        )
    
    async def handle_track_by_serial(self, chat_id: int, message_id: int):
        """Start tracking by serial number"""
        async with self.sessions.session(chat_id) as session:
            session.state = UserState.WAITING_SERIAL
        
        await self.msg.bot.edit_message_text(
            chat_id=chat_id, message_id=message_id,
            text="#️⃣ سریال دستگاه را وارد کنید:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ انصراف", callback_data=CallbackFormats.MAIN_MENU)
            ]])
        )
    
    # =====================================================
    # Service Requests
    # =====================================================
    
    async def handle_repair_request(self, chat_id: int, message_id: int):
        """Start repair request"""
        async with self.sessions.session(chat_id) as session:
            if not session.is_authenticated:
                await self._require_auth(chat_id, message_id)
                return
            
            session.state = UserState.WAITING_REPAIR_DESC
        
        await self.msg.bot.edit_message_text(
            chat_id=chat_id, message_id=message_id,
            text="🔧 لطفا مشکل دستگاه خود را توضیح دهید:\n(حداقل 10 کاراکتر)",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ انصراف", callback_data=CallbackFormats.MAIN_MENU)
            ]])
        )
    
    async def handle_submit_complaint(self, chat_id: int, message_id: int):
        """Start complaint submission"""
        async with self.sessions.session(chat_id) as session:
            if not session.is_authenticated:
                await self._require_auth(chat_id, message_id)
                return
            
            session.state = UserState.WAITING_COMPLAINT_TYPE
        
        # Show complaint type selection
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔧 فنی", callback_data="complaint_technical")],
            [InlineKeyboardButton("💰 مالی", callback_data="complaint_payment")],
            [InlineKeyboardButton("📦 ارسال", callback_data="complaint_shipping")],
            [InlineKeyboardButton("🎧 پشتیبانی", callback_data="complaint_service")],
            [InlineKeyboardButton("📝 سایر", callback_data="complaint_other")],
            [InlineKeyboardButton("❌ انصراف", callback_data=CallbackFormats.MAIN_MENU)]
        ])
        
        await self.msg.bot.edit_message_text(
            chat_id=chat_id, message_id=message_id,
            text="📝 نوع شکایت/پیشنهاد را انتخاب کنید:",
            reply_markup=keyboard
        )
    
    async def handle_complaint_type(self, chat_id: int, message_id: int, data: str):
        """Handle complaint type selection"""
        complaint_map = {
            "complaint_technical": ComplaintType.TECHNICAL,
            "complaint_payment": ComplaintType.PAYMENT,
            "complaint_shipping": ComplaintType.SHIPPING,
            "complaint_service": ComplaintType.SERVICE,
            "complaint_other": ComplaintType.OTHER
        }
        
        complaint_type = complaint_map.get(data)
        if not complaint_type:
            return
        
        async with self.sessions.session(chat_id) as session:
            session.temp_data['complaint_type'] = complaint_type
            session.state = UserState.WAITING_COMPLAINT_TEXT
        
        await self.msg.bot.edit_message_text(
            chat_id=chat_id, message_id=message_id,
            text=f"💬 متن شکایت/پیشنهاد را بنویسید:\n(حداقل 10 کاراکتر)",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ انصراف", callback_data=CallbackFormats.MAIN_MENU)
            ]])
        )
    
    async def handle_rate_service(self, chat_id: int, message_id: int):
        """Start service rating"""
        async with self.sessions.session(chat_id) as session:
            if not session.is_authenticated:
                await self._require_auth(chat_id, message_id)
                return
            
            session.state = UserState.WAITING_RATING_SCORE
        
        # Show rating options
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⭐", callback_data="rating_1"),
             InlineKeyboardButton("⭐⭐", callback_data="rating_2")],
            [InlineKeyboardButton("⭐⭐⭐", callback_data="rating_3"),
             InlineKeyboardButton("⭐⭐⭐⭐", callback_data="rating_4")],
            [InlineKeyboardButton("⭐⭐⭐⭐⭐", callback_data="rating_5")],
            [InlineKeyboardButton("❌ انصراف", callback_data=CallbackFormats.MAIN_MENU)]
        ])
        
        await self.msg.bot.edit_message_text(
            chat_id=chat_id, message_id=message_id,
            text="⭐ امتیاز شما به خدمات ما:",
            reply_markup=keyboard
        )
    
    async def handle_rating_score(self, chat_id: int, message_id: int, data: str):
        """Handle rating score selection"""
        try:
            score = int(data.split("_")[1])
        except:
            return
        
        async with self.sessions.session(chat_id) as session:
            session.temp_data['rating_score'] = score
            session.state = UserState.WAITING_RATING_TEXT
        
        await self.msg.bot.edit_message_text(
            chat_id=chat_id, message_id=message_id,
            text=f"امتیاز شما: {'⭐' * score}\n\n💬 نظر خود را بنویسید (اختیاری):\nیا /skip برای رد کردن",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ انصراف", callback_data=CallbackFormats.MAIN_MENU)
            ]])
        )
    
    # =====================================================
    # Information Display
    # =====================================================
    
    async def handle_contact_info(self, chat_id: int, message_id: int):
        """Display contact information"""
        text = f"""📞 **اطلاعات تماس**

        ☎️ تلفن: {self.msg.config.support_phone}
        📧 ایمیل: {self.msg.config.support_email}
        🌐 وبسایت: {self.msg.config.website_url}

        ⏰ ساعات پاسخگویی:
        شنبه تا چهارشنبه: 8-16:
        پنجشنبه: 8-12"""
        
        await self.msg.bot.edit_message_text(
            chat_id=chat_id, message_id=message_id,
            text=text, parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 بازگشت", callback_data=CallbackFormats.MAIN_MENU)
            ]])
        )
    
    async def handle_help(self, chat_id: int, message_id: int):
        """Display help information"""
        text = MESSAGES['help'].format(
            support_phone=self.msg.config.support_phone,
            website_url=self.msg.config.website_url
        )
        
        await self.msg.bot.edit_message_text(
            chat_id=chat_id, message_id=message_id,
            text=text, parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 بازگشت", callback_data=CallbackFormats.MAIN_MENU)
            ]])
        )
    
    # =====================================================
    # Helper Methods
    # =====================================================
    
    async def _show_main_menu(self, chat_id: int, message_id: int):
        """Show main menu for non-authenticated users"""
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔐 ورود با کد ملی", callback_data=CallbackFormats.AUTHENTICATE)],
            [InlineKeyboardButton("🔢 پیگیری سفارش", callback_data=CallbackFormats.TRACK_BY_NUMBER),
             InlineKeyboardButton("#️⃣ پیگیری سریال", callback_data=CallbackFormats.TRACK_BY_SERIAL)],
            [InlineKeyboardButton("📞 اطلاعات تماس", callback_data=CallbackFormats.CONTACT_INFO)],
            [InlineKeyboardButton("❓ راهنما", callback_data=CallbackFormats.HELP)]
        ])
        
        await self.msg.bot.edit_message_text(
            chat_id=chat_id, message_id=message_id,
            text="🏠 منوی اصلی\n\nگزینه مورد نظر را انتخاب کنید:",
            reply_markup=keyboard
        )
    
    async def _show_auth_menu(self, chat_id: int, message_id: int, name: str = "کاربر"):
        """Show authenticated user menu"""
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("👤 اطلاعات من", callback_data=CallbackFormats.MY_INFO)],
            [InlineKeyboardButton("📦 سفارشات من", callback_data=CallbackFormats.MY_ORDERS)],
            [InlineKeyboardButton("🔢 پیگیری سفارش", callback_data=CallbackFormats.TRACK_BY_NUMBER),
             InlineKeyboardButton("#️⃣ پیگیری سریال", callback_data=CallbackFormats.TRACK_BY_SERIAL)],
            [InlineKeyboardButton("🔧 درخواست تعمیر", callback_data=CallbackFormats.REPAIR_REQUEST)],
            [InlineKeyboardButton("📝 ثبت شکایت", callback_data=CallbackFormats.SUBMIT_COMPLAINT)],
            [InlineKeyboardButton("⭐ امتیازدهی", callback_data=CallbackFormats.RATE_SERVICE)],
            [InlineKeyboardButton("🚪 خروج", callback_data=CallbackFormats.LOGOUT)]
        ])
        
        await self.msg.bot.edit_message_text(
            chat_id=chat_id, message_id=message_id,
            text=f"👋 سلام {name} عزیز!\n\n📋 پنل کاربری - انتخاب کنید:",
            reply_markup=keyboard
        )
    
    async def _require_auth(self, chat_id: int, message_id: int):
        """Show authentication required message"""
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔐 ورود", callback_data=CallbackFormats.AUTHENTICATE)],
            [InlineKeyboardButton("🔙 بازگشت", callback_data=CallbackFormats.MAIN_MENU)]
        ])
        
        await self.msg.bot.edit_message_text(
            chat_id=chat_id, message_id=message_id,
            text="⚠️ برای این عملیات باید وارد شوید",
            reply_markup=keyboard
        )
    
    async def _show_error(self, chat_id: int, message_id: int, error_msg: str = None):
        """Show error message"""
        text = error_msg or "❌ خطایی رخ داد"
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 بازگشت", callback_data=CallbackFormats.MAIN_MENU)
        ]])
        
        try:
            await self.msg.bot.edit_message_text(
                chat_id=chat_id, message_id=message_id,
                text=text, reply_markup=keyboard
            )
        except:
            pass
