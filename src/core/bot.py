"""
Bot Manager — Central lifecycle orchestrator for all bot components.
Supports hot dynamic configuration reloads, background maintenance,
and resilient broadcast mechanisms.
"""
import asyncio, logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from aiogram import Bot, Dispatcher
from src.config.settings import Settings
from src.core.cache import CacheManager
from src.core.session import SessionManager, BackgroundTasks
from src.core.dynamic import DynamicConfigManager
from src.core.client import APIClient
from src.services.api import APIService
from src.services.notifications import NotificationService
from src.handlers import common_routers, auth, order, support
from src.utils.messages import get_message

logger = logging.getLogger(__name__)

class BotManager:
    """Central coordinator for bot initialization, usage, and lifecycle.""" 

    def __init__(self, config: Settings):
        self.config = config
        self.bot: Optional[Bot] = None
        self.cache: Optional[CacheManager] = None
        self.sessions: Optional[SessionManager] = None
        self.dynamic: Optional[DynamicConfigManager] = None
        self.api_client: Optional[APIClient] = None
        self.api: Optional[APIClient] = None
        self.background: Optional[BackgroundTasks] = None
        self.notifications: Optional[NotificationService] = None
        self._dynamic_task: Optional[asyncio.Task] = None
        self.start_time = datetime.now()
        self.is_running = False
        self._stats: Dict[str, Any] = dict(messages=0, callbacks=0, errors=0)

    async def __aenter__(self):
        if not await self.initialize():
            raise RuntimeError("BotManager initialization failed!!!")
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.shutdown()

    async def initialize(self) -> bool:
        logger.info("Starting Core BotManager initialization...")
        try:
            self.cache = await self._init_cache()
            self.sessions = await self._init_session_manager(self.cache)
            self.api_client = await self._init_api_client(self.cache)
            self.api = APIService(self.api_client, self.config)
            self.bot = await self._init_bot()
            self.notifications = NotificationService(self.bot, self.sessions)
            self.dynamic = await self._init_dynamic_manager(
                cache=self.cache,
                api=self.api,
                notifications=self.notifications
                )
            self.background = await self._init_background_tasks(self.sessions, self.notifications)
            await self._init_dynamic_reload()
            self._register_dynamic_callbacks() 
            self.is_running = True
            logger.info("Core BotManager fully initialized.")
            return True
        except Exception as e:
            logger.critical(f"CRITICAL init error: {e}", exc_info=True)
            await self.shutdown()
            return False

    async def shutdown(self):
        """Gracefully stop all tasks and components."""
        logger.info("Shutting down BotManager...")
        self.is_running = False

        try:
            if self._dynamic_task and not self._dynamic_task.done():
                self._dynamic_task.cancel()
                try:
                    await self._dynamic_task
                except asyncio.CancelledError:
                    pass
                logger.info("Dynamic config watcher stopped.")

            components = [self.background, self.sessions, self.dynamic,
                          self.api_client, self.cache]

            for comp in components:
                if not comp:
                    continue
                if hasattr(comp, "stop"):
                    await comp.stop()
                elif hasattr(comp, "shutdown"):
                    await comp.shutdown()

            logger.info("Core BotManager shutdown complete.")
        except Exception as e:
            logger.error(f"Error during shutdown: {e}", exc_info=True)

    async def _init_cache(self) -> CacheManager:
        cache = CacheManager(self.config.redis_url)
        await cache.startup()
        return cache

    async def _init_api_client(self, cache: CacheManager) -> APIClient:
        api = APIClient(
        base_url=self.config.server_urls["base"],
        auth_token=self.config.auth_token,
        cache=cache,
        )
        await api.startup()
        return api

    async def _init_session_manager(self, cache: CacheManager) -> SessionManager:
        return SessionManager(cache=cache, notifications=self.notifications)

    async def _init_dynamic_manager(self,
                                    cache: CacheManager,
                                    api: APIClient,
                                    notifications: NotificationService)-> DynamicConfigManager:
        dynamic = DynamicConfigManager(cache=cache, api_client=api, notifications=notifications)
        await dynamic.startup()
        return dynamic

    async def _init_bot(self) -> Bot:
        """Initialize Aiogram bot client"""
        bot = Bot(token=self.config.telegram_token)
        try:
            me = await bot.get_me()
            logger.info(f"Bot Connected as @{me.username}")
        except Exception as e:
            logger.warning(f"Bot identity check failed: {e}")
        return bot

    async def _init_background_tasks(
            self, 
            sessions: SessionManager,
            notifications: NotificationService
            ) -> BackgroundTasks:
        """Start session cleanup task(Background tasks)."""
        tasks = BackgroundTasks(sessions, notifications)
        await tasks.start()
        return tasks

    async def _init_dynamic_reload(self):
        """Spawn periodic dynamic config reload watcher safely."""
        async def _reload_loop():
            while self.is_running:
                try:
                    await asyncio.sleep(300)
                    await self.dynamic.reload_config()
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Dynamic reload error: {e}", exc_info=True)
                    await asyncio.sleep(30)

        self._dynamic_task = asyncio.create_task(_reload_loop())
        logger.info("Dynamic config watcher started.")

    def _register_dynamic_callbacks(self):
        if not self.dynamic:
            return

        async def on_change(changed_keys: List[str], new_cfg):
            try:
                cfg_dict = new_cfg.to_dict() if hasattr(new_cfg, "to_dict") else {}
                for comp in (self.cache, self.sessions, self.api):
                    if hasattr(comp, "update_defaults_from_config"):
                        comp.update_defaults_from_config(cfg_dict)
                logger.info(f"Config hot reload applied: {changed_keys}")
            except Exception as e:
                logger.error(f"Dynamic change callback failed: {e}", exc_info=True)

        self.dynamic.register_change_callback(on_change)

    async def reload_config(self) -> bool:
        if not self.dynamic:
            return False
        ok = await self.dynamic.reload_config()
        logger.info("Configuration reloaded" if ok else "Configuration Reload failed.")
        return ok

    async def build_aiogram_layer(self) -> Dispatcher:
        """Compose an Aiogram dispatcher with dynamically configured dependencies."""
        
        storage = await self.sessions.get_fsm_storage()
        dp = Dispatcher(storage=storage)
        dp.include_router(common_routers.prepare_router(
            settings=self.config,
            session_manager=self.sessions,
            dynamic_config=self.dynamic,
            cache_manager=self.cache
        ))
        dp.include_router(auth.prepare_router(self.api, self.sessions))
        dp.include_router(order.prepare_router(self.api, self.sessions))
        dp.include_router(support.prepare_router(self.api, self.sessions))
        logger.info("Dispatcher built OK.")
        return dp

    async def set_maintenance_mode(self, enabled: bool, note: Optional[str] = None):
        """Enable / disable maintenance broadcast and send notification to all active sessions."""
        self.is_running = not enabled

        if not self.bot or not self.sessions or not self.notifications:
            logger.warning("Maintenance toggle skipped — bot or dependencies unavailable.")
            return
        
        msg_template = get_message("maintenance")
        msg = msg_template + (f"\n\n📝 {note}" if note else "")
        
        try:
            chat_ids = await self.sessions.get_all_chat_ids()
            if not chat_ids:
                logger.info("No active sessions found for maintenance broadcast.")
                return

            await self.notifications.broadcast(msg, chat_ids=chat_ids)
            logger.info(f"Maintenance {'ENABLED' if enabled else 'DISABLED'} "
                        f"— broadcast sent to {len(chat_ids)} sessions.")
        except Exception as e:
            logger.error(f"Maintenance mode update failed: {e}", exc_info=True)


    async def push_order_status_update(self, chat_id: int, order_no: str, step: int, status: str):
        await self.notifications.order_status_changed(chat_id, order_no, step, status)

    def update_stats(self, key: str, inc: int = 1):
        if key in self._stats:
            self._stats[key] += inc

    def get_stats(self) -> Dict[str, Any]:
        uptime = (datetime.now() - self.start_time).total_seconds()
        base = dict(self._stats)
        base.update(
            uptime_seconds=uptime,
            uptime_hours=round(uptime / 3600, 2),
            running=self.is_running,
        )
        return base

    async def get_health_status(self) -> Dict[str, Any]:
        return {
            "running": self.is_running,
            "uptime_sec": (datetime.now() - self.start_time).total_seconds(),
            "cache_ok": await self.cache.ping() if self.cache else False,
            "api_health": self.api.get_health() if self.api else {},
            "sessions_active": self.sessions.get_active_count() if self.sessions else 0,
        }
