"""
Common Router Handler
- handle start-menu-cancel-logout-help and admin commands
"""
import logging
from typing import Union, TYPE_CHECKING
from aiogram import Router, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.types import Message, CallbackQuery
from src.config.settings import Settings
from src.config.constants import CallbackFormats, CALLBACK_TO_REPLY_BUTTON
from src.core.session import SessionManager
from src.services.keyboards import KeyboardFactory
from src.utils.messages import get_message

if TYPE_CHECKING:
    from src.core.bot import BotManager
    from src.core.dynamic import DynamicConfigManager

logger = logging.getLogger(__name__)

async def start_flow_unified(
    event: Union[CallbackQuery, Message],
    state: FSMContext,
    new_state: State,
    prompt_text: str,
    session_manager: SessionManager,
):
    """Starts a flow based on event type (Callback or Message)."""
    await state.set_state(new_state)
    if isinstance(event, CallbackQuery):
        await event.message.edit_text(prompt_text, reply_markup=KeyboardFactory.cancel_inline())
        await event.answer()
    else:
        await session_manager.cleanup_messages(event.bot, event.chat.id)
        await event.delete()
        sent = await event.answer(prompt_text, reply_markup=KeyboardFactory.cancel_reply())
        await session_manager.track_message(event.chat.id, sent.message_id)

async def _edit_or_respond(event: Union[CallbackQuery, Message], text: str, reply_markup) -> Message:
    """Edits if callback else deletes then sends."""
    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, reply_markup=reply_markup, parse_mode="MARKDOWN")
        return event.message
    else:
        await event.delete()
        sent = await event.answer(text, reply_markup=reply_markup, parse_mode="MARKDOWN")
        return sent

