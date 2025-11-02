"""
Dynamic Configuration Manager
- runtime feature toggles, rate limiting, hot reload
- optimized for async dynamic architecture
"""
import asyncio, json, logging
from dataclasses import dataclass, field    
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Set
from collections import defaultdict

from .cache import CacheManager
from .client import APIClient
from ..config.settings import Settings


logger = logging.getLogger(__name__)

@dataclass
class DynamicConfig:
    """Dynamic configuration data structure"""
    features: Dict[str, bool] = field(default_factory=dict)
    rate_limits: Dict[str, Dict[str, int]] = field(default_factory=dict)
    messages: Dict[str, str] = field(default_factory=dict)
    admin_users: Set[int] = field(default_factory=set)
    maintenance: Dict[str, Any] = field(default_factory=dict)
    last_updated: Optional[datetime] = None
    
    def to_dict(self) -> dict:
        return {
            'features': self.features,
            'rate_limits': self.rate_limits,
            'messages': self.messages,
            'admin_users': list(self.admin_users),
            'maintenance': self.maintenance,
            'last_updated': self.last_updated.isoformat() if self.last_updated else None,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'DynamicConfig':
        try:
            return cls(
                features=data.get("features", {}),
                rate_limits=data.get("rate_limits", {}),
                messages=data.get("messages", {}),
                admin_users=set(data.get("admin_users", [])),
                maintenance=data.get("maintenance", {}),
                last_updated=datetime.fromisoformat(data["last_updated"])
                if data.get("last_updated")
                else datetime.now(),
            )
        except Exception:
            logger.warning("Failed to parse timestamp; defaulting now()")
            data["last_updated"] = datetime.now().isoformat()
            return cls.from_dict(data)


class DynamicConfigManager:
    """Async dynamic configuration with cache & file persistence, hot reload, and callbacks."""
    
    def __init__(self, cache: Optional[CacheManager] = None,
                 api_client: Optional[APIClient] = None,
                 config: Optional[Settings] = None):
        """Initialize with optional cache"""
        self.cache, self.api_client, self.config = cache, api_client, config
        self.current_config: DynamicConfig = self._get_defaults()
        self.config_file = Path("config/dynamic.json")
        self._rate_limiters = defaultdict(lambda: {"count": 0, "reset_at": datetime.now()})
        self._lock = asyncio.Lock()
        self._callbacks: List = []
        self.cache_key = "dynamic:config"
        logger.debug("DynamicConfigManager initialized")
    
    async def startup(self):
        """Initialize configuration (consistent naming with other modules)"""
        try:
            if self.cache:
                cached = await self._load_from_cache()
                if cached:
                    self.current_config = cached
                    logger.info("Dynamic config loaded from cache")
                    return True
            
            file_config = self._load_from_file()
            if file_config:
                self.current_config = file_config
                logger.info("Dynamic config loaded from file")
                
            await self._save_all()
            logger.info("Dynamic config defaults initialized")
            return True
        except Exception as e:
            logger.error(f"DynamicConfigManager startup error: {e}", exc_info=True)
            return False

    async def shutdown(self):
        async with self._lock:
            await self._save_all()
            self._callbacks.clear()
            logger.info("Dynamic config manager shutdown")

    async def check_rate_limit(self, identifier: str, limit_type: str = "default") -> tuple[bool, int]:
        if not self.cache:
            return True, 0

        key = f"rate:{limit_type}:{identifier}"
        cfg = self.current_config.rate_limits.get(limit_type, {})
        window, max_req = cfg.get("window_seconds", 3600), cfg.get("max_requests", 100)
        count = await self.cache.increment(key) or 0

        if count == 1:
            await self.cache.expire(key, window)

        if count > max_req:
            ttl = await self.cache.redis.ttl(key) if self.cache.redis else window
            return False, ttl or window
        return True, 0
    
    def get_message(self, key: str, default: str = "", **kw) -> str:
        txt = self.current_config.messages.get(key, default)
        try:
            return txt.format(**kw) if kw else txt
        except Exception:
            return default

    async def update_message(self, key: str, text: str):
        self.current_config.messages[key] = text
        await self._save_all()
        await self._notify(["messages"])
    
    def is_admin(self, uid: int) -> bool:
        return uid in self.current_config.admin_users

    async def set_admin(self, uid: int, is_admin: bool):
        (self.current_config.admin_users.add if is_admin else self.current_config.admin_users.discard)(uid)
        await self._save_all()
        await self._notify(["admin_users"])
    
    def is_maintenance_mode(self) -> bool:
        return self.current_config.maintenance.get("enabled", False)

    def get_maintenance_message(self) -> str:
        return self.current_config.maintenance.get(
            "message", "🔧 سیستم در حال بروزرسانی است، لطفاً بعداً مراجعه کنید."
        )

    async def set_maintenance_mode(self, enabled: bool, message: Optional[str] = None):
        self.current_config.maintenance.update(
            {
                "enabled": enabled,
                "message": message or self.get_maintenance_message(),
                "started_at": datetime.now().isoformat(),
            }
        )
        await self._save_all()
        await self._notify(["maintenance"])
    
    async def _save_all(self):
        self.current_config.last_updated = datetime.now()
        self._save_to_file()
        if self.cache:
            await self._save_to_cache()

    async def _save_to_cache(self):
        try:
            await self.cache.set(self.cache_key, self.current_config.to_dict(), ttl=3600)
        except Exception as e:
            logger.error(f"Save to cache failed: {e}")

    def _save_to_file(self):
        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(self.current_config.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Save to file error: {e}")

    async def _load_from_cache(self) -> Optional[DynamicConfig]:
        try:
            if data := await self.cache.get(self.cache_key):
                return DynamicConfig.from_dict(data if isinstance(data, dict) else json.loads(data))
        except Exception as e:
            logger.error(f"Cache load error: {e}")
        return None

    def _load_from_file(self) -> Optional[DynamicConfig]:
        try:
            if self.config_file.exists():
                with open(self.config_file, "r", encoding="utf-8") as f:
                    return DynamicConfig.from_dict(json.load(f))
        except Exception as e:
            logger.error(f"File load error: {e}")
        return None
    
    def _get_defaults(self) -> DynamicConfig:
        return DynamicConfig(
            features={
                "enable_rate_limit": True,
                "enable_order_tracking": True,
                "enable_repair_request": True,
                "enable_authentication": True,
                "debug_mode": False,
            },
            rate_limits={
                "default": {"max_requests": 100, "window_seconds": 3600},
                "message": {"max_requests": 10, "window_seconds": 60},
            },
            messages={
                "welcome": "🎉 خوش آمدید",
                "error": "❌ خطا رخ داد",
                "maintenance": "🔧 سیستم در حال بروزرسانی",
            },
            maintenance={"enabled": False},
            last_updated=datetime.now(),
        )

    async def reload_config(self) -> bool:
        try:
            new_cfg = await self._load_from_cache() or self._load_from_file()
            if not new_cfg:
                return False

            old = self.current_config.to_dict()
            self.current_config = new_cfg
            diff = self._diff(old, new_cfg.to_dict())
            if diff:
                await self._notify(diff)
                logger.info(f"Dynamic reload — changed: {diff}")
            return True
        except Exception as e:
            logger.error(f"Reload error: {e}", exc_info=True)
            return False

    @staticmethod
    def _diff(a: dict, b: dict) -> List[str]:
        return [k for k in ("features", "rate_limits", "messages", "admin_users", "maintenance")
                if json.dumps(a.get(k), sort_keys=True) != json.dumps(b.get(k), sort_keys=True)]

    def register_change_callback(self, cb):
        if cb not in self._callbacks:
            self._callbacks.append(cb)

    async def _notify(self, keys: List[str]):
        for cb in list(self._callbacks):
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(keys, self.current_config)
                else:
                    cb(keys, self.current_config)
            except Exception as e:
                logger.error(f"Callback {cb.__name__} failed: {e}")
    
    def get_status(self) -> Dict[str, Any]:
        """Get current status"""
        return {
            'last_updated': self.current_config.last_updated.strftime("%Y-%m-%d %H:%M") if self.current_config.last_updated else None,
            'features_enabled': sum(1 for v in self.current_config.features.values() if v),
            'total_features': len(self.current_config.features),
            'admin_users': len(self.current_config.admin_users),
            'maintenance_mode': self.is_maintenance_mode(),
            'rate_limits_configured': len(self.current_config.rate_limits),
            'messages_configured': len(self.current_config.messages)
        }
    
    def get_summary(self) -> str:
        """Get human-readable summary"""
        status = self.get_status()
        return (
            f"📊 Config Status\n"
            f"├─ Features: {status['features_enabled']}/{status['total_features']}\n"
            f"├─ Admins: {status['admin_users']}\n"
            f"├─ Rate Limits: {status['rate_limits_configured']} types\n"
            f"├─ Messages: {status['messages_configured']} templates\n"
            f"└─ Maintenance: {'🔴 ON' if status['maintenance_mode'] else '🟢 OFF'}"
        )
