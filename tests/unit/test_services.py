import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from pydantic import BaseModel
from src.services.api import APIService
from src.services.notifications import NotificationService
from src.services.exceptions import (
    ConfigurationError,
    APIResponseError,
    APIValidationError,
    APINetworkError,
    APIAuthenticationError,
)

# ---------------------- fixtures ----------------------
@pytest.fixture
def dummy_settings(mocker):
    s = mocker.Mock()
    s.get_endpoint.side_effect = lambda k: f"https://t/api/{k}" if "bad" not in k else None
    return s

@pytest.fixture
def dummy_client(mocker):
    c = AsyncMock()
    c.request.return_value = SimpleNamespace(success=True, status=200, data={"id": 1})
    return c

@pytest.fixture
def service(dummy_client, dummy_settings):
    return APIService(dummy_client, dummy_settings)


# ---------------------- APIService ----------------------
@pytest.mark.asyncio
async def test_make_request_success(service):
    class M(BaseModel): id: int
    result = await service._make_request("get", "ok", model_to_validate=M)
    assert isinstance(result, M) and result.id == 1

@pytest.mark.asyncio
async def test_make_request_no_endpoint(service):
    with pytest.raises(ConfigurationError):
        await service._make_request("get", "bad_key", None)

@pytest.mark.asyncio
async def test_make_request_error_branches(service, dummy_client):
    for st, exc in [(401, APIAuthenticationError), (500, APIResponseError)]:
        dummy_client.request.return_value = SimpleNamespace(success=False, status=st, error="err")
        with pytest.raises(exc):
            await service._make_request("get", "x", None)

    for data in ({"success": False}, None):
        dummy_client.request.return_value = SimpleNamespace(success=True, status=200, data=data)
        with pytest.raises(APIResponseError):
            await service._make_request("get", "x", None)

@pytest.mark.asyncio
async def test_validation_and_network_error(service, dummy_client):
    dummy_client.request.return_value = SimpleNamespace(success=True, status=200, data={"bad": "x"})
    class M(BaseModel): id: int
    with pytest.raises(APIValidationError):
        await service._make_request("get", "x", M)

    dummy_client.request.side_effect = asyncio.TimeoutError()
    with pytest.raises(APINetworkError):
        await service._make_request("get", "x", None)

@pytest.mark.asyncio
async def test_force_refresh_flow(mocker, dummy_settings):
    c = AsyncMock()
    c.cache = AsyncMock()
    c.request.return_value = SimpleNamespace(success=True, status=200, data={"id": 9})
    s = APIService(c, dummy_settings)
    out = await s._make_request("get", "ok", None, force_refresh=True)
    assert out == {"id": 9}
    c.cache.invalidate.assert_awaited()

@pytest.mark.asyncio
async def test_model_validation_success_and_empty_invalid_cases(dummy_settings):
    class M(BaseModel): id: int
    c = AsyncMock()
    s = APIService(c, dummy_settings)

    c.request.return_value = SimpleNamespace(success=True, status=200, data={"id": 55})
    r = await s._make_request("get", "ok", model_to_validate=M)
    assert isinstance(r, M) and r.id == 55

    for data in ({}, {"success": False}):
        c.request.return_value = SimpleNamespace(success=True, status=200, data=data)
        with pytest.raises(APIResponseError):
            await s._make_request("get", "ok", None)

    c.request.return_value = SimpleNamespace(success=True, status=200, data={"id": "bad"})
    with pytest.raises(APIValidationError):
        await s._make_request("get", "ok", model_to_validate=M)

@pytest.mark.asyncio
async def test_make_request_list_data_and_no_model(dummy_settings):
    """Covers payload['data'] as single-item list & flow without validation."""
    c = AsyncMock()
    payload = {"data": [{"id": 33, "ok": True}]}
    c.request.return_value = SimpleNamespace(success=True, status=200, data=payload)
    s = APIService(c, dummy_settings)
    result = await s._make_request("get", "ok", None)
    assert isinstance(result, dict) and result["id"] == 33

@pytest.mark.asyncio
async def test_make_request_handles_client_error(dummy_settings):
    """Covers aiohttp.ClientError branch."""
    import aiohttp
    c = AsyncMock()
    c.request.side_effect = aiohttp.ClientError("bad net")
    s = APIService(c, dummy_settings)
    with pytest.raises(APINetworkError):
        await s._make_request("post", "ok", None)

@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["submit_complaint", "submit_repair_request"])
async def test_submit_failures(service, mocker, method):
    mocker.patch.object(service, "_make_request", return_value={"success": False, "message": "fail"})
    with pytest.raises(APIResponseError):
        await getattr(service, method)(1, "desc", "sn")

def test_exception_strs():
    err = APIResponseError(400, "boom")
    assert "[400]" in str(err)
    assert "boom" in str(err)
    assert "ConfigurationError" in str(ConfigurationError("x"))


