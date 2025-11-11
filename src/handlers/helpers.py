import logging
from typing import Optional, Union, TYPE_CHECKING
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.exceptions import TelegramBadRequest
from src.models.user import UserSession
from src.utils.messages import get_message
from src.utils.keyboards import KeyboardFactory
if TYPE_CHECKING:
    from src.core.session import SessionManager

logger = logging.getLogger(__name__)

async def _start_fsm_flow(
    event: Union[CallbackQuery, Message],
    state: FSMContext,
    new_state: State,
    prompt_text: str,
    session_manager: "SessionManager",
    event_message: Optional[str] = None,
):
    """Starts a flow based on event type (Callback or Message)."""
    msg = event.message if isinstance(event, CallbackQuery) else event
    chat_id = msg.chat.id

    await state.set_state(new_state)
    if isinstance(event, CallbackQuery):
        await msg.edit_text(prompt_text, reply_markup=KeyboardFactory.cancel_inline(), parse_mode="MARKDOWN")
        await event.answer(event_message)
    else:
        await session_manager.cleanup_messages(event.bot, chat_id)
        try:
            await event.delete()
        except TelegramBadRequest as e:
            logger.warning(f"Could not delete user message in start_flow: {e}")
        sent = await event.answer(prompt_text, reply_markup=KeyboardFactory.cancel_reply(),parse_mode="MARKDOWN")
        await session_manager.track_message(chat_id, sent.message_id)

async def _ensure_authenticated(
    event: Union[CallbackQuery, Message], 
    session_manager: "SessionManager"
) -> Optional["UserSession"]:
    """
    Checks if a user is authenticated.
    - If YES: returns the user session object.
    - If NO: handles the full "not authenticated" notification flow and returns None.
    """
    msg = event.message if isinstance(event, CallbackQuery) else event
    chat_id = msg.chat.id
    user_id = event.from_user.id
    
    async with session_manager.get_session(chat_id, user_id) as session:
        if session.is_authenticated:
            return session

        await session_manager.cleanup_messages(msg.bot, chat_id)
        not_auth_text = get_message("not_authenticated")

        if isinstance(event, CallbackQuery):
            await event.answer(not_auth_text, show_alert=True)
        else:
            bot_msg = await msg.answer(not_auth_text, reply_markup=KeyboardFactory.cancel_inline())
            await session_manager.track_message(chat_id, bot_msg.message_id)

        return None

async def _prepare_for_processing(
    message: Message, 
    session_manager: "SessionManager",
    loading_text: str
) -> Message:
    """
    Handles the boilerplate for processing user input in an FSM state:
    1. Deletes the user's triggering message.
    2. Cleans up previous bot messages.
    3. Sends a "Loading..." message to the user.
    Returns the "Loading..." message object for later editing.
    """
    chat_id = message.chat.id
    try:
        await message.delete()
    except TelegramBadRequest:
        pass 
    
    await session_manager.cleanup_messages(message.bot, chat_id)
    
    bot_message = await message.answer(loading_text, reply_markup=KeyboardFactory.remove())
    await session_manager.track_message(chat_id, bot_message.message_id)
    return bot_message

async def _edit_or_respond(event: Union[CallbackQuery, Message], text: str, reply_markup) -> Message:
    """
    Robust Aiogram-safe message updater:
    → Tries edit if possible.
    → Falls back to sending new message if edit fails for any reason.
    → Always returns Message instance.
    """
    msg_to_act_on = event.message if isinstance(event, CallbackQuery) else event
    text = (text or "").strip()

    try:
        return await msg_to_act_on.edit_text(
            text,
            reply_markup=reply_markup,
            parse_mode="MARKDOWN"
        )

    except TelegramBadRequest as e:
        err = str(e).lower()
        non_editable = (
            "message can't be edited",
            "message to edit not found",
            "message is not modified",
            "the message was deleted",
            "message identifier is not specified"
        )

        if any(x in err for x in non_editable):
            logger.debug(f"Fallback triggered for edit: {err}")

            try:
                if isinstance(event, Message):
                    await event.delete()
            except TelegramBadRequest:
                pass

            try:
                return await msg_to_act_on.answer(
                    text,
                    reply_markup=reply_markup,
                    parse_mode="MARKDOWN"
                )
            except TelegramBadRequest as e2:
                logger.error(f"Answer failed after edit error: {e2}")
                return await msg_to_act_on.answer(text)

        logger.error(f"Unhandled Telegram API error in _edit_or_respond: {e}")
        try:
            return await msg_to_act_on.answer(text)
        except Exception as e3:
            logger.critical(f"Total failure in message response: {e3}")
            raise
