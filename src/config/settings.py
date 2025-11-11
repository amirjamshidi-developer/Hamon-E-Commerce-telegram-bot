""" Runtime dynamic configuration management with environment variables supports """
import os
import json
import logging
from dataclasses import dataclass, field
from typing import Dict, Optional, Any, ClassVar
from datetime import datetime
from threading import Lock
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

@dataclass
class Settings:
    telegram_token: str
    redis_url: str = "redis://localhost:6379/0"
    redis_password: Optional[str] = None
    auth_token: str = ""
    server_urls: Dict[str, str] = field(default_factory=dict)

    # Runtime-tunable values
    maintenance_mode: bool = False
    cache_ttl_seconds: int = 300
    cache_max_size: int = 1000
    session_timeout_minutes: int = 60
    max_sessions_per_user: int = 3
    session_cleanup_interval: int = 300
    max_requests_hour: int = 100
    max_requests_day: int = 1000
    rate_limit_duration: int = 3600
    enable_dynamic_config: bool = True
    enable_logging: bool = True
    enable_metrics: bool = True

    # API config
    api_timeout: int = 30
    api_max_retries: int = 3
    api_retry_delay: int = 1
    
    # Business
    support_phone: str = os.getenv("SUPPORT_PHONE","03133127")
    website_url: str = os.getenv("WEBSITE_URL","https://hamoonpay.com")
    admin_chat_id: str = os.getenv("ADMIN_CHAT_ID")

    # Singleton instance
    _instance: ClassVar[Optional['Settings']] = None
    _lock: ClassVar[Lock] = Lock()
    _last_reload: ClassVar[Optional[datetime]] = None
    _dynamic_fields: ClassVar[set] = {
        'maintenance_mode', 'session_timeout_minutes', 'cache_ttl_seconds',
        'max_requests_day', 'max_requests_hour', 'support_phone', 'website_url'
    }

    @classmethod
    def get_instance(cls, force_reload: bool = False) -> 'Settings':
        """ Get singleton instance with optional reload - Thread-safe implementation """
        with cls._lock: # Thread-safe
            if cls._instance is None or force_reload:
                cls._instance = cls.from_env()
                cls._last_reload = datetime.now()
                logger.info(f"Settings {'reloaded' if force_reload else 'loaded'}")
        return cls._instance

    @classmethod
    def from_env(cls) -> 'Settings':
        """Load configuration from environment variables"""
        
        base_url = os.getenv("SERVER_URL") 
        server_urls = {
            "base":base_url,
            "number": os.getenv("SERVER_URL_NUMBER"),
            "serial": os.getenv("SERVER_URL_SERIAL"),
            "national_id": os.getenv("SERVER_URL_NATIONAL_ID"),
            "submit_complaint": os.getenv("SERVER_URL_COMPLAINT"),
            "submit_repair": os.getenv("SERVER_URL_REPAIR")
        }

        return cls(
            telegram_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            auth_token=os.getenv("AUTH_TOKEN", ""),
            redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            redis_password=os.getenv("REDIS_PASSWORD"),
            server_urls=server_urls,
            maintenance_mode=os.getenv("MAINTENANCE_MODE", "false").lower() in ["true", "1"],
            enable_metrics=os.getenv("ENABLE_METRICS", "true").lower() in ["true", "1"],
            enable_dynamic_config=os.getenv("ENABLE_DYNAMIC_CONFIG", "true").lower() in ["true", "1"],
            cache_ttl_seconds=int(os.getenv("CACHE_TTL", "300")),
            cache_max_size=int(os.getenv("CACHE_SIZE", "1000")),
            api_timeout=int(os.getenv("API_TIMEOUT", "30")),
            api_max_retries=int(os.getenv("API_RETRIES", "3")),
            max_requests_hour=int(os.getenv("MAX_REQUESTS_HOUR", "100")),
            max_requests_day=int(os.getenv("MAX_REQUESTS_DAY", "1000")),
            session_timeout_minutes=int(os.getenv("SESSION_TIMEOUT", "60")),
            max_sessions_per_user=int(os.getenv("MAX_SESSIONS", "3")),
            support_phone=os.getenv("SUPPORT_PHONE"),
            website_url=os.getenv("WEBSITE_URL"),
            admin_chat_id=os.getenv("ADMIN_CHAT_ID")
        )

    def __post_init__(self):
        """Validate required fields"""
        if not self.telegram_token:
            raise ValueError("TELEGRAM_BOT_TOKEN is required")
        if os.path.exists('.dynamic_config.json'):
            try:
                with open('.dynamic_config.json', 'r') as f:
                    self.update_from_dict(json.load(f), persist=False)
            except json.JSONDecodeError as e:
                logger.warning(f"Dynamic config file corrupt: {e}")
        
    def get_endpoint(self, name: str) -> Optional[str]:
        """Get endpoint with validation"""
        return self.server_urls.get(name)

    def update_from_dict(self, updates: Dict[str, Any], persist: bool = True) -> None:
        with self._lock:
            applied = {}
            for key, value in updates.items():
                if key in self._dynamic_fields and hasattr(self, key):
                    current_type = type(getattr(self, key))
                    try:
                        if current_type is bool and isinstance(value, str):
                            value = value.lower() in ("true", "1", "yes")
                        elif current_type is int and isinstance(value, str):
                            value = int(value)
                    except Exception:
                        pass
                    setattr(self, key, value)
                    applied[key] = value
                    logger.info(f"Updated {key} → {value!r}")
            if persist and applied:
                self._persist_updates(applied)

    def _persist_updates(self, updates: Dict[str, Any]) -> None:
        try:
            existing = {}
            if os.path.exists('.dynamic_config.json'):
                with open('.dynamic_config.json', 'r') as f:
                    existing = json.load(f) or {}
            existing.update(updates)
            with open('.dynamic_config.json', 'w') as f:
                json.dump(existing, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to persist config: {e}")

def get_config() -> Settings:
    """Get current configuration instance"""
    return Settings.get_instance()
