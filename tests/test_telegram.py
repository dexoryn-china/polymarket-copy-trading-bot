"""TelegramNotifier: event names, formatting, filtered send, attach."""

from __future__ import annotations

from app import events
from app.events import Activity, EventBus
from app.notifications.telegram import (
    ALL_EVENTS,
    DEFAULT_EVENTS,
    TelegramNotifier,
    event_name,
    format_message,
)
from tests.fakes import FakeSession


def test_event_name_system_uses_data_event():
    a = Activity(kind=events.SYSTEM, summary="paused", data={"event": "pause"})
    assert event_name(a) == "pause"
    b = Activity(kind=events.COPY_SUCCESS, summary="ok")
    assert event_name(b) == events.COPY_SUCCESS
    c = Activity(kind=events.SYSTEM, summary="x")
    assert event_name(c) == events.SYSTEM


def test_format_message_includes_summary_and_optional_fields():
    a = Activity(
        kind=events.COPY_SUCCESS,
        summary="whale bought",
        venue="predictions",
        data={"latency_ms": 42, "order_id": "order-abcdef-1234"},
    )
    msg = format_message(a)
    assert "whale bought" in msg
    assert "Copied" in msg
    assert "42" in msg
    assert "order-abcdef" in msg
    assert "<b>" in msg


def _notifier(enabled=True, notify_on=None, session=None) -> TelegramNotifier:
    cfg = {
        "telegram": {
            "enabled": enabled,
            "bot_token": "tok",
            "chat_id": "111",
        }
    }
    if notify_on is not None:
        cfg["telegram"]["notify_on"] = notify_on
    return TelegramNotifier(cfg, session or FakeSession())


def test_on_activity_only_sends_enabled_kinds(monkeypatch):
    sent: list[str] = []
    n = _notifier(notify_on=[events.COPY_SUCCESS, events.ERROR])
    monkeypatch.setattr(n, "send", lambda text: sent.append(text))
    n.on_activity(Activity(kind=events.COPY_SUCCESS, summary="yes"))
    n.on_activity(Activity(kind=events.COPY_FAILURE, summary="no"))
    n.on_activity(Activity(kind=events.ERROR, summary="err"))
    n.on_activity(Activity(kind=events.TARGET_FILL, summary="fill"))
    assert len(sent) == 2
    assert any("yes" in s for s in sent)
    assert any("err" in s for s in sent)


def test_on_activity_defaults_when_notify_on_omitted(monkeypatch):
    sent = []
    n = _notifier(notify_on=None)
    monkeypatch.setattr(n, "send", sent.append)
    n.on_activity(Activity(kind=events.COPY_SKIPPED, summary="skip"))
    n.on_activity(Activity(kind=events.COPY_SUCCESS, summary="ok"))
    n.on_activity(Activity(
        kind=events.SYSTEM,
        summary="Copying started — Prediction markets",
        data={"event": events.COPY_START},
    ))
    assert len(sent) == 2
    assert any("ok" in s for s in sent)
    assert any("▶️" in s and "Copying started" in s for s in sent)
    assert DEFAULT_EVENTS <= ALL_EVENTS
    assert events.COPY_START in DEFAULT_EVENTS
    assert events.COPY_STOP in DEFAULT_EVENTS
    assert events.COPY_SKIPPED not in DEFAULT_EVENTS
    assert events.TARGET_FILL not in DEFAULT_EVENTS
    assert events.ORDER_UPDATE not in DEFAULT_EVENTS


def test_attach_always_subscribes_disabled_does_not_send(monkeypatch):
    bus = EventBus()
    sent: list[str] = []
    disabled = _notifier(enabled=False)
    monkeypatch.setattr(disabled, "send", sent.append)
    disabled.attach(bus)
    assert disabled.on_activity in bus._subs

    bus.emit(events.COPY_SUCCESS, "should-not-send")
    assert sent == []

    disabled.configure({
        "telegram": {"enabled": True, "bot_token": "tok", "chat_id": "111"},
    })
    bus.emit(events.COPY_SUCCESS, "now-send")
    assert len(sent) == 1
    assert "now-send" in sent[0]


def test_configure_live_toggle(monkeypatch):
    sent: list[str] = []
    n = _notifier(enabled=True)
    monkeypatch.setattr(n, "send", sent.append)
    n.on_activity(Activity(kind=events.COPY_SUCCESS, summary="on"))
    assert len(sent) == 1

    n.configure({"telegram": {"enabled": False, "bot_token": "tok", "chat_id": "111"}})
    n.on_activity(Activity(kind=events.COPY_SUCCESS, summary="off"))
    assert len(sent) == 1

    n.configure({"telegram": {"enabled": True, "bot_token": "tok", "chat_id": "111"}})
    n.on_activity(Activity(kind=events.COPY_SUCCESS, summary="on-again"))
    assert len(sent) == 2
    assert "on-again" in sent[-1]


def test_configure_enabled_requires_token():
    n = _notifier(enabled=False)
    try:
        n.configure({"telegram": {"enabled": True, "bot_token": "", "chat_id": "111"}})
        assert False
    except ValueError as e:
        assert "bot_token" in str(e)
    assert n.enabled is False