# ---------------------- APIService Public Workflows ----------------------
@pytest.mark.asyncio
async def test_authenticate_and_get_orders(service, mocker):
    from src.models.domain import Order
    auth_response_data = {
        "data": {
            "number": 70231,
            "$$_contactId": "رامین اسدبیگی",
            "contactId_nationalCode": "3970165857",
            "contactId_phone": "09368501337",
            "contactId_cityId": "همدان تویسرکان",
            "steps": 50,
            "$$_steps": "پایان عملیات",
            "items": [
                {
                    "$$_deviceId": "ANFU AF85",
                    "serialNumber": "05HEC050505",
                    "status": "50"
                }
            ],
            "factorId_paymentLink": "https://cms.hamoonpay.com/l/e6vQF",
            "factorPayment": None
        },
        "success": True
    }
    mocker.patch.object(
        service, 
        "_make_request", 
        return_value=Order.model_validate(auth_response_data["data"])
    )
    
    auth_result = await service.authenticate_user("3970165857")
    
    assert auth_result.authenticated is True
    assert auth_result.order.order_number == "70231"
    assert auth_result.name == "رامین اسدبیگی"
    
    order_response = {
        "data": {
            "number": 72530,
            "$$_contactId": "عاطفه بحریپور",
            "contactId_nationalCode": "1362405728",
            "contactId_phone": "09924081915",
            "contactId_cityId": "آذربایجان شرقی تبریز",
            "steps": 0,
            "$$_steps": "ورود مرسوله",
            "items": [
                {
                    "$$_deviceId": "ANFU AF75",
                    "serialNumber": "05HEC034461",
                    "status": "0"
                }
            ],
            "factorId_paymentLink": ""
        }
    }
    
    mocker.patch.object(
        service, 
        "_make_request", 
        return_value=Order.model_validate(order_response["data"])
    )
    
    order_result = await service.get_order_by_number("72530")
    assert order_result.order_number == "72530"
    assert order_result.customer_name == "عاطفه بحریپور"
    
    serial_result = await service.get_order_by_serial("05HEC034461")
    assert serial_result.order_number == "72530"

@pytest.mark.asyncio
async def test_submit_inline_failures(service, mocker):
    mocker.patch("src.config.enums.ComplaintType.map_to_server", return_value={"subject_guid": "x", "unit": "u"})
    mocker.patch.object(service, "_make_request", return_value={"success": False, "message": "fail"})
    with pytest.raises(APIResponseError):
        await service.submit_complaint(1, "b", "cid")

    obj = type("R", (), {"success": False, "message": "fail"})
    mocker.patch.object(service, "_make_request", return_value=obj)
    with pytest.raises(APIResponseError):
        await service.submit_repair_request("desc", "sn")

@pytest.mark.asyncio
async def test_submit_methods_success(service, mocker):
    from src.models.domain import SubmissionResponse
    mocker.patch("src.config.enums.ComplaintType.map_to_server", return_value={"subject_guid": "guid", "unit": 2})
    payload = {"success": True, "message": "ok", "ticketNumber": "T001", "recordId": "RID"}
    mocker.patch.object(service, "_make_request", return_value=SubmissionResponse.model_validate(payload))
    r1 = await service.submit_complaint(1, "msg", "11")
    assert r1.ticket_number == "T001" and r1.success
    r2 = await service.submit_repair_request("desc", "sn")
    assert r2.ticket_number == "T001"

@pytest.mark.asyncio
async def test_submit_methods_fail(service, mocker):
    mocker.patch("src.config.enums.ComplaintType.map_to_server", return_value={"subject_guid": "guid", "unit": "unit"})
    mocker.patch.object(service, "_make_request", side_effect=APIResponseError(status_code=422, error_detail="bad"))
    with pytest.raises(APIResponseError):
        await service.submit_complaint(1, "b", "cid")
    mocker.patch.object(service, "_make_request", side_effect=APIResponseError(status_code=404, error_detail="empty"))
    with pytest.raises(APIResponseError):
        await service.submit_repair_request("desc", "sn")


# ---------------------- NotificationService ----------------------
@pytest.mark.asyncio
async def test_send_and_error_branches(mocker):
    from aiogram.exceptions import TelegramServerError
    bot, sm = AsyncMock(), AsyncMock()
    n = NotificationService(bot, sm)

    bot.send_message.return_value = SimpleNamespace(message_id=10)
    assert await n._send(1, "ok")

    bot.send_message.side_effect = TelegramServerError(method="sendMessage", message="fail")
    assert not await n._send(2, "bad")

    bot.send_message.side_effect = Exception("boom")
    assert not await n._send(3, "err")

@pytest.mark.asyncio
async def test_event_notifications(mocker):
    bot, sm = AsyncMock(), AsyncMock()
    n = NotificationService(bot, sm)
    mocker.patch("src.services.notifications.WorkflowSteps.get_step_info",
                 return_value={"icon": "📦", "name": "آماده‌سازی"})
    await n.order_status_changed(1, "ORD1", 2, "در حال ارسال")
    await n.session_expired(1)
    await n.rate_limit_exceeded(1, 60)
    await n.general_error(1, retry_callback="cb:data")
    cb = Mock()
    cb.pack.return_value = "cb:info"
    await n.general_error(1, retry_callback=cb)
    bot.send_message.assert_called()

@pytest.mark.asyncio
async def test_broadcast_flows_all_cases(mocker):
    bot, sm = AsyncMock(), AsyncMock()
    n = NotificationService(bot, sm)

    sm.get_all_chat_ids.return_value = [1, 2]
    bot.send_message.return_value = SimpleNamespace(message_id=1)
    assert await n.broadcast("msg") == 2

    bot.send_message.side_effect = Exception("fail")
    sm.get_all_chat_ids.return_value = [1]
    assert await n.broadcast("msg") == 0

    async def send_side(chat_id, text, **kwargs):
        if chat_id == 2:
            raise Exception("bot err")
        return SimpleNamespace(message_id=chat_id)
    bot.send_message.side_effect = send_side
    sm.get_all_chat_ids.return_value = [1, 2, 3]
    assert await n.broadcast("msg") == 2

    sm.get_all_chat_ids.return_value = []
    assert await n.broadcast("none") == 0

