"""
Redis Session Manager - Complete Minimized Production Version
"""
import json
import asyncio
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
import redis.asyncio as aioredis
from contextlib import asynccontextmanager

# Import from core config
from CoreConfig import UserState, BotConfig, BotMetrics

logger = logging.getLogger(__name__)

# =====================================================
# Session Data Model
# =====================================================
@dataclass
class SessionData:
    """Minimal session data structure"""
    chat_id: int
    state: UserState = UserState.IDLE
    created_at: datetime = field(default_factory=datetime.now)
    expires_at: datetime = field(default_factory=lambda: datetime.now() + timedelta(minutes=30))
    
    # Authentication
    is_authenticated: bool = False
    national_id: Optional[str] = None
    user_name: Optional[str] = None
    
    # Temporary storage
    temp_data: Dict[str, Any] = field(default_factory=dict)
    
    # Activity tracking
    last_activity: datetime = field(default_factory=datetime.now)
    request_count: int = 0
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for Redis storage"""
        data = asdict(self)
        # Convert datetime to ISO format
        for key in ['created_at', 'expires_at', 'last_activity']:
            if data[key]:
                data[key] = data[key].isoformat()
        # Convert enum to value
        data['state'] = self.state.value
        return data
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'SessionData':
        """Create instance from dictionary"""
        # Convert ISO strings to datetime
        for key in ['created_at', 'expires_at', 'last_activity']:
            if data.get(key):
                data[key] = datetime.fromisoformat(data[key])
        # Convert state string to enum
        if 'state' in data:
            data['state'] = UserState(data['state'])
        return cls(**data)
    
    def is_expired(self) -> bool:
        """Check if session expired"""
        return datetime.now() > self.expires_at
    
    def extend(self, minutes: int = 30):
        """Extend session expiry"""
        self.expires_at = datetime.now() + timedelta(minutes=minutes)
        self.last_activity = datetime.now()

# =====================================================
# Redis Session Manager
# =====================================================
class RedisSessionManager:
    """Minimal async Redis session manager"""
    
    def __init__(self, config: BotConfig, metrics: BotMetrics):
        self.config = config
        self.metrics = metrics
        self.redis: Optional[aioredis.Redis] = None
        self.pool: Optional[aioredis.ConnectionPool] = None
        self._local_cache: Dict[int, SessionData] = {}
        self._lock = asyncio.Lock()
        self._pool = None

        # Redis key prefixes
        self.KEY_PREFIX = "bot:session:"
        self.AUTH_PREFIX = "bot:auth:"
        
        # TTL configuration
        self.DEFAULT_TTL = 1800  # 30 minutes
        self.AUTH_TTL = 3600     # 60 minutes
        self.MAX_CACHE_SIZE = 500
        
    async def connect(self):
        """Connect to Redis with proper connection pooling"""
        max_retries = 3
        retry_delay = 1
        
        for attempt in range(max_retries):
            try:
                # create separated connection pool
                self.pool = aioredis.ConnectionPool.from_url(
                    self.config.redis_url,
                    decode_responses=True,
                    max_connections=20,
                    socket_keepalive=True,
                    socket_connect_timeout=5,
                    retry_on_timeout=True,
                    health_check_interval=30
                )
                self.redis = aioredis.Redis(connection_pool=self.pool)
                
                await self.redis.ping()
                logger.info("✅ Redis connected")
                return
            except Exception as e:
                if attempt == max_retries - 1:
                    logger.error(f"❌ Redis connection failed: {e}")
                    raise
                await asyncio.sleep(retry_delay)
                retry_delay *= 2

    
    async def disconnect(self):
        """Safely disconnect from Redis"""
        try:
            # Close Redis connection if exists
            if self.redis:
                try:
                    # Don't wait for pool operations if event loop is closing
                    await asyncio.wait_for(self.redis.close(), timeout=1.0)
                except (asyncio.TimeoutError, RuntimeError) as e:
                    logger.debug(f"Redis close timeout/error (expected during shutdown): {e}")
                finally:
                    self.redis = None
            
            # Close pool if exists
            if self._pool:
                try:
                    # Use wait_closed=False to avoid event loop issues
                    await asyncio.wait_for(self._pool.disconnect(inuse_connections=True), timeout=1.0)
                except (asyncio.TimeoutError, RuntimeError, AttributeError) as e:
                    logger.debug(f"Pool disconnect timeout/error (expected during shutdown): {e}")
                finally:
                    self._pool = None
                    
            logger.info("Redis disconnected cleanly")
            
        except Exception as e:
            # During shutdown, some errors are expected
            if "Event loop is closed" not in str(e):
                logger.error(f"Unexpected error during disconnect: {e}")
            else:
                logger.debug("Event loop closed during disconnect (normal during shutdown)")


    
    @asynccontextmanager
    async def session(self, chat_id: int):
        """Session context manager"""
        if not self.redis:
            logger.error("Redis not connected")
            
        session = await self.get_or_create(chat_id)
        try:
            yield session
        finally:
            if session:
                await self.save(session)
    

    async def get_or_create(self, chat_id: int) -> SessionData:
        """Get existing or create new session"""
        if not self.redis:
            logger.error("Redis not connected")

        # Check local cache
        if chat_id in self._local_cache:
            session = self._local_cache[chat_id]
            if not session.is_expired():
                self.metrics.cache_hits += 1
                return session
            else:
                del self._local_cache[chat_id]
        
        self.metrics.cache_misses += 1
        
        # Check Redis
        key = f"{self.KEY_PREFIX}{chat_id}"
        data = await self.redis.get(key)
        
        if data:
            try:
                session = SessionData.from_dict(json.loads(data))
                if not session.is_expired():
                    self._local_cache[chat_id] = session
                    return session
            except Exception as e:
                logger.error(f"Session decode error: {e}")
        
        # Create new session
        session = SessionData(chat_id=chat_id)
        await self.save(session)
        
        self.metrics.total_sessions += 1
        self.metrics.active_sessions = len(self._local_cache)
        
        logger.info(f"New session created: {chat_id}")
        return session
    
    async def save(self, session: SessionData):
        """Save session to Redis"""
        try:
            session.last_activity = datetime.now()
            session.request_count += 1
            
            # Determine TTL
            ttl = self.AUTH_TTL if session.is_authenticated else self.DEFAULT_TTL
            
            # Save to Redis
            key = f"{self.KEY_PREFIX}{session.chat_id}"
            await self.redis.setex(
                key, 
                ttl, 
                json.dumps(session.to_dict())
            )
            
            # Update local cache
            self._local_cache[session.chat_id] = session
            
            # Cleanup cache if too large
            if len(self._local_cache) > self.MAX_CACHE_SIZE:
                await self._cleanup_cache()
                
        except Exception as e:
            logger.error(f"Save error: {e}")
    
    async def _cleanup_cache(self):
        """Clean up local cache"""
        async with self._lock:
            # Remove expired sessions
            expired = [
                k for k, v in self._local_cache.items() 
                if v.is_expired()
            ]
            for k in expired[:250]:  # Remove half
                del self._local_cache[k]
            
            self.metrics.active_sessions = len(self._local_cache)
    
    async def update_state(self, chat_id: int, new_state: UserState, **kwargs):
        """Update session state"""
        async with self.session(chat_id) as session:
            old_state = session.state
            session.state = new_state
            session.extend()
            
            if kwargs:
                session.temp_data.update(kwargs)
            
            logger.info(f"State changed: {chat_id} {old_state.name} -> {new_state.name}")
            return session
    
    async def authenticate(self, chat_id: int, national_id: str, name: str):
        """Authenticate user"""
        async with self.session(chat_id) as session:
            session.is_authenticated = True
            session.national_id = national_id
            session.user_name = name
            session.state = UserState.AUTHENTICATED
            session.extend(60)  # 60 minutes for authenticated users
            
            # Save auth index
            auth_key = f"{self.AUTH_PREFIX}{national_id}"
            await self.redis.setex(auth_key, self.AUTH_TTL, chat_id)
            
            self.metrics.authenticated_users += 1
            logger.info(f"User authenticated: {chat_id} - {name}")
            return session
    
    async def logout(self, chat_id: int):
        """Logout user"""
        async with self.session(chat_id) as session:
            # Clear auth index
            if session.national_id:
                auth_key = f"{self.AUTH_PREFIX}{session.national_id}"
                await self.redis.delete(auth_key)
            
            # Reset session
            session.is_authenticated = False
            session.national_id = None
            session.user_name = None
            session.state = UserState.IDLE
            session.temp_data.clear()
            
            if self.metrics.authenticated_users > 0:
                self.metrics.authenticated_users -= 1
            
            logger.info(f"User logged out: {chat_id}")
    
    async def clear(self, chat_id: int):
        """Clear session completely"""
        try:
            # Remove from Redis - با مدیریت خطا
            if self.redis:
                key = f"{self.KEY_PREFIX}{chat_id}"
                try:
                    await self.redis.delete(key)
                except (ConnectionError, RuntimeError) as e:
                    logger.warning(f"Could not delete from Redis: {e}")
            
            # Remove from cache
            if chat_id in self._local_cache:
                del self._local_cache[chat_id]
            
            self.metrics.active_sessions = len(self._local_cache)
            logger.info(f"Session cleared: {chat_id}")
        except Exception as e:
            logger.error(f"Error clearing session {chat_id}: {e}")

    
    async def get_stats(self) -> Dict:
        """Get session statistics"""
        cursor = '0'
        total = 0
        authenticated = 0
        
        while cursor != 0:
            cursor, keys = await self.redis.scan(
                cursor,
                match=f"{self.KEY_PREFIX}*",
                count=100
            )
            total += len(keys)
            
            # Count authenticated sessions
            for key in keys:
                try:
                    data = await self.redis.get(key)
                    if data:
                        session_dict = json.loads(data)
                        if session_dict.get('is_authenticated'):
                            authenticated += 1
                except:
                    pass
        
        return {
            'total_sessions': total,
            'authenticated_sessions': authenticated,
            'cached_sessions': len(self._local_cache),
            'cache_hit_rate': self.metrics.cache_hits / max(self.metrics.cache_hits + self.metrics.cache_misses, 1),
            'total_requests': self.metrics.total_requests
        }
    
    async def cleanup_expired(self):
        """Clean up expired sessions from Redis"""
        cursor = '0'
        deleted = 0
        
        while cursor != 0:
            cursor, keys = await self.redis.scan(
                cursor,
                match=f"{self.KEY_PREFIX}*",
                count=100
            )
            
            for key in keys:
                try:
                    data = await self.redis.get(key)
                    if data:
                        session_dict = json.loads(data)
                        expires_at = datetime.fromisoformat(session_dict.get('expires_at'))
                        if datetime.now() > expires_at:
                            await self.redis.delete(key)
                            deleted += 1
                except:
                    pass
        
        logger.info(f"Cleaned up {deleted} expired sessions")
        return deleted
    
    async def get_user_by_national_id(self, national_id: str) -> Optional[int]:
        """Get chat_id by national ID"""
        auth_key = f"{self.AUTH_PREFIX}{national_id}"
        chat_id = await self.redis.get(auth_key)
        return int(chat_id) if chat_id else None
    
    async def is_rate_limited(self, chat_id: int) -> bool:
        """Check if user is rate limited"""
        session = await self.get_or_create(chat_id)
        
        # Check hourly limit
        if session.request_count > self.config.max_requests_hour:
            session.state = UserState.RATE_LIMITED
            await self.save(session)
            return True
        
        return False
    
    async def get_active_sessions(self) -> List[SessionData]:
        """Get all active sessions"""
        active_sessions = []
        
        for session in self._local_cache.values():
            if not session.is_expired():
                active_sessions.append(session)
        
        return active_sessions

# =====================================================
# Factory & Background Tasks
# =====================================================
class SessionBackgroundTasks:
    """Background tasks for session management"""
    
    def __init__(self, manager: RedisSessionManager):
        self.manager = manager
        self.cleanup_task = None
        self.running = False
    
    async def start(self):
        """Start background tasks"""
        self.running = True
        self.cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("Background tasks started")
    
    async def stop(self):
        """Stop background tasks"""
        self.running = False
        if self.cleanup_task:
            self.cleanup_task.cancel()
            try:
                await self.cleanup_task
            except asyncio.CancelledError:
                pass
        logger.info("Background tasks stopped")
    
    async def _cleanup_loop(self):
        """Periodic cleanup task"""
        while self.running:
            try:
                await asyncio.sleep(1800)  # Run every 30 minutes
                await self.manager.cleanup_expired()
                await self.manager._cleanup_cache()
            except Exception as e:
                logger.error(f"Cleanup error: {e}")

async def create_session_manager(config: BotConfig, metrics: BotMetrics) -> RedisSessionManager:
    """Factory to create and initialize session manager"""
    manager = RedisSessionManager(config, metrics)
    await manager.connect()
    
    # Start background tasks
    tasks = SessionBackgroundTasks(manager)
    await tasks.start()
    manager.background_tasks = tasks
    
    return manager

# =====================================================
# Helper Functions
# =====================================================
def format_session_info(session: SessionData) -> str:
    """Format session info for display"""
    info = f"""
