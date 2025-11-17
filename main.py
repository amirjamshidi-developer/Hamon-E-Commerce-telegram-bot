import sys, os, asyncio, json, logging
from datetime import datetime
from src.config.settings import Settings
from src.core.bot import BotManager
from aiogram.exceptions import TelegramNetworkError

def configure_logging():
    """Container-native logging (stdout only) with structured output."""
    in_container = os.path.exists('/.dockerenv') or os.getenv('KUBERNETES_SERVICE_HOST')
    
    if in_container:
        # JSON format for production log aggregation (ELK, Loki, etc.)
        class JSONFormatter(logging.Formatter):
            def format(self, record):
                log_data = {
                    'timestamp': datetime.utcnow().isoformat(),
                    'level': record.levelname,
                    'logger': record.name,
                    'message': record.getMessage(),
                    'module': record.module,
                    'function': record.funcName,
                }
                if record.exc_info:
                    log_data['exception'] = self.formatException(record.exc_info)
                return json.dumps(log_data, ensure_ascii=False)
        
        formatter = JSONFormatter()
    else:
        # simple format for local development
        formatter = logging.Formatter(
            "%(asctime)s - %(levelname)s - %(name)s: %(message)s"
        )

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()
    root_logger.addHandler(stream_handler)

    for name in ("aiogram", "aiohttp", "asyncio", "telegram"):
        logging.getLogger(name).setLevel(logging.WARNING)

    logging.getLogger("aiogram.dispatcher").setLevel(logging.ERROR)
    logging.getLogger("aiogram.event").setLevel(logging.ERROR)

configure_logging()
logger = logging.getLogger("src")

async def main():
    """Entrypoint for bot lifecycle."""
    settings = Settings.get_instance()

    try:
        async with BotManager(settings) as manager:
            dp = await manager.build_aiogram_layer()
            try:
                await manager.bot.delete_webhook(drop_pending_updates=True)
            except TelegramNetworkError as e:
                logger.warning(f"[Network] Telegram unreachable: {e}")
                logger.warning("[Network] Running in offline mode (VPN off?)")
                return 
            logger.info("Bot polling started.")
            await dp.start_polling(manager.bot)
    except TelegramNetworkError as e:
        logger.error(f"[Critical] Telegram connection failed: {e}")
    except Exception as e:
        logger.critical(f"Bot crashed: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    if sys.platform == 'win32':
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        except Exception:
            pass

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Exit requested by user — silent termination.")
        sys.exit(0)
    except Exception as e:
        logger.exception(f"Unhandled runtime exception: {e}")
        sys.exit(1)
    finally:
        logger.info("Runtime exited successfully.")
        