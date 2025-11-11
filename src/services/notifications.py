"""
Notifications Service
Modernized for Aiogram 3.x using structured callbacks and integrated SessionManager tracking.
"""
from __future__ import annotations
import asyncio
import logging
from typing import Optional, TYPE_CHECKING
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramServerError
from aiogram.types import InlineKeyboardMarkup
from src.config.callbacks import MenuCallback, AuthCallback, OrderCallback
from src.config.enums import WorkflowSteps
from src.utils.keyboards import KeyboardFactory
from src.utils.messages import get_message
if TYPE_CHECKING:
    from src.core.session import SessionManager    
logger = logging.getLogger(__name__)


class NotificationService:
    """Central notification dispatcher for all user‑facing Telegram events."""

    def __init__(self, bot: Bot, session_manager: SessionManager):
        self.bot = bot
        self.sessions = session_manager

    async def _send(
        self,
        chat_id: int,
        text: str,
        keyboard: Optional[InlineKeyboardMarkup] = None,
    ) -> bool:
        """
        Core sender with error resilience and message tracking.
        Only handles Markdown‑safe texts.
        """
        try:
            msg = await self.bot.send_message(
                chat_id,
                text,
                reply_markup=keyboard,
                parse_mode="MARKDOWN",
            )
            await self.sessions.track_message(chat_id, msg.message_id)
            return True

        except (TelegramServerError, TelegramAPIError) as e:
            logger.error(f"Telegram error sending notification to {chat_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending to {chat_id}: {e}", exc_info=True)
            return False

    async def order_status_changed(
        self,
        chat_id: int,
        order_number: str,
        new_step: int,
        status_text: str,
    ) -> bool:
        """Inform user that the workflow step of an order changed."""
        info = WorkflowSteps.get_step_info(new_step)
        icon, name = info["icon"], info["name"]

        text = f"{icon} وضعیت سفارش **{order_number}** به مرحله **{name}** تغییر کرد.\n🪧 {status_text}"
        keyboard = KeyboardFactory.single_button(
            "🔍 مشاهده جزئیات",
            OrderCallback(action="order_details", order_number=order_number).pack(),
        )
        return await self._send(chat_id, text, keyboard)

    async def session_expired(self, chat_id: int) -> bool:
        """Notify session timeout."""
        text = get_message("session_expired")
        keyboard = KeyboardFactory.single_button(
            "🔐 ورود مجدد",
            AuthCallback(action="start").pack(),
        )
        return await self._send(chat_id, text, keyboard)

    async def rate_limit_exceeded(self, chat_id: int, seconds_remaining: int) -> bool:
        """Warn user for hitting rate limit."""
        minutes = max(1, round(seconds_remaining / 60))
        text = get_message("rate_limited", minutes=minutes)
        return await self._send(chat_id, text)

    async def general_error(self, chat_id: int, retry_callback: Optional[str | MenuCallback] = None) -> bool:
        """Send a generic error with optional retry flow."""
        text = get_message("general_error")
        keyboard = None
        if retry_callback:
            if isinstance(retry_callback, str):
                retry_cb = retry_callback
            else:
                retry_cb = retry_callback.pack()
            keyboard = KeyboardFactory.single_button(
                get_message("retry"),
                retry_cb,
            )
        return await self._send(chat_id, text, keyboard)

    async def broadcast(self, message: str, chat_ids: list[int] | None = None):
        """Send message to all active sessions concurrently."""
        try:
            if not chat_ids:
                chat_ids = await self.sessions.get_all_chat_ids()
                if not chat_ids:
                    logger.info("No active sessions for broadcast.")
                    return 0

            tasks = [self._send(cid, message) for cid in chat_ids]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            count = sum(1 for r in results if r is True)

            logger.info(f"Broadcast delivered to {count}/{len(chat_ids)} users")
            return count
        
        except Exception as e:
            logger.error(f"Broadcast failure: {e}", exc_info=True)
            return 0
        