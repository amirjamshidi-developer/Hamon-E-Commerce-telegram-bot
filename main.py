"""
HamoonBot - Production Entry Point 
"""
import asyncio
import logging
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler as TgMessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)

from modules.CoreConfig import initialize_core
from modules.SessionManager import RedisSessionManager
from modules.DataProvider import DataProvider
from modules.MessageHandler import MessageHandler
from modules.CallbackHandler import CallbackHandler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Global handlers
msg_handler = None
callback_handler = None
sessions = None

# Command Handlers
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    await msg_handler.handle_start(update.effective_chat.id)

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages"""
    try:
        chat_id = update.effective_chat.id
        text = update.message.text
        # Fix: Use correct method name
        await msg_handler.process_message(chat_id, text, update.message)
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text("❌ خطایی رخ داد. لطفا دوباره تلاش کنید.")

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback queries"""
    try:
        query = update.callback_query
        await query.answer()
        await callback_handler.handle_callback(
            query.from_user.id, 
            query.data, 
            query.message.message_id
        )
    except Exception as e:
        logger.error(f"Callback error: {e}")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"Error: {context.error}")
    if update and update.effective_chat:
        try:
            await context.bot.send_message(
                update.effective_chat.id,
                "❌ خطایی رخ داد. لطفا دوباره تلاش کنید."
            )
        except:
            pass

# Lifecycle
async def post_init(app: Application):
    """Initialize after application build"""
    global msg_handler, callback_handler, sessions
    
    try:
        # Initialize components
        config, validators, metrics = initialize_core()
        
        # Create session manager
        sessions = RedisSessionManager(config, metrics)
        await sessions.connect()
        
        # Create data provider
        provider = DataProvider(config, sessions.redis)
        await provider.ensure_session()
        
        # Create handlers
        msg_handler = MessageHandler(app.bot, config, sessions, provider)
        callback_handler = CallbackHandler(msg_handler, sessions, provider)
        
        logger.info("✅ Bot initialized successfully")
        
    except Exception as e:
        logger.exception(f"Initialization failed: {e}")
        raise

async def post_shutdown(app: Application):
    """Cleanup on shutdown"""
    global sessions
    
    try:
        if sessions:
            await sessions.disconnect()
        logger.info("✅ Cleanup complete")
    except Exception as e:
        logger.error(f"Shutdown error: {e}")

# Main
def main():
    """Main entry point"""
    # Get config
    config, _, _ = initialize_core()
    if not config.telegram_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not configured")
    
    # Build application
    app = (
        Application.builder()
        .token(config.telegram_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    
    # Register handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(TgMessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_error_handler(error_handler)
    
    # Run bot
    try:
        logger.info("🚀 Starting bot...")
        app.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )
    except KeyboardInterrupt:
        logger.info("⏹ Shutdown signal received")
    finally:
        logger.info("🔚 Bot stopped")

if __name__ == "__main__":
    main()
