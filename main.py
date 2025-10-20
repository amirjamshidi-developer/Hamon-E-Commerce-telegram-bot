"""
HamoonBot - Production Entry Point
"""

import logging
import sys
import os

from telegram import Bot, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes
from telegram.ext import MessageHandler as TgMessageHandler
from telegram.ext import filters

from modules.CallbackHandler import CallbackHandler
from modules.CoreConfig import UserState, initialize_core
from modules.DataProvider import DataProvider
from modules.MessageHandler import MessageHandler
from modules.SessionManager import RedisSessionManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

for logger_name in ["httpx", "httpcore", "telegram", "telegram.ext", "apscheduler"]:
    logging.getLogger(logger_name).setLevel(logging.WARNING)

bot: Bot = None


# ========== COMMAND HANDLERS ==========
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    handler: MessageHandler = context.application.bot_data.get("message_handler")
    if handler:
        await handler.handle_start(update.effective_chat.id)
    else:
        logger.warning("MessageHandler not initialized")


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /menu command"""
    handler: MessageHandler = context.application.bot_data.get("message_handler")
    if handler:
        await handler.show_menu(update.effective_chat.id)
    else:
        logger.warning("MessageHandler not initialized")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    handler: MessageHandler = context.application.bot_data.get("message_handler")
    if handler:
        await handler.show_help(update.effective_chat.id)
    else:
        logger.warning("MessageHandler not initialized")


async def cmd_logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /logout command"""
    handler: MessageHandler = context.application.bot_data.get("message_handler")
    sessions: RedisSessionManager = context.application.bot_data.get("session_manager")

    if handler and sessions:
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id if update.effective_user else None
        async with sessions.session(chat_id, user_id) as session:
            if session and session.is_authenticated:
                await sessions.logout(chat_id)
                await handler.send_message(
                    chat_id, "👋 با موفقیت از حساب کاربری خارج شدید."
                )

        await handler.show_menu(chat_id, authenticated=False)


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /cancel command"""
    handler: MessageHandler = context.application.bot_data.get("message_handler")
    sessions: RedisSessionManager = context.application.bot_data.get("session_manager")

    if handler and sessions:
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id if update.effective_user else None
        async with sessions.session(chat_id, user_id) as session:
            if session:
                session.state = UserState.IDLE
                session.temp_data.clear()
                await sessions.save(session)

        await handler.show_menu(chat_id)


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stats command (admin only)"""
    chat_id = update.effective_chat.id
    sessions: RedisSessionManager = context.application.bot_data.get("session_manager")

    if sessions:
        stats = await sessions.get_stats()
        if chat_id != int(os.getenv("ADMIN_CHAT_ID", "0")) :  # Replace with admin ID for access the stats
            await context.bot.send_message(chat_id, "❌ دسترسی ندارید")
            return
        await context.bot.send_message(
            chat_id,
            f"📊 آمار سیستم:\n\n"
            f"جلسات فعال: {stats.get('total_sessions', 0)}\n"
            f"کاربران احراز هویت شده: {stats.get('authenticated_sessions', 0)}\n"
            f"جلسات در حافظه کش: {stats.get('cached_sessions', 0)}\n"
            f"نرخ موفقیت کش: {stats.get('cache_hit_rate', 0):.1%}\n"
            f"کل درخواست‌ها: {stats.get('total_requests', 0):,}",
        )


# ========== EVENT HANDLERS ==========
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages"""
    handler: MessageHandler = context.application.bot_data.get("message_handler")
    if handler and update.message and update.message.text:
        await handler.process_message(
            update.effective_chat.id, update.message.text, update.message
        )


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback queries"""
    callback_handler = context.application.bot_data.get("callback_handler")
    if callback_handler and update.callback_query:
        await callback_handler.handle_callback(update)
    else:
        logger.warning("CallbackHandler not found")


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"Update {update} caused error {context.error}", exc_info=True)

    try:
        if update and update.effective_chat:
            await context.bot.send_message(
                update.effective_chat.id, "⚠️ خطایی رخ داد. لطفا دوباره تلاش کنید."
            )
    except:
        pass


# ========== APPLICATION LIFECYCLE ==========
async def post_init(application: Application):
    """Initialize bot components after application build"""
    global bot

    try:
        config, validators, metrics = initialize_core()

        session_manager = RedisSessionManager(config, metrics)
        await session_manager.connect()
        logger.info("✅ Session manager with background tasks initialized")

        data_provider = DataProvider(config, session_manager.redis)
        await data_provider.ensure_session()
        logger.info("✅ Data provider initialized")

        bot = application.bot

        message_handler = MessageHandler(
            bot=bot,
            config=config,
            session_manager=session_manager,
            data_provider=data_provider,
            callback_handler=None,
        )

        callback_handler = CallbackHandler(
            message_handler=message_handler,
            session_manager=session_manager,
            data_provider=data_provider,
        )
        # Set circular reference after both message handler and callback handler are created
        message_handler.callback_handler = callback_handler

        application.bot_data.update(
            {
                "bot": bot,
                "config": config,
                "validators": validators,
                "metrics": metrics,
                "session_manager": session_manager,
                "data_provider": data_provider,
                "message_handler": message_handler,
                "callback_handler": callback_handler,
            }
        )

        logger.info("✅ All bot components initialized successfully")

    except Exception as e:
        logger.error(f"❌ Initialization failed: {e}", exc_info=True)
        raise


async def post_shutdown(application: Application):
    """Cleanup on shutdown"""
    try:
        data_provider = application.bot_data.get("data_provider")
        session_manager = application.bot_data.get("session_manager")

        if (
            hasattr(session_manager, "background_tasks")
            and session_manager.background_tasks
        ):
            await session_manager.background_tasks.stop()
            logger.info("✅ Background tasks stopped")

        if data_provider:
            if hasattr(data_provider, "close_session"):
                await data_provider.close_session()
            elif hasattr(data_provider, "cleanup"):
                await data_provider.cleanup()

        if session_manager:
            await session_manager.disconnect()

        logger.info("✅ Cleanup completed")

    except Exception as e:
        logger.error(f"Cleanup error: {e}", exc_info=True)


def create_application() -> Application:
    """Create and configure the application"""
    config, _, _ = initialize_core()

    if not config.telegram_token:
        raise RuntimeError("❌ TELEGRAM_BOT_TOKEN not configured")

    app = (
        Application.builder()
        .token(config.telegram_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .concurrent_updates(True)
        .connection_pool_size(8)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .build()
    )

    return app


def main():
    """Main entry point"""
    try:
        app = create_application()

        # Register handlers
        app.add_handler(CommandHandler("start", cmd_start))
        app.add_handler(CommandHandler("help", cmd_help))
        app.add_handler(CommandHandler("menu", cmd_menu))
        app.add_handler(CommandHandler("logout", cmd_logout))
        app.add_handler(CommandHandler("cancel", cmd_cancel))
        app.add_handler(CommandHandler("stats", cmd_stats))

        app.add_handler(TgMessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
        app.add_handler(CallbackQueryHandler(on_callback))
        app.add_error_handler(error_handler)

        logger.info("🚀 Starting HamoonBot...")
        app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

    except KeyboardInterrupt:
        logger.info("⏹ Received shutdown signal")
    except Exception as e:
        logger.exception(f"❌ Fatal error: {e}")
        return 1
    finally:
        logger.info("🔚 Bot stopped")
        return 0


if __name__ == "__main__":
    if sys.version_info < (3, 8):
        logger.error("❌ Python 3.8+ required")
        sys.exit(1)

    sys.exit(main() or 0)
