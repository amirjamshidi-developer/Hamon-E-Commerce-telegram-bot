"""
Data Provider 
"""
import os
import logging
import json
import asyncio
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from datetime import datetime
import aiohttp
from aiohttp import ClientTimeout, ClientSession

from .CoreConfig import (
    BotConfig, STATUS_TEXT, WORKFLOW_STEPS, STEP_ICONS,
    calculate_progress, generate_progress_bar, get_status_info
)

logger = logging.getLogger(__name__)

# =====================================================
# Data Models
# =====================================================

@dataclass
class OrderInfo:
    """Order information with proper field mapping"""
    order_number: str
    customer_name: str
    national_id: str
    device_model: str
    serial_number: str
    status: int
    steps: int
    registration_date: str
    pre_reception_date: str
    repair_description: Optional[str] = None
    tracking_code: Optional[str] = None
    estimated_completion: Optional[str] = None
    technician_name: Optional[str] = None
    total_cost: Optional[int] = None
    devices: List[Dict[str, Any]] = None

    def to_display_dict(self) -> Dict[str, Any]:
        """Convert to display format with enhanced UI"""
        # Get status information
        status_info = get_status_info(self.status, self.steps)
        
        # Build display dictionary
        return {
            'order_number': self.order_number,
            'customer_name': self.customer_name,
            'device_model': self.device_model,
            'serial_number': self.serial_number,
            'status': status_info['status_text'],
            'status_icon': status_info['icon'],
            'current_step': status_info.get('step_text', f"مرحله {self.steps}"),
            'progress': status_info['progress'],
            'progress_bar': status_info['progress_bar'],
            'registration_date': self._format_date(self.registration_date),
            'pre_reception_date': self._format_date(self.pre_reception_date),
            'tracking_code': self.tracking_code or "---",
            'repair_description': self.repair_description or "---",
            'additional_info': self._format_additional_info(status_info),
            'devices': self.devices or []
        }
    
    def _format_date(self, date_str: str) -> str:
        """Format date for display (remove time part)"""
        if not date_str or date_str == "---":
            return "---"
        # Split by space and take only date part
        if ' ' in date_str:
            return date_str.split(' ')[0]
        return date_str
    
    def _format_additional_info(self, status_info: Dict) -> str:
        """Format additional information"""
        lines = []
        
        # Current stage
        lines.append(f"📍 مرحله: {status_info['icon']} {status_info.get('step_text', 'نامشخص')}")
        
        # Tracking code
        if self.tracking_code:
            lines.append(f"🔍 کد رهگیری: {self.tracking_code}")
        
        # Repair description
        if self.repair_description:
            lines.append(f"📝 تعمیرات: {self.repair_description[:50]}...")
        
        # Cost
        if self.total_cost:
            lines.append(f"💰 هزینه: {self.total_cost:,.0f} ریال")
        
        return "\n".join(lines)

# =====================================================
# Main DataProvider Class
# =====================================================

