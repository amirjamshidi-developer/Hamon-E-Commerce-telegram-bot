"""
Data Provider Module - Fixed Production Version
"""
import os
import logging
import json
import asyncio
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from datetime import datetime, timedelta
import aiohttp
from aiohttp import ClientTimeout, ClientSession

from CoreConfig import BotConfig, STATUS_TEXT, WORKFLOW_STEPS, calculate_progress, get_step_display

logger = logging.getLogger(__name__)

@dataclass
class OrderInfo:
    """Order information data class"""
    order_number: str
    customer_name: str
    national_id: str
    device_model: str
    serial_number: str
    status: int
    steps: int
    registration_date: str
    repair_description: Optional[str] = None
    tracking_code: Optional[str] = None
    estimated_completion: Optional[str] = None
    technician_name: Optional[str] = None
    total_cost: Optional[int] = None
    devices: List[Dict[str, Any]] = None
    
    def to_display_dict(self) -> Dict[str, Any]:
        """Convert to display format"""
        status_text = STATUS_TEXT.get(self.status, f"مرحله {self.status}")
        step_text = WORKFLOW_STEPS.get(self.steps, f"گام {self.steps}")
        progress = calculate_progress(self.steps)
        
        return {
            'order_number': self.order_number,
            'customer_name': self.customer_name,
            'device_model': self.device_model,
            'serial': self.serial_number,
            'status': status_text,
            'current_step': step_text,
            'progress': round(progress, 1),
            'registration_date': self.registration_date,
            'additional_info': self._format_additional_info(),
            'devices': self.devices or []
        }
    
    def _format_additional_info(self) -> str:
        """Format additional information"""
        info = []
        
        if self.steps is not None:
            step_text = get_step_display(self.steps)
            info.append(f"📍 مرحله فعلی: {step_text}")
        
        if self.tracking_code:
            info.append(f"🔍 کد رهگیری: {self.tracking_code}")
        if self.technician_name:
            info.append(f"👨‍🔧 کارشناس: {self.technician_name}")
        if self.estimated_completion:
            info.append(f"📅 تاریخ تحویل: {self.estimated_completion}")
        if self.total_cost:
            info.append(f"💰 هزینه: {self.total_cost:,} تومان")
        if self.repair_description:
            info.append(f"📝 تعمیرات: {self.repair_description}")
            
        return "\n".join(info) if info else ""