def prepare_router(settings: Settings,
                   session_manager: SessionManager,
                   dynamic_config: "DynamicConfigManager",
                   cache_manager,
                   manager: "BotManager | None" = None) -> Router:
    """Factory to prepare unified router (common + admin)."""
    router = Router(name="common_router")

    @router.message(CommandStart())
    async def handle_start(message: Message, state: FSMContext):
        await session_manager.cleanup_messages(message.bot, message.chat.id)
        await state.clear()
        await message.delete()

        placeholder = await message.answer(
            get_message('use_menu'),
            reply_markup=KeyboardFactory.main_reply_menu(authenticated=False)
        )

        text = f"{get_message('welcome')}\n{get_message('use_menu')}"
        sent = await message.answer(text, reply_markup=KeyboardFactory.main_inline_menu(False))
        await session_manager.track_message(message.chat.id, sent.message_id)

    @router.message(Command("menu"))
    @router.callback_query(F.data == CallbackFormats.MAIN_MENU)
    @router.message(F.text == CALLBACK_TO_REPLY_BUTTON[CallbackFormats.MAIN_MENU])
    async def handle_menu(event: Union[CallbackQuery, Message], state: FSMContext):
        await state.clear()

        if isinstance(event, Message):
            await session_manager.cleanup_messages(event.bot, event.chat.id)

        placeholder = await event.answer(
            get_message('main_menu'),
            reply_markup=KeyboardFactory.main_reply_menu(authenticated=False)
        )

        session_data = await state.get_data()
        is_auth = session_data.get("is_authenticated", False)
        text = get_message("welcome")
        
        final_message = await _edit_or_respond(event, text, KeyboardFactory.main_inline_menu(is_auth))
        await session_manager.track_message(final_message.chat.id, final_message.message_id)

        if isinstance(event, CallbackQuery):
            await event.answer()

    @router.message(Command("help"))
    @router.callback_query(F.data == CallbackFormats.HELP)
    @router.message(F.text == CALLBACK_TO_REPLY_BUTTON[CallbackFormats.HELP])
    async def handle_help(event: Union[CallbackQuery, Message], state: FSMContext):
        if isinstance(event, Message):
            await session_manager.cleanup_messages(event.bot, event.chat.id)
            
        text = get_message("help", support_phone=settings.support_phone, website_url=settings.website_url)
        
        final_message = await _edit_or_respond(event, text, KeyboardFactory.cancel_inline())
        await session_manager.track_message(final_message.chat.id, final_message.message_id)
        
        if isinstance(event, CallbackQuery):
            await event.answer()

    @router.message(Command("logout"))
    @router.callback_query(F.data == CallbackFormats.LOGOUT_PROMPT)
    async def handle_logout(event: Union[CallbackQuery, Message], state: FSMContext):
        msg = event.message if isinstance(event, CallbackQuery) else event
        user = await state.get_data()
        if not user.get("is_authenticated", False):
            sent = await msg.answer(get_message("no_logout"),
                                    reply_markup=KeyboardFactory.single_button("🏠 منوی اصلی", CallbackFormats.MAIN_MENU))
            await session_manager.track_message(msg.chat.id, sent.message_id)
            if isinstance(event, CallbackQuery): await event.answer()
            return

        await state.clear()
        await session_manager.logout(msg.chat.id)
        text = get_message("logout_success")
        sent = await msg.answer(text, reply_markup=KeyboardFactory.main_inline_menu(False))
        await session_manager.track_message(msg.chat.id, sent.message_id)
        if isinstance(event, CallbackQuery): await event.answer()

    @router.message(Command("cancel"))
    @router.callback_query(F.data == CallbackFormats.CANCEL)
    async def handle_cancel(event: Union[CallbackQuery, Message], state: FSMContext):

        current_state = await state.get_state()
        active_prefixes = ("AuthState.", "OrderState.", "SupportState.")

        if not (current_state and any(current_state.startswith(p) for p in active_prefixes)):
            msg = event.message if isinstance(event, CallbackQuery) else event
            try:
                await msg.answer(
                    get_message("no_operation"),
                    reply_markup=KeyboardFactory.cancel_inline()
                )
            except Exception as e:
                logger.exception(f"Cancel handler [no_state] failed: {e}")
            if isinstance(event, CallbackQuery): await event.answer()
            return

        session_data = await state.get_data()
        authenticated = session_data.get("is_authenticated", False)
        await state.clear()
        await state.update_data(is_authenticated=authenticated)

        text = get_message("cancelled")
        keyboard = KeyboardFactory.main_inline_menu(authenticated)

        final_message = await _edit_or_respond(event, text, keyboard)
        await session_manager.track_message(final_message.chat.id, final_message.message_id)
        
        logger.debug(f"Cancel handled successfully for chat_id={final_message.chat.id}, state={current_state}")
        
        if isinstance(event, CallbackQuery):
            await event.answer()

    @router.callback_query(F.data == "reload_config")
    async def admin_reload_handler(callback: CallbackQuery):
        admin_id = int(settings.admin_chat_id or 0)
        if callback.from_user.id != admin_id and not dynamic_config.is_admin(callback.from_user.id):
            await callback.message.answer("🚫 Only admin can reload configuration.")
            await callback.answer()
            return

        success = await dynamic_config.reload_config()
        msg = "✅ تنظیمات با موفقیت بارگذاری شد." if success else "❌ خطا در بارگذاری تنظیمات."
        await callback.message.answer(msg)
        await callback.answer()
        logger.info(f"Admin {callback.from_user.id} reloaded dynamic configuration: {success}")

    @router.message(Command("admin"))
    @router.message(Command("stats"))
    async def handle_admin_stats(message: Message):
        admin_id = int(settings.admin_chat_id or 0)
        if message.chat.id != admin_id and not dynamic_config.is_admin(message.chat.id):
            await message.answer("🚫 این قابلیت فقط برای ادمین فعال است.")
            return

        try:
            session_stats = await session_manager.get_stats()
            cache_stats = cache_manager.get_stats()
            dyn_status = dynamic_config.get_status()

            text = (
                f"📊 **System Stats** \n"
                f"─────────────────────\n"
                f"🧠 Sessions: {session_stats['total_sessions']}\n"
                f"🔐 Authenticated: {session_stats['authenticated_sessions']}\n"
                f"💾 Cached (local): {session_stats['cached_sessions']}\n"
                f"⚙️ Requests handled: {session_stats['total_requests']}\n\n"
                f"📉 Cache Hits: {cache_stats['hits']} / Misses: {cache_stats['misses']} "
                f"(Hit‑Rate: {round(cache_stats['hit_rate']*100,2)}%)\n"
                f"🧩 DynamicConfig: {dyn_status['features_enabled']}/{dyn_status['total_features']} features\n"
                f"🛠 Maintenance: {'🔴 ON' if dyn_status['maintenance_mode'] else '🟢 OFF'}\n"
                f"🕓 Last‑Reload: {dyn_status['last_updated'] or '---' }  (UTC+03:30)\n"
                f"🧑‍💻 Admins Registered: {dyn_status['admin_users']}\n"
                f"─────────────────────\n"
                f"Redis Connection: {'✅ OK' if cache_stats['connected'] else '❌ DOWN'}"
            )
        except Exception as e:
            logger.exception(f"Admin stats error: {e}")
            text = f"❌ Error fetching stats: {e}"

        await message.answer(text, parse_mode="MARKDOWN")

    @router.message()
    async def handle_unknown_text(message: Message):
        """Catch unregistered texts (non-command)."""
        if message.text and message.text.strip() in CALLBACK_TO_REPLY_BUTTON.keys():
            return
        await message.answer(
            "⚠️ دستور ناشناخته!\nلطفا از منو یا دکمه‌های زیر استفاده کنید👇 ",
            reply_markup=KeyboardFactory.main_reply_menu(authenticated=False)
        )

    return router
