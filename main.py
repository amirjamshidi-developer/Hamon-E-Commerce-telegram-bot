import logging
from logging.handlers import RotatingFileHandler
from src.config.settings import Settings
from src.core.bot import BotManager

def configure_logging():
    """Structured logging setup for file + console output."""
    fmt = "%(asctime)s - %(levelname)s - %(name)s: %(message)s"
    formatter = logging.Formatter(fmt)

    file_handler = RotatingFileHandler(
        "bot.log", maxBytes=10_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)
    root_logger.addHandler(stream_handler)

    for name in (
        "aiogram", 
        "aiohttp", 
        "asyncio", 
        "telegram",
    ):
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
            await manager.bot.delete_webhook(drop_pending_updates=True)
            logger.info("Bot polling started.")
            await dp.start_polling(manager.bot)
    except Exception as e:
        logger.critical(f"Bot crashed: {e}", exc_info=True)

if __name__ == "__main__":
    try:
        import asyncio
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Exit requested by user — silent termination.")
    except Exception as e:
        logger.exception(f"Unhandled runtime exception: {e}")
    finally:
        logger.info("Runtime exited successfully.")
        