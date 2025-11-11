"""Asynchronous API Client — resilient, cached, dynamic-ready"""
import asyncio, logging, json, aiohttp, hashlib
from aiohttp import ClientTimeout, ClientError
from typing import Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime
from src.core.cache import CacheManager

logger = logging.getLogger(__name__)

@dataclass
class APIResponse:
    status: int
    data: Any
    error: Optional[str] = None
    cached: bool = False
    timestamp: datetime = None
    
    @property
    def success(self) -> bool:
        return 200 <= self.status < 300 and self.error is None


class APIClient:
    """HTTP client with retries, caching, and dynamic config awareness."""
    
    def __init__(self, base_url: str, auth_token: Optional[str] = None,
                 timeout: int = 30, max_retries: int = 3, cache: Optional[CacheManager] = None):
        self.base_url = base_url.rstrip("/")
        self.auth_token = auth_token
        self.timeout = ClientTimeout(total=timeout, connect=5, sock_read=5)
        self.max_retries = max_retries
        self.cache = cache
        self.session: Optional[aiohttp.ClientSession] = None
        self._lock = asyncio.Lock()
        self.stats = {"requests": 0, "fails": 0, "cache_hits": 0, "last_error": None}
    
    async def startup(self):
        async with self._lock:
            if not self.session:
                headers = {
                    "Content-Type": "application/json",
                }
                if self.auth_token:
                    headers["auth-token"] = self.auth_token

                self.session = aiohttp.ClientSession(
                    headers=headers,
                    timeout=self.timeout
                )
                logger.info("APIClient started with base URL %s", self.base_url)
    
    async def shutdown(self):
        async with self._lock:
            if self.session and not self.session.closed:
                await self.session.close()
                self.session = None
                logger.info("APIClient shutdown complete")
    
    async def request(self, method: str, endpoint: str,
                      data: Optional[Dict] = None, params: Optional[Dict] = None,
                      cache_ttl: int = 0, **kw) -> APIResponse:
        """Make HTTP request with automatic retry and optional caching."""
        await self.startup()
        url = endpoint if endpoint.startswith("http") else f"{self.base_url}{endpoint}"

        key = None
        if cache_ttl > 0 and self.cache:
            digest = hashlib.sha1(
                f"{method}:{endpoint}:{json.dumps(data, sort_keys=True)}:{json.dumps(params, sort_keys=True)}".encode()
            ).hexdigest()
            key = f"api:{digest}"
            if cached := await self.cache.get(key):
                self.stats["cache_hits"] += 1
                return APIResponse(status=200, data=cached, cached=True)

        err = None
        for attempt in range(self.max_retries):
            start_time = asyncio.get_event_loop().time()
            try:
                self.stats["requests"] += 1
                async with self.session.request(method, url, json=data, params=params, **kw) as r:
                    payload = None
                    try:
                        payload = await r.json(content_type=None)
                    except Exception:
                        payload = await r.text()
                    if r.status < 400:
                        if key:
                            await self.cache.set(key, payload, ttl=cache_ttl)
                        return APIResponse(status=r.status, data=payload)
                    err = f"HTTP {r.status}"
                    if 400 <= r.status < 500:
                        break
            except asyncio.TimeoutError:
                duration = asyncio.get_event_loop().time() - start_time
                logger.warning(f"Timeout after {duration:.1f}s on attempt {attempt+1}/{self.max_retries} to {url}")
                err = "timeout"
            except ClientError as e:
                logger.error(f"Network failure on attempt {attempt+1}/{self.max_retries} to {e}")
                err = str(e)
            if attempt < self.max_retries - 1:
                await asyncio.sleep(2 ** attempt)

        self.stats["fails"] += 1
        self.stats["last_error"] = err
        return APIResponse(status=500, data=None, error=err)
    
    async def get(self, endpoint: str, **kw): return await self.request("GET", endpoint, **kw)
    async def post(self, endpoint: str, data=None, **kw): return await self.request("POST", endpoint, data=data, **kw)
    async def put(self, endpoint: str, data=None, **kw): return await self.request("PUT", endpoint, data=data, **kw)
    async def delete(self, endpoint: str, **kw): return await self.request("DELETE", endpoint, **kw)

    def get_health(self) -> Dict[str, Any]:
        return {
            "active": self.session is not None,
            "base_url": self.base_url,
            "stats": self.stats,
            "cache": bool(self.cache),
        }
    
    def update_defaults_from_config(self, cfg: dict):
        """Apply runtime config to tweak timeout / retry / base_url."""
        self.max_retries = cfg.get("api_max_retries", self.max_retries)
        if (new_url := cfg.get("api_base_url")):
            self.base_url = new_url.rstrip("/")
