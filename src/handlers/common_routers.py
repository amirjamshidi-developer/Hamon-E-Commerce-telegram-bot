"""
Common Router Handler
Handles: start, menu, help, cancel, logout, retry, admin commands
"""
import logging
from typing import Union
from aiogram import Router, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message, CallbackQuery
from src.config.settings import Settings
from src.config.callbacks import MenuCallback, AuthCallback
from src.core.session import SessionManager
from src.core.dynamic import DynamicConfigManager
from src.services.keyboards import KeyboardFactory
from src.utils.messages import get_message
from src.utils.helpers import _edit_or_respond    

logger = logging.getLogger(__name__)


def prepare_router(
    settings: Settings,
    session_manager: SessionManager,
    dynamic_config: "DynamicConfigManager",
    cache_manager,
) -> Router:
    router = Router(name="common_router")

    @router.message(CommandStart())
    async def handle_start(message: Message, state: FSMContext):
        chat_id = message.chat.id
        await state.clear()
        await session_manager.cleanup_messages(message.bot, chat_id)

        replay = await message.answer(get_message('use_menu'),
        reply_markup=KeyboardFactory.main_reply_menu(is_auth=False)
        )
        await session_manager.track_message(chat_id, replay.message_id)

        sent = await message.answer(get_message('welcome'),
        reply_markup=KeyboardFactory.main_inline_menu(is_auth=False)
        )
        await session_manager.track_message(chat_id, sent.message_id)

        try:
            await message.delete()
        except TelegramBadRequest:
            pass

    @router.message(Command("menu"))
    @router.callback_query(MenuCallback.filter(F.target == "main_menu"))
    @router.message(F.text == "🔙 بازگشت به منوی اصلی" or "🏠 منوی اصلی")
    async def handle_menu(event: Union[CallbackQuery, Message], state: FSMContext):
        msg = event.message if isinstance(event, CallbackQuery) else event
        chat_id = msg.chat.id
        if isinstance(event, CallbackQuery): await event.answer("🔰 به ربات تلگرامی هامون خوش آمدید 🔰",show_alert=False)
        await state.clear()

        session_data = await state.get_data()
        is_auth = session_data.get("is_authenticated", False)

        if isinstance(event, Message):
            await session_manager.cleanup_messages(event.bot, chat_id)
        if isinstance(msg, Message): 
            await session_manager.cleanup_messages(msg.bot, chat_id)

        replay = await msg.answer(get_message('menu_refresh_success'), reply_markup=KeyboardFactory.main_reply_menu(is_auth))
        await session_manager.track_message(chat_id, replay.message_id)

        sent = await _edit_or_respond(msg, get_message("welcome"), KeyboardFactory.main_inline_menu(is_auth))
        await session_manager.track_message(chat_id, sent.message_id)

    @router.callback_query(MenuCallback.filter(F.target == "auth_menu"))
    async def handle_auth_menu(callback: CallbackQuery, state: FSMContext):
        """Navigate back to authenticated menu."""
        chat_id = callback.message.chat.id
        await session_manager.cleanup_messages(callback.bot, chat_id)
        await callback.answer(get_message("loading", action="بازگشت به منوی کاربری"))

        sent = await _edit_or_respond(callback.message,
            get_message("welcome"),
            KeyboardFactory.main_inline_menu(is_auth=True)
        )
        await session_manager.track_message(chat_id, sent.message_id)

    @router.message(Command("help"))
    @router.callback_query(MenuCallback.filter(F.target == "help"))
    @router.message(F.text == "❓ راهنما")
    async def handle_help(event: Union[CallbackQuery, Message], state: FSMContext):
        msg = event.message if isinstance(event, CallbackQuery) else event
        chat_id = msg.chat.id
        if isinstance(event, Message): await session_manager.cleanup_messages(event.bot, chat_id)
            
        text = get_message("help", support_phone=settings.support_phone, website_url=settings.website_url)
        sent = await _edit_or_respond(event, text, KeyboardFactory.cancel_inline())
        await session_manager.track_message(chat_id, sent.message_id)
        if isinstance(event, CallbackQuery): await event.answer(get_message('help_section'))

    @router.message(Command("logout"))
    @router.callback_query(AuthCallback.filter(F.action == "logout_prompt"))
    @router.message(F.text == "🚪 خروج از حساب")
    async def handle_logout(event: Union[CallbackQuery, Message], state: FSMContext):
        msg = event.message if isinstance(event, CallbackQuery) else event
        chat_id = msg.chat.id
        user = await state.get_data()
        is_auth = user.get("is_authenticated", False)

        await session_manager.cleanup_messages(msg.bot, chat_id)

        if not is_auth:
            sent = await _edit_or_respond(event, get_message("no_logout"),KeyboardFactory.main_inline_menu(is_auth))
            await session_manager.track_message(chat_id, sent.message_id)
            if isinstance(event, CallbackQuery):
                await event.answer()
            return

        await state.clear()
        await session_manager.logout(chat_id)

        sent = await _edit_or_respond(event, get_message("logout_success"),KeyboardFactory.main_inline_menu(is_auth=False))
        await session_manager.track_message(chat_id, sent.message_id)
        if isinstance(event, CallbackQuery): await event.answer()

    @router.message(Command("cancel"))
    @router.callback_query(MenuCallback.filter(F.target == "cancel"))
    @router.message(F.text == "❌ انصراف")
    async def handle_cancel(event: Union[CallbackQuery, Message], state: FSMContext):
        msg = event.message if isinstance(event, CallbackQuery) else event
        chat_id = msg.chat.id
        await session_manager.cleanup_messages(msg.bot, chat_id)
        
        current_state = await state.get_state()
        session_data = await state.get_data()
        is_auth = session_data.get("is_authenticated", False)

        await state.clear()
        await state.update_data(is_authenticated=is_auth)

        if not current_state:
            text, markup = get_message("no_operation"), KeyboardFactory.cancel_inline()
        else:
            text, markup = get_message("cancelled"), KeyboardFactory.main_inline_menu(is_auth)

        sent = await _edit_or_respond(event, text, markup)
        await session_manager.track_message(chat_id, sent.message_id)
        logger.debug(f"Cancel handled | chat={chat_id} | state={current_state}")
        if isinstance(event, CallbackQuery): await event.answer()

    @router.callback_query(MenuCallback.filter(F.target == "retry"))
    @router.message(F.text == "🔄 تلاش مجدد")
    async def handle_retry(event: Union[CallbackQuery, Message], state: FSMContext):
        msg = event.message if isinstance(event, CallbackQuery) else event
        chat_id = msg.chat.id
        session_data = await state.get_data()
        is_auth = session_data.get("is_authenticated", False)

        sent = await _edit_or_respond(event, get_message("loading"), KeyboardFactory.main_inline_menu(is_auth))
        await session_manager.track_message(chat_id, sent.message_id)
        if isinstance(event, CallbackQuery): await event.answer("🔄 تلاش مجدد ", show_alert=False)
        logger.info(f"Retry triggered for chat_id={chat_id}")

    @router.callback_query(F.data == "reload_config")
    async def admin_reload_handler(callback: CallbackQuery):
        chat_id = callback.message.chat.id
        admin_id = int(settings.admin_chat_id or 0)

        if callback.from_user.id != admin_id and not dynamic_config.is_admin(callback.from_user.id):
            response = await callback.message.answer("🚫 Only admin can reload configuration.")
            await session_manager.track_message(chat_id, response.message_id)
            await callback.answer()
            return

        success = await dynamic_config.reload_config()
        msg = "✅ تنظیمات با موفقیت بارگذاری شد." if success else "❌ خطا در بارگذاری تنظیمات."
        sent = await callback.message.answer(msg)
        await session_manager.track_message(chat_id, sent.message_id)
        await callback.answer()
        logger.info(f"AdminReload | admin_id={callback.from_user.id} | success={success}")

    @router.message(Command("admin"))
    @router.message(Command("stats"))
    async def handle_admin_stats(message: Message):
        chat_id = message.chat.id
        admin_id = int(settings.admin_chat_id or 0)

        if chat_id != admin_id and not dynamic_config.is_admin(chat_id):
            sent = await message.answer("🚫 این قابلیت فقط برای ادمین فعال است.")
            await session_manager.track_message(chat_id, sent.message_id)
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
                f"🧑‍💻 Admins: {dyn_status['admin_users']}\n"
                f"─────────────────────\n"
                f"Redis Connection: {'✅ OK' if cache_stats['connected'] else '❌ DOWN'}"
            )
        except Exception as e:
            logger.exception(f"Admin stats error: {e}")
            text = f"❌ Error fetching stats: {e}"

        sent = await message.answer(text, parse_mode="MARKDOWN")
        await session_manager.track_message(chat_id, sent.message_id)

    return router
