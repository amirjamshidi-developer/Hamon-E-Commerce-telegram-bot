"""support flow handler for complaints and repair requests."""
import logging
from typing import Union
from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, CallbackQuery
from src.core.session import SessionManager
from src.services.api import APIService
from src.services.exceptions import APIResponseError, APIValidationError
from src.utils.keyboards import KeyboardFactory
from src.config.callbacks import ServiceCallback, REPLY_BUTTON_TO_CALLBACK_ACTION
from src.config.enums import ComplaintType
from src.utils.validators import Validators
from src.utils.messages import get_message
from src.utils.formatters import Formatters
from src.handlers.helpers import _edit_or_respond , _ensure_authenticated, _prepare_for_processing, _start_fsm_flow

logger = logging.getLogger(__name__)

class SupportState(StatesGroup):
    """FSM states for Support (complaint / repair) flows."""
    awaiting_complaint_type = State()
    awaiting_complaint_text = State()
    awaiting_serial_for_repair = State()
    awaiting_repair_text = State()

def prepare_router(api_service: APIService, session_manager: SessionManager) -> Router:
    router = Router(name="support_flow")
    router.message.filter(F.chat.type == "private")

    @router.callback_query(ServiceCallback.filter(F.action == "complaint_start"))
    @router.message(F.text.in_({"📝 ثبت شکایات", "📝 ثبت شکایات/نظرات"}))
    async def start_complaint(event: Union[CallbackQuery, Message], state: FSMContext):
        """Starts complaint process — select complaint type."""
        if not await _ensure_authenticated(event, session_manager):
            return

        msg = event.message if isinstance(event, CallbackQuery) else event
        chat_id = msg.chat.id

        if isinstance(event, CallbackQuery):
            await event.answer(get_message("enter_complaint"))

        await state.set_state(SupportState.awaiting_complaint_type)
        await session_manager.cleanup_messages(event.bot, chat_id)  

        refresh_msg = await msg.answer(get_message('use_menu'), reply_markup=KeyboardFactory.complaint_types_reply())
        await session_manager.track_message(chat_id, refresh_msg.message_id)

        inline_msg = await _edit_or_respond(msg, get_message("complaint_type_select"), KeyboardFactory.complaint_types_inline())
        await session_manager.track_message(chat_id, inline_msg.message_id)

    @router.callback_query(StateFilter(SupportState.awaiting_complaint_type), ServiceCallback.filter(F.action == "select_complaint"))
    async def process_complaint_type(callback: CallbackQuery, callback_data: ServiceCallback, state: FSMContext):
        """Processes the selected complaint type and asks for text."""
        msg = callback.message if isinstance(callback, CallbackQuery) else callback
        chat_id = msg.chat.id

        try:
            c_enum = ComplaintType.from_id(int(callback_data.type_id))
        except (ValueError, TypeError):
            await callback.answer("❌ نوع شکایت نامعتبر است", show_alert=True)
            await session_manager.track_message(chat_id, callback.message.message_id)
            return

        await state.update_data(
            complaint_type_id=c_enum.id,
            complaint_type_text=c_enum.display,
        )
        await state.set_state(SupportState.awaiting_complaint_text)        

        back_button = [{
                "text": "🔙 بازگشت به انتخاب نوع شکایت",
                "callback": ServiceCallback(action="complaint_start").pack()
            }]
        keyboard = KeyboardFactory.back_inline(extra_buttons=back_button)

        await _edit_or_respond(callback.message, get_message("complaint_text_prompt"), keyboard)
        if isinstance(callback, CallbackQuery) and getattr(callback, "bot", None):
            await callback.answer("✍ لطفاً متن شکایت خود را ارسال کنید.")

    @router.message(StateFilter(SupportState.awaiting_complaint_type),
                    F.text.in_([
                        "🔧 خرابی و تعمیرات دستگاه",
                        "🚚 ارسال و دریافت دستگاه",
                        "💰 بخش مالی و حسابداری",
                        "👤 پشتیبانی و رفتار پرسنل",
                        "📈 بخش فروش و توسعه بازار",
                        "📝 سایر موارد"
                    ]))
    async def process_complaint_type_text(message: Message, state: FSMContext):
        """Handle complaint type selection via reply keyboard text."""

        await session_manager.cleanup_messages(message.bot, message.chat.id)
        await message.answer("ثبت شکایات/نظرات", reply_markup=KeyboardFactory.cancel_reply())
        await session_manager.track_message(message.chat.id, message.message_id)

        mapped = REPLY_BUTTON_TO_CALLBACK_ACTION.get(message.text.strip())
        if not mapped or not isinstance(mapped, ServiceCallback):
            await message.answer("❌ گزینه نامعتبر است، لطفاً از منو استفاده کنید.")
            return

        fake_query = CallbackQuery(
            id="reply_to_cb",
            from_user=message.from_user,
            message=message,
            chat_instance=str(message.chat.id),
            data=mapped.pack()
        )
        await process_complaint_type(fake_query, mapped, state)

    @router.message(StateFilter(SupportState.awaiting_complaint_text), F.text)
    async def process_complaint_text(message: Message, state: FSMContext):
        bot_message = await _prepare_for_processing(
            message, session_manager, get_message("loading", action="ثبت شکایت")
        )

        validation = Validators.validate_text_length(message.text, context="توضیح شکایت")
        if not validation.is_valid:
            await session_manager.cleanup_messages(message.bot, message.chat.id)
            bot_message = await _edit_or_respond(bot_message, validation.error_message, KeyboardFactory.cancel_inline())
            await session_manager.track_message(message.chat.id, bot_message.message_id)
            return
        
        async with session_manager.get_session(message.chat.id, message.from_user.id) as session:
            u_data = await state.get_data()
            device_serial = (
                (session.temp_data.get("raw_auth_data", {})
                .get("items", [{}])[0]
                .get("serialNumber"))
                if session.temp_data else None
            )

            try:
                resp = await api_service.submit_complaint(
                    complaint_type_id=u_data.get("complaint_type_id"),
                    text=validation.cleaned_value,
                    chat_id=str(message.chat.id),
                    user_name = session.user_name or "",
                    phone_number=session.phone_number or "",
                    device_serial=device_serial or "",
                )
                text = Formatters.complaint_submitted(
                    ticket_number=resp.ticket_number,
                    complaint_type=u_data.get("complaint_type_text"),
                )
                await state.clear()

            except APIResponseError as e:
                logger.error(f"Complaint API rejected request: {e}")
                text = get_message("complaint_error")

            except Exception as e:
                logger.exception(f"Unexpected complaint submission error: {e}")
                text = get_message("complaint_error")

        await message.answer(text=get_message('use_menu'), reply_markup=KeyboardFactory.main_reply_menu(is_auth=True))
        await _edit_or_respond(bot_message, text, KeyboardFactory.main_inline_menu(is_auth=True))


    @router.callback_query(ServiceCallback.filter(F.action == "repair_start"))
    @router.message(F.text == "📞 درخواست تعمیرات")
    async def start_repair(event: Union[CallbackQuery, Message], state: FSMContext):
        """Begins the repair request flow by asking for the device serial."""
        if not await _ensure_authenticated(event, session_manager):
            return

        await _start_fsm_flow(
            event=event,
            state=state,
            new_state=SupportState.awaiting_serial_for_repair,
            prompt_text=get_message("repair_serial_input"),
            session_manager=session_manager,
            event_message=get_message("enter_repair"),
        )

    @router.message(StateFilter(SupportState.awaiting_serial_for_repair), F.text)
    async def process_serial_for_repair(message: Message, state: FSMContext):
        """Handles serial input and moves to the description input step."""
        bot_message = await _prepare_for_processing(
            message, session_manager, get_message("loading", action="دریافت سریال برای درخواست تعمیر")
        )

        validation = Validators.validate_serial(message.text.strip())
        if not validation.is_valid:
            await session_manager.cleanup_messages(message.bot, message.chat.id)
            bot_message = await _edit_or_respond(bot_message, validation.error_message, KeyboardFactory.cancel_inline())
            await session_manager.track_message(message.chat.id, bot_message.message_id)
            return
        
        await state.update_data(device_serial=validation.cleaned_value)
        await state.set_state(SupportState.awaiting_repair_text)

        await _edit_or_respond(bot_message, get_message('repair_text_prompt'), KeyboardFactory.cancel_inline())

    @router.message(StateFilter(SupportState.awaiting_repair_text), F.text)
    async def process_repair_text(message: Message, state: FSMContext):
        bot_message = await _prepare_for_processing(
            message, session_manager, get_message("loading", action="ثبت درخواست تعمیر")
        )
        chat_id = message.chat.id

        validation = Validators.validate_text_length(message.text, context="توضیح تعمیر")
        if not validation.is_valid:
            await session_manager.cleanup_messages(message.bot, message.chat.id)
            bot_message = await _edit_or_respond(bot_message, validation.error_message, KeyboardFactory.cancel_inline())
            await session_manager.track_message(message.chat.id, bot_message.message_id)
            return

        user_data = await state.get_data()
        device_serial = (user_data.get("device_serial") or "").upper()
        
        if device_serial.startswith("00HEC"):
            device_model="ANFU AF70"
        elif device_serial.startswith("05HEC"):
            device_model="ANFU AF75"
        else:
            device_model = ""       

        async with session_manager.get_session(chat_id, message.from_user.id) as session:
            try:
                resp = await api_service.submit_repair_request(
                    description=validation.cleaned_value,
                    device_serial=device_serial,
                    device_model=device_model,
                    chat_id=chat_id or "",
                    user_name=session.user_name or "",
                    phone_number=session.phone_number or "",
                )
                text = Formatters.repair_submitted(ticket_number=resp.ticket_number)
                await state.clear()

            except (APIResponseError, APIValidationError) as e:
                logger.error(f"Repair submission Api Error: {e}")
                text = get_message("repair_error")
            except Exception as e:
                logger.error(f"Repair submission failed: {e}")
                text = get_message("repair_error")

        await message.answer(text=get_message('use_menu'), reply_markup=KeyboardFactory.main_reply_menu(session.is_authenticated))
        await _edit_or_respond(bot_message, text, KeyboardFactory.main_inline_menu(session.is_authenticated))


    return router
