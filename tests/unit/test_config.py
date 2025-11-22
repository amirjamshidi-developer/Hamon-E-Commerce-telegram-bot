import os
import json
import builtins
import logging
import pytest
from json import JSONDecodeError
from src.config.settings import Settings, get_config
from src.config.enums import WorkflowSteps, ComplaintType, DeviceStatus, UserState


# ==================== Environment & Settings ==================== #

def test_missing_telegram_token_raises(monkeypatch, app_settings):
    assert app_settings.telegram_token == os.getenv("TELEGRAM_BOT_TOKEN")
    assert app_settings.redis_url == os.getenv("REDIS_URL")
    
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    Settings._instance = None
    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN is required"):
        Settings.from_env()


# ==================== Enums ==================== #
def test_user_state():
    assert UserState.WAITING_NATIONAL_ID.is_waiting()
    assert UserState.AUTHENTICATED.is_authenticated()
    assert UserState.WAITING_COMPLAINT_TYPE.requires_auth()

def test_workflow_steps_comprehensive():
    WorkflowSteps.update_display_names({3: "Custom"})
    assert "Custom" in WorkflowSteps.REPAIR.display_name
    
    WorkflowSteps._dynamic_names = {3: None}
    assert WorkflowSteps.REPAIR.display_name == "تعمیرات"
    WorkflowSteps._dynamic_names = {}
    
    info = WorkflowSteps.get_step_info(3)
    assert info["icon"] == "🔧"
    assert WorkflowSteps.get_step_info(999)["icon"] == "❓"
    
    assert WorkflowSteps.REPAIR.is_active()
    assert WorkflowSteps.COMPLETED.is_completed()
    assert WorkflowSteps.STALLED.is_stalled()
    assert WorkflowSteps.INVOICING.is_payable()
    assert WorkflowSteps.PRE_ACCEPTANCE.can_edit()


def test_complaint_type():
    assert ComplaintType.from_id(1).code == "device_issue"
    assert ComplaintType.map_to_server(1)["unit"] >= 0
    with pytest.raises(ValueError):
        ComplaintType.from_id(999)

    options = ComplaintType.get_keyboard_options()
    assert len(options) > 0
    assert "خرابی و تعمیرات دستگاه" in options[0]["text"]


@pytest.mark.parametrize("val,expected", [
    (3, "در حال تعمیر"),
    ("در حال تعمیر", "در حال تعمیر"),
    ("garbage", "نامشخص"),
    (None, "نامشخص"),
    (999, "نامشخص"),
    ("  invalid_status  ", "نامشخص"),
])
def test_device_status_display(val, expected):
    assert expected in DeviceStatus.get_display(val)


# ==================== Singleton & Thread Safety ==================== #

@pytest.mark.parametrize("reload,differs", [(False, False), (True, True)])
def test_singleton_lifecycle(reload, differs):
    s1 = Settings.get_instance()
    s2 = Settings.get_instance(force_reload=reload)
    assert (s1 is not s2) == differs
    assert get_config() is Settings.get_instance()


def test_thread_safety(monkeypatch):
    acquired = []
    orig_lock = Settings._lock
    
    class TrackedLock:
        def __enter__(self): acquired.append(1); return orig_lock.__enter__()
        def __exit__(self, *a): return orig_lock.__exit__(*a)
    
    monkeypatch.setattr(Settings, "_lock", TrackedLock())
    Settings._instance = None
    Settings.get_instance()
    assert acquired


# ==================== Dynamic Updates ==================== #

def test_dynamic_updates(app_settings, config_file):
    assert app_settings.get_endpoint("base") == os.getenv("SERVER_URL")
    assert app_settings.get_endpoint("nonexistent") is None

    orig_token = app_settings.telegram_token
    app_settings.update_from_dict({
        "maintenance_mode": "true",
        "cache_ttl_seconds": "500",
        "telegram_token": "hacked"
    }, persist=True)
    
    assert app_settings.maintenance_mode is True
    assert app_settings.cache_ttl_seconds == 500
    assert app_settings.telegram_token == orig_token
    assert config_file.exists()


@pytest.mark.parametrize("val,exp", [
    ("true", True), ("1", True), ("yes", True),
    ("false", False), ("0", False), ("no", False),
])
def test_bool_coercion(app_settings, val, exp):
    app_settings.update_from_dict({"maintenance_mode": val}, persist=False)
    assert app_settings.maintenance_mode == exp


def test_invalid_type_coercion_error(app_settings):
    """Cover exception handling in update_from_dict type coercion."""
    original_val = app_settings.cache_ttl_seconds
    
    app_settings.update_from_dict({
        "cache_ttl_seconds": "not_a_number"
    }, persist=False)
    
    assert app_settings.cache_ttl_seconds == "not_a_number"
    
    app_settings.cache_ttl_seconds = original_val


# ==================== Persistence & Errors ==================== #

@pytest.mark.parametrize("exists,fail,persist", [
    (True, False, False),   # exists, no fail, no persist
    (False, False, True),   # new file, persist
    (True, True, False),    # exists, fails on write
])
def test_persistence(config_file, monkeypatch, exists, fail, persist, caplog):
    if exists:
        config_file.write({"a": 1})
    
    s = Settings.get_instance(force_reload=True)
    
    if fail:
        monkeypatch.setattr(builtins, "open", lambda *a, **k: (_ for _ in ()).throw(OSError("fail")))
        with caplog.at_level(logging.ERROR):
            s._persist_updates({"b": 2})
        assert "fail" in caplog.text
    else:
        s._persist_updates({"b": 2})
        assert config_file.exists()

def test_corrupt_json_handling(config_file, monkeypatch, caplog):
    config_file.write({"x": 1})
    
    monkeypatch.setattr(json, "load", lambda *_: (_ for _ in ()).throw(JSONDecodeError("bad", "{", 1)))
    
    Settings._instance = None
    with caplog.at_level(logging.WARNING):
        Settings.get_instance(force_reload=True)
    
    assert "corrupt" in caplog.text.lower()
