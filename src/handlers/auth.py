import logging
from typing import Union
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, CallbackQuery
from src.core.session import SessionManager 
from src.models.user import UserState
from src.config.callbacks import AuthCallback, OrderCallback 
from src.services.api import APIService
from src.services.exceptions import APIResponseError, APIValidationError
from src.utils.keyboards import KeyboardFactory
from src.utils.formatters import Formatters
from src.utils.validators import Validators
from src.utils.messages import get_message
from src.handlers.helpers import _start_fsm_flow, _edit_or_respond, _prepare_for_processing, _ensure_authenticated

logger = logging.getLogger(__name__)

class AuthState(StatesGroup):
    awaiting_national_id = State()

def prepare_router(api_service: APIService, session_manager: SessionManager) -> Router:
    router = Router(name="auth_router")
    router.message.filter(F.chat.type == "private")
  
    @router.callback_query(AuthCallback.filter(F.action == "start"))
    @router.message(F.text == "🔐 ورود با کد/شناسه ملی")
    async def start_auth_flow(event: Union[CallbackQuery, Message], state: FSMContext):
        await _start_fsm_flow(
            event=event,
            state=state,
            new_state=AuthState.awaiting_national_id,
            prompt_text=get_message("auth_request"),
            session_manager=session_manager,
            event_message=get_message("enter_auth")
        )

    @router.message(AuthState.awaiting_national_id)
    async def process_national_id(message: Message, state: FSMContext):
        """Handles authentication via national ID."""
        bot_message = await _prepare_for_processing(
            message, session_manager, get_message("processing")
        )
        
        national_id = message.text.strip()
        validation = Validators.validate_national_id(national_id)
        if not validation.is_valid:
            await session_manager.cleanup_messages(message.bot, message.chat.id)
            bot_message = await _edit_or_respond(
                bot_message,
                validation.error_message or get_message("invalid_national_id"),
                KeyboardFactory.cancel_inline(),
            )
            await session_manager.track_message(message.chat.id, bot_message.message_id)
            return
        
        try:
            auth_response = await api_service.authenticate_user(validation.cleaned_value)
            if not auth_response.authenticated:
                raise APIResponseError(status_code=404, error_detail="User not found")

            async with session_manager.get_session(message.chat.id, message.from_user.id) as session:
                session.is_authenticated = True
                session.order_number = auth_response.order_number
                session.national_id = auth_response.national_id or validation.cleaned_value
                session.user_name = auth_response.name
                session.phone_number = auth_response.phone_number
                session.city = auth_response.city
                session.state = UserState.AUTHENTICATED

                order_dict = auth_response.order.model_dump(mode='json')
                if not order_dict.get('national_id'):
                    order_dict['national_id'] = validation.cleaned_value
                session.temp_data['raw_auth_data'] = order_dict
                session.temp_data['last_auth_order'] = auth_response.order_number
                session.last_orders = [order_dict]

            await state.clear()
            text = get_message('auth_success').format(name=auth_response.name) + "\n" + get_message('auth_menu')
            inline_kb = KeyboardFactory.main_inline_menu(is_auth=True)
            reply_kb = KeyboardFactory.main_reply_menu(is_auth=True)

            reply_placeholder = await message.answer("😃 ورود موفقیت آمیز!", reply_markup=reply_kb)
            await session_manager.track_message(message.chat.id, reply_placeholder.message_id)
            await _edit_or_respond(bot_message, text, inline_kb)
            logger.info(f"Authenticated {auth_response.name} ({auth_response.national_id}) chat={message.chat.id}")

        except (APIResponseError, APIValidationError) as e:
            logger.error(f"Auth failed for NID={validation.cleaned_value}: {e}")
            await session_manager.cleanup_messages(message.bot, message.chat.id)
            bot_message = await _edit_or_respond(bot_message, get_message("auth_failed"), KeyboardFactory.cancel_inline())
            await session_manager.track_message(message.chat.id, bot_message.message_id)
        except Exception as e:
            logger.exception(f"Unhandled auth error for national_id={validation.cleaned_value}: {e} in chat:{message.chat.id}")
            await _edit_or_respond(bot_message, get_message("general_error"), KeyboardFactory.cancel_inline())
            await state.clear()

    @router.callback_query(AuthCallback.filter(F.action == "my_info"))
    @router.message(F.text == "👤 اطلاعات من")
    async def handle_my_info(event: Union[CallbackQuery, Message], state: FSMContext):
        """Show authenticated user info."""
        session = await _ensure_authenticated(event, session_manager)
        if not session:
            return

        msg = event.message if isinstance(event, CallbackQuery) else event
        chat_id = msg.chat.id
            
        if isinstance(event, CallbackQuery):
            await event.answer("👤 اطلاعات ثبت شده در سیستم")
            await session_manager.cleanup_messages(msg.bot, chat_id)
        else:
            try:
                await msg.delete()
            except Exception:
                pass
            await session_manager.cleanup_messages(msg.bot, chat_id)
            reply_menu = KeyboardFactory.cancel_reply()
            message = await msg.answer(get_message("use_menu"), reply_markup=reply_menu)
            await session_manager.track_message(chat_id, message.message_id)

        placeholder = await msg.answer(get_message("loading", action="نمایش اطلاعات کاربری"))
        await session_manager.track_message(chat_id, placeholder.message_id)

        formatted_text, extra_buttons = Formatters.user_info(session)
        keyboard = KeyboardFactory.back_inline(is_auth=True, extra_buttons=extra_buttons)

        await _edit_or_respond(placeholder, formatted_text, keyboard)

    @router.callback_query(OrderCallback.filter(F.action == "orders_list"))
    @router.message(F.text == "📦 لیست سفارشات من")
    async def handle_my_orders(event: Union[CallbackQuery, Message], state: FSMContext):
        """Display My Orders view using cached AuthResponse data."""
        session = await _ensure_authenticated(event, session_manager)
        if not session:
            return

        msg = event.message if isinstance(event, CallbackQuery) else event
        chat_id = msg.chat.id
        await session_manager.cleanup_messages(msg.bot, chat_id)
        if isinstance(event, CallbackQuery):
            await event.answer("💳 سفارشات فعال در سیستم")
        else:
            try:
                await msg.delete()
            except Exception:
                pass
            reply_menu = KeyboardFactory.cancel_reply("📋 مشاهده جزئیات سفارش")
            message = await msg.answer(get_message("use_menu"), reply_markup=reply_menu)
            await session_manager.track_message(chat_id, message.message_id)

        placeholder = await msg.answer(get_message("loading", action="دریافت لیست سفارشات"))
        await session_manager.track_message(chat_id, placeholder.message_id)
              
        formatted_text, _ = Formatters.my_orders_summary(session)
        keyboard = KeyboardFactory.my_orders_actions(session)

        await _edit_or_respond(placeholder, formatted_text, keyboard)


    return router
