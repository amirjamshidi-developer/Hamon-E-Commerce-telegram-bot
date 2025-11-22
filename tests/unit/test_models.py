from datetime import datetime, timedelta
import pytest
from src.models.domain import (
    sanitize_text, clean_numeric_string, parse_date_string,
    Order, Payment, AuthResponse, SubmissionResponse
)
from src.models.user import UserSession
from src.config.enums import UserState


# ---------------- Utility Tests ----------------
@pytest.mark.parametrize("text,expected", [
("   hello\tworld  \n", "hello world"), ("", ""), (None, "")
])
def test_sanitize_text(text, expected): 
    assert sanitize_text(text) == expected

@pytest.mark.parametrize("raw,expected", [(" 22,44a99 ", "224499"), (None, None)])
def test_clean_numeric_string(raw, expected): 
    assert clean_numeric_string(raw) == expected

@pytest.mark.parametrize("val,result", [
    ("2024-03-21 11:22:00", "2024-03-21"), (None, None), ("unknown data", "unknown data")
])
def test_parse_date_string(val, result):
    # covers normal, None, and unknown paths + ValueError fallback
    class BadObj:
        def __str__(self): return "boom string"
        def split(self, _): raise ValueError("boom")
    assert (parse_date_string(val) == result) or ("unknown" in parse_date_string(val))
    assert isinstance(parse_date_string(BadObj()), str)

# ---------------- UserSession ----------------
def test_user_session_lifecycle(monkeypatch):
    s = UserSession(chat_id=100, user_id=200)
    monkeypatch.setattr(s, "expires_at", datetime.now() - timedelta(seconds=1))
    assert s.is_expired()
    s.refresh(15)
    assert s.expires_at > datetime.now() and isinstance(s.last_activity, datetime)

    data = s.to_dict()
    assert {"chat_id", "user_id"} <= data.keys() and s.state == UserState.IDLE

    class DummyCfg: session_timeout_minutes = 60
    from src.config import settings
    monkeypatch.setattr(settings, "get_config", lambda: DummyCfg())
    sess = UserSession.create_with_default_expiry(chat_id=1, user_id=2)
    diff = (sess.expires_at - datetime.now()).total_seconds() / 60
    assert 58 <= diff <= 61


# ---------------- Domain Models ----------------
def test_order_payment_and_fallbacks():
    data = {
        "number": " 00123 ", "$$_contactId": " Amir ", "contactId_nationalCode": "1112223334",
        "contactId_phone": "09351234567", "contactId_cityId": "Tehran",
        "steps": 1, "$$_steps": "Done", "factorId_paymentLink": "https://pay.link",
        "factorPayment": {"id": "pay_123"},
    }
    o = Order.model_validate(data)
    assert (o.order_number, o.customer_name, o.city) == ("00123", "Amir", "Tehran")
    assert o.payment.is_completed and o.has_payment_link and o.is_paid
    assert isinstance(o.registration_date, (str, type(None)))

    obj = Order.model_validate({"number": None, "$$_contactId": "Y", "contactId_nationalCode": "8"})
    assert obj.order_number == "None"  # normalize_numeric_ids fallback


def test_payment_flags(): 
    p = Payment(id="abc")
    assert p.is_completed and p.is_paid


# ---------------- AuthResponse & Submission ----------------
def test_auth_response_and_submission():
    raw = {
        "number": "12", "$$_contactId": "Kamyar", "contactId_nationalCode": "123",
        "contactId_phone": "09", "contactId_cityId": "Tehran",
        "items": [{"$$_deviceId": "D", "serialNumber": "s"}],
    }
    ar = AuthResponse.model_validate(raw)
    assert ar.authenticated and ar.name == "Kamyar"
    assert (ar.national_id, ar.phone_number, ar.city, ar.device_count) == ("123", "09", "Tehran", 1)
    assert not ar.is_paid and not ar.has_payment_link
    assert AuthResponse.model_validate({
        "order": {"number": "7", "$$_contactId": "K", "contactId_nationalCode": "1"}
    }).name == "K"
    assert not AuthResponse.model_validate({
        "order": {"number": "", "$$_contactId": "", "contactId_nationalCode": ""}
    }).authenticated

    base = Order.model_validate({"number": "500", "$$_contactId": "Z", "contactId_nationalCode": "9"})
    wrapped = AuthResponse.model_validate(AuthResponse(order=base))
    assert wrapped.order_number == "500"  # cover property + non‑dict path

    res = SubmissionResponse(success=True, message="OK", ticketNumber="T001")
    ts = datetime.fromisoformat(res.timestamp)
    assert res.success and res.ticket_number == "T001"
    assert abs(datetime.now().timestamp() - ts.timestamp()) < 5
