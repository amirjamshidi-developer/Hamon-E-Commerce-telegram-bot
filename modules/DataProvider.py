"""
Data Provider - Handle The Data's come from server
"""

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiohttp
from aiohttp import ClientSession, ClientTimeout

from .CoreConfig import (
    DEVICE_STATUS,
    STEP_ICONS,
    STEP_PROGRESS,
    WORKFLOW_STEPS,
    BotConfig,
    Validators,
    get_step_info,
    safe_format_date
)

logger = logging.getLogger(__name__)


@dataclass
class OrderInfo:
    """Order information with proper field mapping"""

    # --- Core identifiers ---
    order_number: str
    customer_name: str
    nationalId: str
    phone_number: str
    city: str
    # --- Order-level workflow status ---
    steps: int  # numeric workflow stage
    current_step: str  # text (from WORKFLOW_STEPS)
    status_icon: str  # icon for current step
    progress: int  # percentage (from STEP_PROGRESS)
    progress_bar: str  # text block visual
    # --- Device-level info ---
    device_model: str
    serial_number: str
    device_status: str
    # --- Dates and details ---
    registration_date: str
    pre_reception_date: str
    repair_description: Optional[str] = None
    tracking_code: Optional[str] = None
    total_cost: Optional[int] = None
    payment_link: Optional[str] = None
    factor_payment: Optional[Dict[str, Any]] = None
    devices: Optional[List[Dict[str, Any]]] = None

    def to_display_dict(self) -> Dict[str, Any]:
        """Convert to display format consumable by MessageHandler"""
        return {
            "order_number": self.order_number,
            "customer_name": self.customer_name,
            "phone_number": self.phone_number,
            "city": self.city,
            # Global status 
            "steps": self.steps,
            "current_step": self.current_step,
            "status_icon": self.status_icon,
            "progress": self.progress,
            "progress_bar": self.progress_bar,
            # Device info
            "device_model": self.device_model,
            "serial_number": self.serial_number,
            "device_status": self.device_status,
            # Dates
            "registration_date": safe_format_date(self.registration_date),
            "pre_reception_date": safe_format_date(self.pre_reception_date),
            # Other optional fields
            "tracking_code": self.tracking_code or "---",
            "repair_description": self.repair_description or "---",
            "payment_link": self.payment_link,
            "total_cost": self.total_cost,
            "factor_payment": self.factor_payment or {},
            "devices": self.devices or [],
        }

