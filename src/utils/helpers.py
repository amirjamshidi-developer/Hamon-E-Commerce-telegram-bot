"""General helper utilities actively used across modules"""
import re, logging, jdatetime
from datetime import datetime
from typing import Any, List, Generator, Optional, Union
from aiogram.types import Message, CallbackQuery
from aiogram.exceptions import TelegramBadRequest

logger = logging.getLogger(__name__)

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

def clean_numeric_string(v: Any) -> Optional[str]:
    """Removes all non-digit characters from a string."""
    if v is None:
        return None
    return re.sub(r"\D", "", str(v))

def sanitize_text(v: str) -> str:
    """Normalize and clean up text returned from API or user input."""
    if not v:
        return ""
    cleaned = re.sub(r"[\t\r\n]+", " ", str(v))
    return cleaned.strip()

def parse_date_string(v: Any, default: str = "نامشخص") -> str:
    """Parse a date string safely - only normalizes different string formats """
    if not v or str(v).lower() == "none":
        return default

    try:
        value = str(v).strip()

        if " " in value:
            value = value.split(" ")[0]
        if "T" in value:
            value = value.split("T")[0]
        if "/" in value:
            parts = value.split("/")
            if len(parts) == 3 and all(p.isdigit() for p in parts):
                year = int(parts[0])
                if 1300 <= year <= 1500:
                    return f"{parts[0]:0>4}/{parts[1]:0>2}/{parts[2]:0>2}"
        if "-" in value:
            parts = value.split("-")
            if len(parts) == 3 and all(p.isdigit() for p in parts):
                return f"{parts[0]:0>4}/{parts[1]:0>2}/{parts[2]:0>2}"

        return value
    except Exception as e:
        logger.warning(f"Failed to parse date string: {v} - {e}")
        return default

def safe_get(data: Any, *keys, default: Any = None) -> Any:
    """Safely get nested dictionary values"""
    if data is None:
        return default
    current = data

    for key in keys:
        if current is None:
            return default

        if isinstance(current, dict):
            current = current.get(key, default)

        elif isinstance(current, (list, tuple)) and isinstance(key, int):
            try:
                current = current[key]
            except (IndexError, KeyError):
                return default

        elif hasattr(current, key):
            try:
                current = getattr(current, key)
            except AttributeError:
                return default

        else:
            return default

    return current if current is not None else default

def _safe_name(name):
    if isinstance(name, bytes):
        return name.decode("utf-8", errors="ignore")
    try:
        return str(name)
    except Exception:
        return "کاربر"

def get_current_jalali_date() -> str:
    """Returns current Jalali date in YYYY/MM/DD format."""
    j_now = jdatetime.datetime.fromgregorian(datetime=datetime.now())
    return f"{j_now.year}/{j_now.month:02d}/{j_now.day:02d}"

def gregorian_to_jalali(dt: datetime) -> str:
    """Convert any Gregorian datetime object to Jalali date string."""
    j_date = jdatetime.datetime.fromgregorian(datetime=dt)
    return f"{j_date.year}/{j_date.month:02d}/{j_date.day:02d}"

def generate_cache_key(*parts: Any) -> str:
    """Generate consistent cache key for Redis."""
    return ":".join(str(p) for p in parts if p is not None)

def chunk_list(items: List[Any], chunk_size: int = 5) -> Generator[List[Any], None, None]:
    """Split list into chunks for pagination / batching."""
    for i in range(0, len(items), chunk_size):
        yield items[i : i + chunk_size]
