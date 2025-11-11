import logging
from typing import Union
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, CallbackQuery
from src.core.session import SessionManager
from src.services.api import APIService
from src.services.exceptions import APIResponseError, APIValidationError
from src.utils.keyboards import KeyboardFactory
from src.models.domain import Order
from src.config.callbacks import OrderCallback, TrackCallback
from src.utils.validators import Validators
from src.utils.messages import get_message
from src.utils.formatters import Formatters 
from src.handlers.helpers import _edit_or_respond, _prepare_for_processing, _start_fsm_flow

logger = logging.getLogger(__name__)

class OrderState(StatesGroup):
    """State group for order tracking flows."""
    awaiting_order_number = State()
    awaiting_serial = State()

def prepare_router(api_service: APIService, session_manager: SessionManager) -> Router:
    router = Router(name="order_router")

    TRACK_BY_NUMBER_TEXT = "🔢 پیگیری با شماره پذیرش"
    TRACK_BY_SERIAL_TEXT = "#️⃣ پیگیری با سریال"

    @router.callback_query(TrackCallback.filter(F.action == "prompt_number"))
    @router.message(F.text.lower() == TRACK_BY_NUMBER_TEXT.lower())
    async def prompt_order_number(event: Union[CallbackQuery, Message], state: FSMContext):
        await _start_fsm_flow(
            event=event,
            state=state,
            new_state=OrderState.awaiting_order_number,
            prompt_text=get_message("order_tracking_prompt"),
            session_manager=session_manager,
            event_message=TRACK_BY_NUMBER_TEXT,
        )

    @router.callback_query(TrackCallback.filter(F.action == "prompt_serial"))
    @router.message(F.text.lower() == TRACK_BY_SERIAL_TEXT.lower())
    async def prompt_serial(event: Union[CallbackQuery, Message], state: FSMContext):
        await _start_fsm_flow(
            event=event,
            state=state,
            new_state=OrderState.awaiting_serial,
            prompt_text=get_message("serial_tracking_prompt"),
            session_manager=session_manager,
            event_message=TRACK_BY_SERIAL_TEXT,
        )

    @router.message(OrderState.awaiting_order_number, F.text)
    async def process_order_number(message: Message, state: FSMContext):
        bot_message = await _prepare_for_processing(
            message, session_manager, get_message("loading", action="جستجو بر اساس شماره پذیرش")
        )

        result = Validators.validate_order_number(message.text)
        if not result.is_valid:
            await session_manager.cleanup_messages(message.bot, message.chat.id)
            bot_message = await _edit_or_respond(bot_message, result.error_message, KeyboardFactory.cancel_inline())
            await session_manager.track_message(message.chat.id, bot_message.message_id)
            return
        
        try:
            order: Order = await api_service.get_order_by_number(result.cleaned_value)
            text, extra_buttons = Formatters.order_detail(order)
            keyboard = KeyboardFactory.order_actions(order.order_number, order, extra_buttons=extra_buttons)
            await _edit_or_respond(bot_message, text, keyboard)
            await session_manager.track_message(message.chat.id, bot_message.message_id)
            await state.clear()

        except APIResponseError as e:
            msg = get_message("order_not_found") if e.status_code == 404 else get_message("order_search_error")
            await session_manager.cleanup_messages(message.bot, message.chat.id)
            bot_message = await _edit_or_respond(bot_message, msg, KeyboardFactory.cancel_inline())
            await session_manager.track_message(message.chat.id, bot_message.message_id)
        except APIValidationError as e:
            await _edit_or_respond(bot_message, get_message("data_processing_error"), reply_markup=KeyboardFactory.cancel_inline())
            await session_manager.track_message(message.chat.id, bot_message.message_id)
        except Exception as e:
            logger.exception(f"Order Number Lookup error: {e} in chat id:{message.chat.id}")
            await _edit_or_respond(bot_message, get_message("order_search_error"), KeyboardFactory.cancel_inline())
            await session_manager.track_message(message.chat.id, bot_message.message_id)

    @router.message(OrderState.awaiting_serial, F.text)
    async def process_serial(message: Message, state: FSMContext):
        bot_message = await _prepare_for_processing(
            message, session_manager, get_message("loading", action="جستجو بر اساس شماره پذیرش")
        )
        result = Validators.validate_serial(message.text)
        if not result.is_valid:
            await session_manager.cleanup_messages(message.bot, message.chat.id)
            bot_message = await _edit_or_respond(bot_message, result.error_message, KeyboardFactory.cancel_inline())
            await session_manager.track_message(message.chat.id, bot_message.message_id)
            return
        
        try:
            order: Order = await api_service.get_order_by_serial(result.cleaned_value)
            text, extra_buttons = Formatters.order_detail(order)
            keyboard = KeyboardFactory.order_actions(order.order_number, order, extra_buttons=extra_buttons)
            await _edit_or_respond(bot_message, text, keyboard)
            await session_manager.track_message(message.chat.id, bot_message.message_id)
            await state.clear()

        except APIResponseError as e:
            msg = get_message("order_not_found") if e.status_code == 404 else get_message("order_search_error")
            await session_manager.cleanup_messages(message.bot, message.chat.id)
            bot_message = await _edit_or_respond(bot_message, msg, KeyboardFactory.cancel_inline())
            await session_manager.track_message(message.chat.id, bot_message.message_id)
        except Exception as e:
            logger.exception(f"Serial lookup error: {e} in chat id:{message.chat.id}")
            await _edit_or_respond(bot_message, get_message("order_search_error"), KeyboardFactory.cancel_inline())
            await session_manager.track_message(message.chat.id, bot_message.message_id)

    @router.callback_query(OrderCallback.filter(F.action == "refresh"))
    @router.message(F.text == "🔄 بروزرسانی اطلاعات")
    async def handle_refresh_order(callback: CallbackQuery, callback_data: OrderCallback):
        order_number = callback_data.order_number
        if not order_number:
            await callback.answer("❌ شماره سفارش یافت نشد.", show_alert=True)
            return

        await callback.answer(get_message("refresh_success"))        
        await _edit_or_respond(
            callback.message, 
            get_message("loading", action="بروزرسانی اطلاعات سفارش"),
            reply_markup=None
            )
        
        try:
            order: Order = await api_service.get_order_by_number(order_number, force_refresh=True)
            async with session_manager.get_session(callback.from_user.id) as session:
                is_auth = session.is_authenticated
            text, extra_buttons = Formatters.order_detail(order,is_auth=is_auth)

            keyboard = KeyboardFactory.order_actions(order.order_number, order, extra_buttons=extra_buttons)
            await _edit_or_respond(callback.message, text, keyboard)
            
        except APIResponseError as e:
            msg = get_message("order_not_found") if e.status_code == 404 else get_message("order_search_error")
            await _edit_or_respond(callback.message, msg, KeyboardFactory.cancel_inline())
        except Exception as e:
            logger.exception(f"Refresh exception for order {order_number}: {e}")
            await _edit_or_respond(callback.message, get_message("refresh_error"), KeyboardFactory.cancel_inline())

    @router.callback_query(OrderCallback.filter(F.action == "order_details"))
    @router.message(F.text == "📋 مشاهده جزئیات سفارش")
    async def handle_show_order_detail(event: Union[CallbackQuery, Message], callback_data: OrderCallback = None):
        try:
            msg = event.message if isinstance(event, CallbackQuery) else event
            chat_id = msg.chat.id

            if isinstance(event, CallbackQuery):
                order_number = callback_data.order_number
                await event.answer("🔍 جزئیات سفارش")
                await session_manager.cleanup_messages(msg.bot, chat_id)
            else:
                await session_manager.cleanup_messages(msg.bot, chat_id)
                async with session_manager.get_session(chat_id) as session:
                    order_number = session.order_number or session.temp_data.get("order_number") or ""
                if not order_number:
                    await msg.answer("⚠️ شماره سفارش یافت نشد.")
                    return
                
            async with session_manager.get_session(chat_id) as session:
                is_auth = session.is_authenticated

            order: Order = await api_service.get_order_by_number(order_number)
            text, extra_buttons = Formatters.order_detail(order, is_auth=is_auth)
            keyboard = KeyboardFactory.order_actions(order_number, order, extra_buttons=extra_buttons)

            await _edit_or_respond(msg, text, keyboard)

        except Exception as e:
            logger.exception(f"Error showing order details → {e}")
            if isinstance(event, CallbackQuery):
                await event.answer("❌ خطا در نمایش جزئیات سفارش", show_alert=True)
            else:
                await msg.answer("❌ خطا در نمایش جزئیات سفارش")

    @router.callback_query(OrderCallback.filter(F.action == "devices_list"))
    @router.message(F.action == "🔍 مشاهده لیست کامل دستگاه‌ها")
    async def handle_device_list(callback: CallbackQuery, callback_data: OrderCallback):
        order_number = callback_data.order_number
        page = callback_data.page or 1
        if not order_number:
            await callback.answer("❌ شماره سفارش یافت نشد.", show_alert=True)
            return
        await callback.answer(f"درحال بارگذاری صفحه {page}...")
        try:
            order: Order = await api_service.get_order_by_number(order_number)
            order_dict = order.model_dump()

            text = Formatters.device_list_paginated(order_dict, page=page)
            
            total_devices = len(order.devices or [])
            per_page = Formatters.config.devices_per_page
            total_pages = max(1, (total_devices + per_page - 1) // per_page)
            
            keyboard = KeyboardFactory.device_list_actions(order.order_number, page, total_pages)
            await _edit_or_respond(callback.message, text, keyboard)

        except Exception as e:
            logger.exception(f"Device list pagination error for order {order_number}: {e}")
            await callback.answer("❌ خطا در نمایش لیست دستگاه‌ها", show_alert=True)

    return router