📊 Session Info:
• Chat ID: {session.chat_id}
• State: {session.state.name}
• Authenticated: {'✅' if session.is_authenticated else '❌'}
• User: {session.user_name or 'N/A'}
• Requests: {session.request_count}
• Expires: {session.expires_at.strftime('%Y-%m-%d %H:%M')}
    """
    return info.strip()

# =====================================================
# Module Exports
# =====================================================
__all__ = [
    'RedisSessionManager',
    'SessionData',
    'SessionBackgroundTasks',
    'create_session_manager',
    'format_session_info'
]

# =====================================================
# Testing
# =====================================================
if __name__ == "__main__":
    async def test():
        """Test session manager"""
        from CoreConfig import initialize_core
        
        # Initialize
        config, validators, metrics = initialize_core()
        
        # Create manager
        manager = await create_session_manager(config, metrics)
        
        # Test operations
        test_chat_id = 123456789
        
        # Create session
        session = await manager.get_or_create(test_chat_id)
        print(f"✅ Session created: {session.chat_id}")
        
        # Test authentication
        await manager.authenticate(
            test_chat_id, 
            "1234567890", 
            "تست کاربر"
        )
        print("✅ User authenticated")
        
        # Test state change
        await manager.update_state(
            test_chat_id,
            UserState.WAITING_ORDER_NUMBER,
            order_type="repair"
        )
        print("✅ State updated")
        
        # Test stats
        stats = await manager.get_stats()
        print(f"📊 Stats: {stats}")
        
        # Test session info
        session = await manager.get_or_create(test_chat_id)
        info = format_session_info(session)
        print(f"📋 Session Info:\n{info}")
        
        # Test logout
        await manager.logout(test_chat_id)
        print("✅ User logged out")
        
        # Test cleanup
        deleted = await manager.cleanup_expired()
        print(f"🧹 Cleaned up {deleted} expired sessions")
        
        # Test rate limiting
        is_limited = await manager.is_rate_limited(test_chat_id)
        print(f"⚠️ Rate limited: {is_limited}")
        
        # Clear session
        await manager.clear(test_chat_id)
        print("✅ Session cleared")
        
        # Stop background tasks
        await manager.background_tasks.stop()
        
        # Disconnect
        await manager.disconnect()
        print("✅ All tests passed!")
    
    # Run test
    import asyncio
    asyncio.run(test())