class DataProvider:
    """API communication manager with caching and error handling"""
    
    def __init__(self, config: BotConfig, redis_client=None):
        self.config = config
        self.redis = redis_client
        self.session: Optional[ClientSession] = None
        self._session_lock = asyncio.Lock()
        
        # Configuration
        self.cache_prefix = "bot:cache:"
        self.auth_token = os.getenv("AUTH_TOKEN", "")
        self.cache_ttl = 300  # 5 minutes
        self.timeout = ClientTimeout(total=30, connect=10, sock_read=20)
        
        # Request tracking
        self._request_count = 0
        self._error_count = 0
        
        logger.info("DataProvider initialized")
    
    # =====================================================
    # Context Manager Support
    # =====================================================
    
    async def __aenter__(self):
        """Async context manager entry"""
        await self.ensure_session()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()
    
    async def close(self):
        """Close all resources"""
        await self.close_session()
        logger.info(f"DataProvider closed - Requests: {self._request_count}, Errors: {self._error_count}")
    
    # =====================================================
    # Cache Methods
    # =====================================================
    
    async def _get_cached(self, key: str) -> Optional[Dict]:
        """Get cached data"""
        if not self.redis:
            return None
        
        try:
            data = await self.redis.get(f"{self.cache_prefix}{key}")
            if data:
                logger.debug(f"Cache hit: {key}")
                return json.loads(data)
        except Exception as e:
            logger.debug(f"Cache miss: {key} - {e}")
        
        return None
    
    async def _set_cached(self, key: str, value: Dict, ttl: int = None) -> None:
        """Set cached data"""
        if not self.redis:
            return
        
        try:
            await self.redis.setex(
                f"{self.cache_prefix}{key}",
                ttl or self.cache_ttl,
                json.dumps(value, ensure_ascii=False)
            )
            logger.debug(f"Cached: {key}")
        except Exception as e:
            logger.debug(f"Cache set failed: {e}")
    
    async def clear_cache(self, pattern: str = "*") -> int:
        """Clear cache entries"""
        if not self.redis:
            return 0
        
        try:
            keys = await self.redis.keys(f"{self.cache_prefix}{pattern}")
            if keys:
                deleted = await self.redis.delete(*keys)
                logger.info(f"Cleared {deleted} cache entries")
                return deleted
        except Exception as e:
            logger.error(f"Cache clear failed: {e}")
        
        return 0
    
    # =====================================================
    # Session Management
    # =====================================================
    
    async def ensure_session(self):
        """Ensure HTTP session exists"""
        async with self._session_lock:
            if not self.session or self.session.closed:
                connector = aiohttp.TCPConnector(
                    limit=100,
                    limit_per_host=30,
                    ttl_dns_cache=300,
                    enable_cleanup_closed=True
                )
                
                self.session = aiohttp.ClientSession(
                    timeout=self.timeout,
                    connector=connector,
                    headers={
                        'User-Agent': 'HamoonBot/1.0',
                        'Accept': 'application/json',
                        'Content-Type': 'application/json'
                    }
                )
                logger.debug("HTTP session created")
    
    async def close_session(self):
        """Close HTTP session"""
        async with self._session_lock:
            if self.session and not self.session.closed:
                await self.session.close()
                await asyncio.sleep(0.25)  # Allow cleanup
                self.session = None
                logger.debug("HTTP session closed")
    
    # =====================================================
    # Core Request Method
    # =====================================================
    
    async def _make_request(
        self,
        method: str,
        url: str,
        json_data: Optional[Dict] = None,
        headers: Optional[Dict] = None,
        retry_count: int = 3
    ) -> Optional[Dict]:
        """Make HTTP request with retry and error handling"""
        await self.ensure_session()
        
        # Prepare headers
        request_headers = {'auth-token': self.auth_token} if self.auth_token else {}
        if headers:
            request_headers.update(headers)
        
        self._request_count += 1
        last_error = None
        
        for attempt in range(retry_count):
            try:
                async with self.session.request(
                    method, url, 
                    json=json_data, 
                    headers=request_headers
                ) as response:
                    
                    # Success
                    if response.status == 200:
                        data = await response.json()
                        return data
                    
                    # Not found
                    elif response.status == 404:
                        logger.debug(f"Not found: {url}")
                        return None
                    
                    # Server error - retry
                    elif response.status >= 500:
                        last_error = f"Server error {response.status}"
                        if attempt < retry_count - 1:
                            await asyncio.sleep(2 ** attempt)
                            continue
                    
                    # Client error - don't retry
                    else:
                        text = await response.text()
                        logger.error(f"API error {response.status}: {text[:200]}")
                        self._error_count += 1
                        return None
                        
            except asyncio.TimeoutError:
                last_error = "Timeout"
                if attempt < retry_count - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                    
            except aiohttp.ClientError as e:
                last_error = str(e)
                if attempt < retry_count - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                    
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                self._error_count += 1
                return None
        
        # All retries failed
        logger.error(f"Request failed after {retry_count} attempts: {last_error}")
        self._error_count += 1
        return None
    
    # =====================================================
    # Public API Methods
    # =====================================================
    
    async def get_order_by_number(self, order_number: str) -> Optional[Dict[str, Any]]:
        """Get order by tracking number"""
        if not order_number:
            return None
        
        # Check cache
        cache_key = f"order:num:{order_number}"
        cached = await self._get_cached(cache_key)
        if cached:
            return cached
        
        # Check endpoint
        endpoint = self.config.server_urls.get('number')
        if not endpoint:
            logger.error("Order tracking endpoint not configured")
            return None
        
        # Make request
        response = await self._make_request(
            'POST', endpoint, 
            json_data={'number': order_number}
        )
        
        if not response:
            return None
        
        # Parse and cache
        order_info = self._parse_order_response(response)
        if order_info:
            result = order_info.to_display_dict()
            await self._set_cached(cache_key, result)
            return result
        
        return None
    
    async def get_order_by_serial(self, serial: str) -> Optional[Dict[str, Any]]:
        """Get order by device serial"""
        if not serial:
            return None
        
        # Check cache
        cache_key = f"order:serial:{serial}"
        cached = await self._get_cached(cache_key)
        if cached:
            return cached
        
        # Check endpoint
        endpoint = self.config.server_urls.get('serial')
        if not endpoint:
            logger.error("Serial tracking endpoint not configured")
            return None
        
        # Make request
        response = await self._make_request(
            'POST', endpoint,
            json_data={'serial': serial}
        )
        
        if not response:
            return None
        
        # Parse and cache
        order_info = self._parse_order_response(response)
        if order_info:
            result = order_info.to_display_dict()
            await self._set_cached(cache_key, result)
            return result
        
        return None
    
    async def authenticate_user(self, national_id: str) -> Optional[Dict]:
        """Authenticate user by national ID"""
        if not national_id:
            return None
        
        # Check cache
        cache_key = f"user:nid:{national_id}"
        cached = await self._get_cached(cache_key)
        if cached:
            return cached
        
        # Check endpoint
        endpoint = self.config.server_urls.get('national_id')
        if not endpoint:
            # Return mock data for testing
            logger.warning("Auth endpoint not configured - using mock")
            return {
                'name': 'کاربر آزمایشی',
                'phone': '09121234567',
                'national_id': national_id,
                'authenticated': True
            }
        
        # Make request
        response = await self._make_request(
            'POST', endpoint,
            json_data={'national_id': national_id}
        )
        
        if response:
            user_data = self._parse_user_response(response)
            if user_data:
                await self._set_cached(cache_key, user_data, ttl=1800)  # 30 min
                return user_data
        
        return None
    
    async def get_user_orders(self, national_id: str) -> List[Dict]:
        """Get all orders for a user"""
        if not national_id:
            return []
        
        endpoint = self.config.server_urls.get('user_orders')
        if not endpoint:
            return []
        
        response = await self._make_request(
            'POST', endpoint,
            json_data={'national_id': national_id}
        )
        
        if response:
            orders = response.get('data', response.get('orders', []))
            return [self._parse_order_response({'data': order}).to_display_dict() 
                   for order in orders if order]
        
        return []
    
    async def submit_complaint(
        self, 
        national_id: str, 
        complaint_type: str, 
        text: str
    ) -> Optional[str]:
        """Submit complaint/suggestion"""
        endpoint = self.config.server_urls.get('submit_complaint')
        if not endpoint:
            # Mock response for testing
            return f"MOCK-{datetime.now().timestamp():.0f}"
        
        response = await self._make_request(
            'POST', endpoint,
            json_data={
                'national_id': national_id,
                'type': complaint_type,
                'text': text,
                'timestamp': datetime.now().isoformat()
            }
        )
        
        if response:
            return response.get('ticket_number', response.get('id'))
        
        return None
    
    async def submit_rating(
        self, 
        national_id: str, 
        score: int, 
        comment: str = ""
    ) -> bool:
        """Submit service rating"""
        endpoint = self.config.server_urls.get('submit_rating')
        if not endpoint:
            return True  # Mock success
        
        response = await self._make_request(
            'POST', endpoint,
            json_data={
                'national_id': national_id,
                'score': score,
                'comment': comment,
                'timestamp': datetime.now().isoformat()
            }
        )
        
        return response is not None
    
    async def submit_repair_request(
        self,
        national_id: str,
        description: str,
        contact: str
    ) -> Optional[str]:
        """Submit repair request"""
        endpoint = self.config.server_urls.get('submit_repair')
        if not endpoint:
            return f"MOCK-{datetime.now().timestamp():.0f}"

        response = await self._make_request(
            'POST', endpoint,
            json_data={
                'national_id': national_id,
                'description': description,
                'contact': contact,
                'timestamp': datetime.now().isoformat()
            }
        )

        if response:
            return response.get('request_number', response.get('id'))
        return None

    # =====================================================
    # Response Parsing
    # =====================================================

    def _parse_order_response(self, response: Dict) -> Optional[OrderInfo]:
        """Parse an order API response into OrderInfo dataclass"""
        try:
            data = response.get('data', response)
            devices = data.get('items', data.get('devices', []))
            first = devices[0] if devices else {}

            return OrderInfo(
                order_number=str(data.get('number', '')),
                customer_name=data.get('contactId_name', 'نامشخص'),
                national_id=data.get('contactId_nationalCode', ''),
                device_model=first.get('$$_deviceId', data.get('$$_deviceId', 'نامشخص')),
                serial_number=first.get('serialNumber', data.get('serialNumber', '')),
                status=int(data.get('status', 0)),
                steps=int(data.get('steps', 0)),
                registration_date=data.get('warehouseRecieptId_createdOn', ''),
                pre_reception_date=data.get('preReceptionId_createdOn', ''),
                repair_description=first.get('passDescription'),
                tracking_code=str(data.get('preReceptionId_number', '')),
                total_cost=data.get('factorId_totalPriceWithTax'),
                devices=devices
            )
        except Exception as e:
            logger.error(f"Order parse error: {e}")
            return None

    def _parse_user_response(self, response: Dict) -> Optional[Dict]:
        """Parse user authentication response"""
        try:
            data = response.get('data', response.get('user', response))
            return {
                'name': data.get('name', 'نامشخص'),
                'phone': data.get('phone', '---'),
                'national_id': data.get('national_id', '---'),
                'authenticated': True
            }
        except Exception as e:
            logger.error(f"User parse error: {e}")
            return None


# =====================================================
# Factory Function
# =====================================================

async def create_data_provider(config: BotConfig, redis_client=None) -> DataProvider:
    """Factory to create and initialize data provider"""
    provider = DataProvider(config, redis_client)
    await provider.ensure_session()
    logger.info("✅ DataProvider ready")
    return provider