class DataProvider:
    """Manages API communications with proper session lifecycle"""
    
    def __init__(self, config: BotConfig, redis_client=None):
        self.config = config
        self.redis = redis_client
        self.session: Optional[ClientSession] = None
        self.session_lock = asyncio.Lock()  # Fixed: renamed from _session_lock
        
        # Add missing attributes
        self.cache_prefix = "bot:cache:"
        self.auth_token = os.getenv("AUTH_TOKEN", "")
        
        # Cache TTLs
        self.cache_ttl = 300  # Default 5 minutes
        
        # Timeout settings
        self.timeout = ClientTimeout(total=30, connect=10, sock_read=20)
        
        logger.info("DataProvider initialized")

    # =====================================================
    # Cache Methods
    # =====================================================
    
    async def _get_cached(self, key: str) -> Optional[Dict[str, Any]]:
        """Get cached data from Redis"""
        if not self.redis:
            return None
        
        try:
            cache_key = f"{self.cache_prefix}{key}"
            data = await self.redis.get(cache_key)
            
            if data:
                logger.debug(f"Cache hit: {key}")
                return json.loads(data)
            
            return None
            
        except Exception as e:
            logger.error(f"Cache get error: {e}")
            return None
    
    async def _set_cached(self, key: str, value: Dict[str, Any], ttl: int = None) -> None:
        """Set cached data in Redis"""
        if not self.redis:
            return
        
        try:
            cache_key = f"{self.cache_prefix}{key}"
            ttl = ttl or self.cache_ttl
            
            await self.redis.setex(
                cache_key,
                ttl,
                json.dumps(value, ensure_ascii=False)
            )
            
            logger.debug(f"Cache set: {key} (TTL: {ttl}s)")
            
        except Exception as e:
            logger.error(f"Cache set error: {e}")
    
    # =====================================================
    # Session Management
    # =====================================================
    
    async def ensure_session(self):
        """Ensure HTTP session exists"""
        async with self.session_lock:
            if self.session is None or self.session.closed:
                connector = aiohttp.TCPConnector(
                    limit=100,
                    limit_per_host=30,
                    ttl_dns_cache=300
                )
                
                self.session = aiohttp.ClientSession(
                    timeout=self.timeout,
                    connector=connector,
                    headers={
                        'User-Agent': 'TelegramBot/1.0',
                        'Accept': 'application/json',
                        'Content-Type': 'application/json'
                    }
                )
                logger.info("HTTP session created")
    
    async def close_session(self):
        """Close HTTP session properly"""
        async with self.session_lock:
            if self.session and not self.session.closed:
                await self.session.close()
                await asyncio.sleep(0.25)
                self.session = None
                logger.info("HTTP session closed")
    
    # =====================================================
    # API Request Method
    # =====================================================
    
    async def _make_request(
        self,
        method: str,
        url: str,
        json: Optional[Dict] = None,
        headers: Optional[Dict] = None
    ) -> Optional[Dict]:
        """Make HTTP request with retry logic"""
        await self.ensure_session()
        
        # Prepare headers
        request_headers = {'auth-token': self.auth_token}
        if headers:
            request_headers.update(headers)
        
        for attempt in range(3):  # Max 3 retries
            try:
                async with self.session.request(
                    method, url, json=json, headers=request_headers
                ) as response:
                    
                    logger.debug(f"API {method} {url} - Status: {response.status}")
                    
                    if response.status == 200:
                        return await response.json()
                    elif response.status == 404:
                        return None
                    elif response.status >= 500 and attempt < 2:
                        await asyncio.sleep(2 ** attempt)
                        continue
                    else:
                        text = await response.text()
                        logger.error(f"API error {response.status}: {text[:200]}")
                        return None
                        
            except asyncio.TimeoutError:
                logger.error(f"Request timeout: {url}")
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
                    continue
            except Exception as e:
                logger.error(f"Request error: {e}")
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
                    continue
        
        return None
    
    # =====================================================
    # API Methods
    # =====================================================
    
    async def get_order_by_number(self, order_number: str) -> Optional[Dict[str, Any]]:
        """Get order by number with caching"""
        cache_key = f"order_num:{order_number}"
        
        # Check cache
        cached = await self._get_cached(cache_key)
        if cached:
            return cached
        
        # Get endpoint
        endpoint = self.config.api_endpoints.get('track_order')
        if not endpoint:
            logger.error("Order tracking endpoint not configured")
            return None
        
        # Make request
        response = await self._make_request('POST', endpoint, json={'number': order_number})
        if not response:
            return None
        
        # Parse response
        order_info = self._parse_order_response(response)
        if not order_info or not order_info.order_number:
            return None
        
        # Convert to display format
        result = order_info.to_display_dict()
        
        # Cache result
        if result:
            await self._set_cached(cache_key, result, ttl=300)
        
        return result

    async def get_order_by_serial(self, serial: str) -> Optional[Dict[str, Any]]:
        """Get order by serial number with caching"""
        cache_key = f"order_serial:{serial}"
        
        # Check cache
        cached = await self._get_cached(cache_key)
        if cached:
            return cached
        
        # Get endpoint
        endpoint = self.config.api_endpoints.get('track_serial')
        if not endpoint:
            logger.error("Serial tracking endpoint not configured")
            return None
        
        # Make request
        response = await self._make_request('POST', endpoint, json={'serial': serial})
        if not response:
            return None
        
        # Parse response
        order_info = self._parse_order_response(response)
        if not order_info or not order_info.order_number:
            return None
        
        # Convert to display format
        result = order_info.to_display_dict()
        
        # Cache result
        if result:
            await self._set_cached(cache_key, result, ttl=300)
        
        return result
    
    def _parse_order_response(self, response: Dict) -> Optional[OrderInfo]:
        """Parse API response into OrderInfo"""
        try:
            # Get data from response
            data = response.get('data', response.get('order', response))
            
            # Extract devices
            devices = data.get('items', data.get('devices', []))
            first_device = devices[0] if devices else {}
            
            # Parse fields
            return OrderInfo(
                order_number=str(data.get('number', '')),
                customer_name=data.get('$$_contactId', data.get('contactId_name', 'نامشخص')),
                national_id=data.get('contactId_nationalCode', ''),
                device_model=first_device.get('$$_deviceId', data.get('$$_deviceId', 'نامشخص')),
                serial_number=first_device.get('serialNumber', data.get('serialNumber', '')),
                status=data.get('status', 0),
                steps=data.get('steps', 0),
                registration_date=data.get('warehouseRecieptId_createdOn', 
                                         data.get('preReceptionId_createdOn', '')),
                repair_description=first_device.get('passDescription'),
                tracking_code=str(data.get('preReceptionId_number', '')),
                total_cost=data.get('factorId_totalPriceWithTax'),
                devices=devices
            )
        except Exception as e:
            logger.error(f"Error parsing order: {e}")
            return None
    
    async def get_user_by_national_id(self, national_id: str) -> Optional[Dict]:
        """Get user information by national ID"""
        if not national_id:
            return None
        
        # For testing - return mock data if endpoint not configured
        endpoint = self.config.api_endpoints.get('national_id')
        if not endpoint:
            logger.warning("National ID endpoint not configured - using mock data")
            return {
                'name': 'کاربر تست',
                'phone': '09121234567',
                'national_id': national_id
            }
        
        # Make request
        cache_key = f"user:nid:{national_id}"
        
        # Check cache
        cached = await self._get_cached(cache_key)
        if cached:
            return cached
        
        response = await self._make_request(
            'POST', endpoint, json={'national_id': national_id}
        )
        
        if response:
            # Parse user data
            user_data = response.get('data', response.get('user', response))
            
            # Cache result
            await self._set_cached(cache_key, user_data, ttl=1800)
            
            return user_data
        
        return None
