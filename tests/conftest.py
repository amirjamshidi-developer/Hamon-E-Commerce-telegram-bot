import os, sys
import pytest
from unittest.mock import MagicMock, AsyncMock
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
load_dotenv(Path(__file__).parent / ".env.test", override=True)

@pytest.fixture(scope="session")
def test_env_vars():
    """Ensure required test env vars are set"""
    required = ["TELEGRAM_BOT_TOKEN", "REDIS_URL", "AUTH_TOKEN", "SERVER_URL"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        pytest.skip(f"Missing test env vars: {missing}")  
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not any(x in token.lower() for x in ["test", "dummy", "fake", "mock"]):
        pytest.exit("DANGER: Production token detected in tests! Use .env.test")
    
    return {k: os.getenv(k) for k in required}

@pytest.fixture(scope="function", autouse=True)
def reset_settings_singleton():
    """Force reset Settings singleton before each test"""
    from src.config.settings import Settings
    
    if hasattr(Settings, '_lock'):
        with Settings._lock:
            Settings._instance = None
            Settings._last_reload = None
    else:
        Settings._instance = None
        Settings._last_reload = None
    
    yield
    
    if hasattr(Settings, '_lock'):
        with Settings._lock:
            Settings._instance = None
    else:
        Settings._instance = None


@pytest.fixture(scope="function", autouse=True)
def mock_dynamic_config_file(tmp_path, monkeypatch):
    """Redirect .dynamic_config.json to temp directory"""
    fake_config_path = tmp_path / ".dynamic_config.json"
    
    original_exists = os.path.exists
    original_open = open
    
    def patched_open(file, mode='r', *args, **kwargs):
        file_str = str(file)
        if os.path.basename(file_str) == ".dynamic_config.json":
            return original_open(fake_config_path, mode, *args, **kwargs)
        return original_open(file, mode, *args, **kwargs)

    def patched_exists(path):
        path_str = str(path)
        if os.path.basename(path_str) == ".dynamic_config.json":
            return fake_config_path.exists()
        return original_exists(path)

    
    monkeypatch.setattr("os.path.exists", patched_exists)
    monkeypatch.setattr("builtins.open", patched_open)
    yield fake_config_path


@pytest.fixture(scope="function", autouse=True)
def mock_redis_globally(monkeypatch):
    fake_redis = MagicMock()
    
    # Basic operations
    fake_redis.ping = AsyncMock(return_value=True)
    fake_redis.get = AsyncMock(return_value=None)
    fake_redis.set = AsyncMock(return_value=True)
    fake_redis.setex = AsyncMock(return_value=True)
    fake_redis.delete = AsyncMock(return_value=1)
    fake_redis.incr = AsyncMock(return_value=1)
    fake_redis.expire = AsyncMock(return_value=True)
    fake_redis.scan = AsyncMock(return_value=(0, []))
    fake_redis.aclose = AsyncMock()
    
    # Hash operations (CRITICAL FOR SESSION STORAGE)
    fake_redis.hset = AsyncMock(return_value=1)
    fake_redis.hget = AsyncMock(return_value=None)
    fake_redis.hgetall = AsyncMock(return_value={})
    fake_redis.hdel = AsyncMock(return_value=1)
    
    # Key operations
    fake_redis.keys = AsyncMock(return_value=[])
    fake_redis.exists = AsyncMock(return_value=0)
    fake_redis.flushdb = AsyncMock(return_value=True)
    
    # Pool mock
    fake_pool = MagicMock()
    fake_pool.disconnect = AsyncMock()
    
    async def mock_from_url(*args, **kwargs):
        return fake_pool
    
    monkeypatch.setattr("redis.asyncio.ConnectionPool.from_url", mock_from_url)
    monkeypatch.setattr("redis.asyncio.Redis", lambda *args, **kwargs: fake_redis)
    
    yield fake_redis


@pytest.fixture
def app_settings(test_env_vars):
    """Isolated Settings instance for each test"""
    from src.config.settings import Settings
    return Settings.from_env()