class DataProvider:
    """API communication manager with caching"""

    def __init__(self, config: BotConfig, redis_client=None):
        self.config = config
        self.redis = redis_client
        self.session: Optional[ClientSession] = None
        self._lock = asyncio.Lock()
        self._session_lock = asyncio.Lock()

        self.cache_prefix = "bot:cache:"
        self.auth_token = os.getenv("AUTH_TOKEN", "")
        self.cache_ttl = 300  # 5 minutes
        self.timeout = ClientTimeout(total=30, connect=10, sock_read=20)

    async def __aenter__(self):
        """Async context manager entry"""
        await self.ensure_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close_session()

    async def _cache_get(self, key: str) -> Optional[Dict]:
        """Get from cache"""
        if not self.redis:
            return None
        try:
            data = await self.redis.get(f"{self.cache_prefix}{key}")
            return json.loads(data) if data else None
        except Exception as e:
            logger.warning(f"Cache get error: {e}")
            return None

    async def _cache_set(self, key: str, value: Dict, ttl: int = 300) -> None:
        """Set cache"""
        if not self.redis:
            return
        try:
            await self.redis.setex(
                f"{self.cache_prefix}{key}",
                ttl,
                json.dumps(value, ensure_ascii=False, default=str)
            )
            logger.debug(f"Cached {key} for {ttl}s")
        except Exception as e:
            logger.warning(f"Cache set error: {e}")

    async def ensure_session(self):
        async with self._session_lock:
            if not self.session or self.session.closed:
                connector = aiohttp.TCPConnector(
                    limit=100,
                    limit_per_host=30,
                    ttl_dns_cache=300,
                    enable_cleanup_closed=True,
                )

                self.session = aiohttp.ClientSession(
                    timeout=self.timeout,
                    connector=connector,
                    headers={
                        "User-Agent": "HamoonBot/1.0",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                )
                logger.debug("HTTP session created")

    async def close_session(self):
        async with self._session_lock:
            if self.session and not self.session.closed:
                await self.session.close()
                await asyncio.sleep(0.1)  # Allow cleanup
                self.session = None
                logger.debug("HTTP session closed")

    async def _make_request(
        self,
        method: str,
        url: str,
        json_data: Optional[Dict] = None,
        params: Optional[Dict] = None,
        headers: Optional[Dict] = None,
        retry_count: int = 2,
    ) -> Optional[Dict]:
        """Make HTTP request with retry and error handling"""
        await self.ensure_session()

        # Prepare headers
        request_headers = {"auth-token": self.auth_token} if self.auth_token else {}
        if headers:
            request_headers.update(headers)

        last_error = None

        for attempt in range(retry_count):
            try:
                async with self.session.request(
                    method, url, json=json_data, params=params, headers=request_headers
                ) as response:

                    if response.status == 200:
                        data = await response.json()
                        return data
                    elif response.status == 404:
                        logger.debug(f"Not found: {url}")
                        return None
                    elif response.status >= 500:
                        last_error = f"Server error {response.status}"
                        if attempt < retry_count - 1:
                            await asyncio.sleep(2**attempt)
                            continue
                    # Client error - don't retry
                    else:
                        text = await response.text()
                        logger.error(f"API error {response.status}: {text[:200]}")
                        return None

            except asyncio.TimeoutError:
                last_error = "Timeout"
                if attempt < retry_count - 1:
                    await asyncio.sleep(2**attempt)
                    continue
            except aiohttp.ClientError as e:
                last_error = str(e)
                if attempt < retry_count - 1:
                    await asyncio.sleep(2**attempt)
                    continue
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                return None

        # All retries failed
        logger.error(f"Request failed after {retry_count} attempts: {last_error}")
        return None

    async def get_order(
        self, identifier: str, id_type: str = "number", force_refresh: bool = False
    ) -> Optional[Dict[str, Any]]:
        """Unified order fetching by different identifier types"""

        logger.info(f"Getting order by {id_type}: {identifier}")

        # Route to appropriate method based on id_type
        if id_type == "national_id" or id_type == "nationalId":
            # For National ID lookup
            cache_key = f"order:nid:{identifier}"

            if not force_refresh:
                cached = await self._cache_get(cache_key)
                if cached:
                    logger.debug(f"Cache hit for National ID {identifier}")
                    return cached

            # Use the National ID endpoint
            endpoint = self.config.server_urls.get(
                "national_id"
            ) or self.config.server_urls.get("nationalId")
            if not endpoint:
                logger.error("National ID endpoint not configured")
                return None
            logger.info(f"Fetching National ID {identifier} from API: {endpoint}")

            json_data = {"nationalId": identifier}
            response = await self._make_request("POST", endpoint, json_data=json_data)

            if response:
                logger.info(
                    f"🔍 RAW RESPONSE: {json.dumps(response, ensure_ascii=False)[:500]}"
                )

                if not response.get("success", True):
                    logger.error(f"API error: {response.get('message')}")
                    return None

                order_info = self._parse_order_response(response)
                if order_info:
                    logger.info(
                        f"✅ Successfully parsed order for National ID {identifier}"
                    )
                    result = order_info.to_display_dict()
                    await self._cache_set(cache_key, result, ttl=self.cache_ttl)
                    return result
                else:
                    logger.error(f"❌ Failed to parse: {response}")

            logger.warning(f"No order found for National ID {identifier}")
            return None

        elif id_type == "number":
            return await self.get_order_by_number(identifier, force_refresh)
        elif id_type == "serial":
            return await self.get_order_by_serial(identifier, force_refresh)
        else:
            logger.error(f"Invalid id_type: {id_type}")
            return None

    async def get_user_orders(self, national_id: str) -> Dict[str, Any]:
        """Get user's orders by national ID"""
        try:
            response = await self._make_request(
                "GET",
                self.config.server_urls.get("user_orders"),
                params={"nationalId": national_id},
            )

            if response and response.get("success", True):
                orders_data = response.get("data", [])
                # Convert to OrderInfo objects
                orders = []
                for order_data in orders_data:
                    order = self._parse_order_response(order_data)
                    if order:
                        orders.append(order.to_display_dict())  # Convert to dict
                
                return {
                    "success": True,
                    "orders": orders,
                    "count": len(orders),
                    "has_more": len(orders_data) > 5 
                }
            else:
                return {
                    "success": False, 
                    "orders": [],
                    "error": "هیچ سفارشی یافت نشد"
                }
                
        except Exception as e:
            logger.error(f"Error getting user orders: {e}")
            return {
                "success": False,
                "orders": [],
                "error": "خطا در دریافت سفارشات"
            }

    async def get_order_by_number(self, order_number: str, force_refresh: bool = False) -> Dict[str, Any]:
        """Get order by tracking number"""
        is_valid, error_msg = Validators.validate_order_number(order_number)
        if not is_valid:
            logger.warning(f"Invalid order number format: {order_number} - {error_msg}")
            return {
                "success": False,
                "error": f"فرمت شماره سفارش نامعتبر: {error_msg}",
                "type": "validation_error"
            }

        cache_key = f"order:number:{order_number}"

        if not force_refresh:
            cached = await self._cache_get(cache_key)
            if cached:
                logger.debug(f"Cache hit for order {order_number}")
                return cached

        try:
            logger.info(f"Fetching order by number: {order_number}")
            
            endpoint = self.config.server_urls.get("number")
            if not endpoint:
                logger.error("Order tracking endpoint not configured")
                return {
                    "success": False,
                    "error": "سرویس پیگیری سفارش در دسترس نیست",
                    "type": "config_error"
                }

            json_data = {"number": order_number}
            response = await self._make_request("POST", endpoint, json_data=json_data)
            
            logger.debug(f"Raw API response for {order_number}: {response}")

            if not isinstance(response, dict):
                logger.error(f"Invalid API response format for {order_number}: {type(response)}")
                return {
                    "success": False,
                    "error": "پاسخ API نامعتبر است",
                    "type": "api_format_error"
                }
            
            if response.get("success") == False:
                error_message = response.get("message", "سفارش یافت نشد") or "خطای ناشناخته"
                logger.warning(f"API error for order {order_number}: {error_message}")
                
                return {
                    "success": False,
                    "error": error_message,
                    "message": error_message,
                    "order_number": order_number,
                    "type": "api_error"
                }
            
            has_order_data = any(
                response.get(field) not in [None, "", "نامشخص", 0, {}] 
                for field in ["id", "order_number", "number", "processNumber"]
            )
            
            if not has_order_data:
                logger.warning(f"No meaningful order data in response for {order_number}")
                return {
                    "success": False,
                    "error": "سفارش در سیستم یافت نشد",
                    "message": "شماره در سیستم یافت نشد",
                    "order_number": order_number,
                    "type": "not_found"
                }
            
            parsed_order = self._parse_order_response(response)
            
            if not parsed_order:
                logger.error(f"Failed to parse valid order data for {order_number}")
                return {
                    "success": False,
                    "error": "خطا در پردازش اطلاعات سفارش",
                    "raw_response": response,  # For debugging
                    "type": "parse_error"
                }
            
            result = parsed_order.to_display_dict()
            result["success"] = True
            
            await self._cache_set(cache_key, result, ttl=self.cache_ttl)
            logger.info(f"Successfully processed order {result['order_number']}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error fetching order {order_number}: {e}", exc_info=True)
            return {
                "success": False,
                "error": f"خطا در دریافت اطلاعات سفارش: {str(e)}",
                "type": "exception"
            }
        
        
    async def get_order_by_serial(self, serial: str, force_refresh: bool = False) -> Dict[str, Any]:
        """Get order by device serial"""
        if not serial:
            return {
                "success": False,
                "error": "شماره سریال خالی است",
                "type": "validation_error"
            }

        is_valid, error_msg = Validators.validate_serial(serial)
        if not is_valid:
            logger.warning(f"Invalid serial format: {error_msg}")
            return {
                "success": False,
                "error": f"فرمت سریال نامعتبر: {error_msg}",
                "type": "validation_error"
            }

        cache_key = f"order:serial:{serial}"

        if not force_refresh:
            cached = await self._cache_get(cache_key)
            if cached:
                logger.debug(f"Cache hit for serial {serial}")
                return cached

        endpoint = self.config.server_urls.get("serial")
        if not endpoint:
            logger.error("Serial tracking endpoint not configured")
            return {
                "success": False,
                "error": "سرویس پیگیری سریال در دسترس نیست",
                "type": "config_error"
            }

        logger.info(f"Fetching serial {serial} from API")

        json_data = {"serial": serial}
        response = await self._make_request("POST", endpoint, json_data=json_data)

        if not response:
            logger.warning(f"No response for serial {serial}")
            return {
                "success": False,
                "error": "خطا در اتصال به سرور",
                "type": "connection_error"
            }

        if not isinstance(response, dict):
            logger.error(f"Invalid response format for serial {serial}")
            return {
                "success": False,
                "error": "پاسخ API نامعتبر است",
                "type": "api_format_error"
            }

        if response.get("success") == False:
            error_msg = response.get("message", "سریال یافت نشد") or "خطای ناشناخته"
            logger.warning(f"API error for serial {serial}: {error_msg}")
            return {
                "success": False,
                "error": error_msg,
                "serial": serial,
                "type": "api_error"
            }

        order_info = self._parse_order_response(response)
        if order_info:
            result = order_info.to_display_dict()
            result["success"] = True 
            await self._cache_set(cache_key, result, ttl=self.cache_ttl)
            logger.info(f"Successfully processed serial {serial}")
            return result
        else:
            logger.warning(f"Failed to parse serial {serial}")
            return {
                "success": False,
                "error": "خطا در پردازش اطلاعات سریال",
                "serial": serial,
                "type": "parse_error"
            }
        

    async def authenticate_user(self, national_id: str) -> Optional[Dict]:
        """Authenticate user by national ID"""
        if not national_id:
            return None

        cache_key = f"user:nid:{national_id}"
        cached = await self._cache_get(cache_key)
        if cached:
            return cached

        endpoint = self.config.server_urls.get("national_id")
        if not endpoint:
            logger.warning("Auth endpoint not configured - using mock")
            return {
                "name": "کاربر آزمایشی",
                "phone_number": "09121234567",
                "city": "تهران",
                "nationalId": national_id,
                "authenticated": True,
            }

        response = await self._make_request(
            "POST", endpoint, json_data={"nationalId": national_id}
        )

        if response and response.get("success", True):
            data = response.get("data", response)
            if data:
                user_data = {
                    "name": data.get("$$_contactId", "نامشخص"),
                    "phone_number": data.get("contactId_phone", "نامشخص"),
                    "city": data.get("contactId_cityId", "نامشخص"),
                    "nationalId": (
                        data.get("contactId_nationalCode")
                        or data.get("contactId_nationalId")
                        or national_id
                    ),
                    "authenticated": True,
                }
                await self._cache_set(cache_key, user_data, ttl=1800)
                logger.info(f"✅ User authenticated: {user_data['name']}")
                return user_data
            else:
                logger.warning(f"No user data in response for {national_id}")
                return {"error": "اطلاعات کاربر یافت نشد"}

        logger.warning(f"Authentication failed for {national_id}")
        return {"error": "احراز هویت ناموفق"}

    async def submit_complaint(
        self,
        national_id: str,
        complaint_type: str,
        description: str,
        user_name: str = None,
        phone_number: str = None,
    ) -> Optional[Dict[str, Any]]:
        """Submit complaint to API with validation and error handling"""
        if not all([national_id, complaint_type, description]):
            logger.error("Missing required complaint fields")
            return {"success": False, "error": "اطلاعات ناقص"}

        if len(description.strip()) < 10:
            logger.error("Complaint description too short")
            return {"success": False, "error": "توضیحات باید حداقل ۱۰ کاراکتر باشد"}

        if self.redis:
            rate_key = f"complaint:rate:{national_id}"
            count = await self.redis.incr(rate_key)
            if count == 1:
                await self.redis.expire(rate_key, 3600)  # 1 hour
            if count > 3:  # Max 3 complaints per hour
                return {"success": False, "error": "محدودیت ارسال شکایت (حداکثر ۳ در ساعت)"}
        
        result = await self.submit_data(
            "complaint",
            national_id,
            complaint_type=complaint_type,
            description=description,
            user_name=user_name or "",
            phone_number=phone_number or ""
        )
        
        return result

    async def submit_repair_request(self, nationalId: str, description: str, contact: str = None) -> Optional[Dict[str, Any]]:
        """Submit repair request - FIXED: Return structured response"""
        if not description or len(description.strip()) < 10:
            return {"success": False, "error": "توضیحات تعمیر باید حداقل ۱۰ کاراکتر باشد"}
        
        result = await self.submit_data(
            "repair",
            nationalId,
            description=description,
            contact=contact or ""
        )
        
        return result

    def _parse_order_response(self, response: Dict) -> Optional[OrderInfo]:
        """Parse order API response"""
        try:
            if isinstance(response, dict):
                data = response.get("data", response)
            elif isinstance(response, list) and response:
                data = response[0]
            else:
                data = {}
            
            if not isinstance(data, dict):
                logger.warning("Invalid data structure in response")
                return None        

            order_num_raw = (
                data.get("number") or 
                data.get("processNumber") or 
                data.get("orderNumber") or 
                data.get("id")
            )
            
            if not order_num_raw or str(order_num_raw).strip() in ["", "null", None]:
                logger.warning("No valid order number found in response")
                return None

            # Device parsing - with safe defaults
            devices_raw = data.get("items", data.get("devices", [])) or []
            normalized_devices = []
            
            for d in devices_raw:
                if not isinstance(d, dict):
                    continue
                
                status_raw = d.get("status", 0)
                if isinstance(status_raw, str):
                    try:
                        status_code = int(status_raw)
                    except ValueError:
                        # Try to map string status to code
                        rev_device_status = {v: k for k, v in getattr(self.config, 'DEVICE_STATUS', {}).items()}
                        status_code = rev_device_status.get(status_raw.strip(), 0)
                else:
                    status_code = int(status_raw) if status_raw is not None else 0
                
                normalized_devices.append({
                    "model": d.get("$$_deviceId", d.get("deviceModel", d.get("model", "نامشخص"))),
                    "serial": d.get("serialNumber", d.get("serial", "---")),
                    "status": getattr(self.config, 'DEVICE_STATUS', {}).get(status_code, "نامشخص"),
                    "status_code": status_code,
                    "passDescription": d.get("passDescription", "")
                })
            
            # Use first device or default
            first_device = normalized_devices[0] if normalized_devices else {
                "model": "نامشخص", 
                "serial": "---", 
                "status": "نامشخص",
                "status_code": 0,
                "passDescription": ""
            }

            # Status parsing
            steps_raw = (
                data.get("steps") or 
                data.get("status") or 
                data.get("currentStep") or 
                0
            )
            
            if isinstance(steps_raw, str):
                try:
                    steps_int = int(steps_raw)
                except ValueError:
                    rev_steps = {v: k for k, v in WORKFLOW_STEPS.items()}
                    steps_int = rev_steps.get(steps_raw.strip(), 0)
            else:
                steps_int = int(steps_raw) if steps_raw is not None else 0
            
            step_info = get_step_info(steps_int)

            #Use the safe date formatter
            reg_date_raw = data.get("warehouseRecieptId_createdOn", data.get("createdOn", ""))
            pre_date_raw = data.get("preReceptionId_createdOn", "")
            
            reg_date = safe_format_date(reg_date_raw, "نامشخص")
            pre_date = safe_format_date(pre_date_raw, "نامشخص")

            # Cost parsing - safe conversion
            total_cost_raw = data.get("factorId_totalPriceWithTax", data.get("totalCost", None))
            total_cost = None
            if total_cost_raw is not None and str(total_cost_raw).strip() not in ["", "null"]:
                try:
                    total_cost = int(float(str(total_cost_raw)))
                except (ValueError, TypeError):
                    total_cost = None

            order_info = OrderInfo(
                order_number=str(order_num_raw).strip(),
                customer_name=data.get("$$_contactId", data.get("customerName", "نامشخص")),
                phone_number=data.get("contactId_phone", data.get("phoneNumber", "")),
                nationalId=data.get("contactId_nationalCode") or data.get("contactId_nationalId") or "",
                city=data.get("contactId_cityId", data.get("city", "نامشخص")),
                steps=steps_int,
                current_step=step_info["text"],
                status_icon=step_info["icon"],
                progress=step_info["progress"],
                progress_bar=step_info['bar'],
                device_model=first_device["model"],
                serial_number=first_device["serial"],
                device_status=first_device["status"],
                registration_date=reg_date,
                pre_reception_date=pre_date,
                repair_description=first_device.get("passDescription", ""),
                tracking_code=str(data.get("preReceptionId_number", "")) if data.get("preReceptionId_number") else None,
                total_cost=total_cost,
                payment_link=data.get("factorId_paymentLink"),
                factor_payment=data.get("factorPayment", {}),
                devices=normalized_devices,
            )
            
            if (order_info.order_number == "نامشخص" and 
                order_info.customer_name == "نامشخص" and 
                order_info.device_model == "نامشخص"):
                logger.warning("Parsed order contains no meaningful data")
                return None
            
            logger.debug(f"✅ Successfully parsed order {order_info.order_number} - Step: {steps_int}, Cost: {total_cost}")
            return order_info

        except Exception as e:
            logger.error(f"❌ Error parsing order response: {e}", exc_info=True)
            return None
        

    async def submit_data(
        self, 
        submission_type: str, 
        national_id: str, 
        **kwargs
    ) -> Dict[str, Any]:
        """Unified submission method - FIXED: Returns structured response"""
        endpoint = self.config.server_urls.get(f"submit_{submission_type}")

        if not endpoint:
            # Mock response - Return structured dict
            mock_id = f"MOCK-{submission_type.upper()}-{int(datetime.now().timestamp())}"
            logger.info(f"Using mock {submission_type} submission: {mock_id}")
            return {
                "success": True,
                "ticket_number": mock_id,
                "message": f"درخواست {submission_type} ثبت شد (حالت آزمایشی)",
                "submission_type": submission_type
            }

        json_data = {
            "nationalId": national_id.strip(),
            "submissionType": submission_type,
            "timestamp": datetime.now().isoformat(),
            **kwargs
        }

        if submission_type == "complaint" and not json_data.get("description"):
            return {
                "success": False,
                "error": "توضیحات شکایت الزامی است"
            }
        
        if submission_type == "repair" and not json_data.get("description"):
            return {
                "success": False,
                "error": "توضیحات تعمیر الزامی است"
            }

        logger.info(f"Submitting {submission_type} for nationalId: {national_id}")
        response = await self._make_request("POST", endpoint, json_data=json_data)

        if response:
            if response.get("success", True):
                ticket_number = (
                    response.get("ticketNumber") or 
                    response.get("ticket_number") or 
                    response.get("id") or 
                    f"REF-{int(datetime.now().timestamp())}"
                )
                
                if self.redis:
                    cache_key = f"{submission_type}:{ticket_number}"
                    await self._cache_set(cache_key, {
                        "nationalId": national_id,
                        "type": submission_type,
                        "ticket": ticket_number,
                        "submitted_at": datetime.now().isoformat()
                    }, ttl=86400)  # 24 hours
                
                logger.info(f"✅ {submission_type.capitalize()} submitted: {ticket_number}")
                return {
                    "success": True,
                    "ticket_number": ticket_number,
                    "message": f"درخواست {submission_type} با موفقیت ثبت شد",
                    "submission_type": submission_type
                }
            else:
                error_msg = response.get("message", "خطای ناشناخته در سرور")
                logger.error(f"❌ {submission_type} submission failed: {error_msg}")
                return {
                    "success": False,
                    "error": error_msg,
                    "submission_type": submission_type
                }
        
        logger.error(f"❌ No response from {submission_type} API")
        return {
            "success": False,
            "error": "خطا در اتصال به سرور",
            "submission_type": submission_type
        }

async def create_data_provider(config: BotConfig, redis_client=None) -> DataProvider:
    """Factory initializer for DataProvider."""
    provider = DataProvider(config, redis_client)
    await provider.ensure_session()
    logger.info("✅ DataProvider ready")
    return provider
