"""Telegram notifications via Bot API (sendMessage).

Subscribes to the EventBus; every activity whose kind is enabled in
`telegram.notify_on` is pushed to all configured chats. Sends run as
background tasks so trading latency is unaffected; failures are logged and
never propagate.
"""

import asyncio
import html
import logging

import aiohttp

from app import events
from app.events import Activity, EventBus

log = logging.getLogger("telegram")

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

# Events selectable in `telegram.notify_on` (activity kinds + SYSTEM sub-events).
EVENT_LABELS = {
    events.COPY_START: "Copying started",
    events.COPY_STOP: "Copying stopped",
    events.COPY_SUCCESS: "Trade copied",
    events.COPY_FAILURE: "Copy failed",
    events.COPY_SKIPPED: "Copy skipped",
    events.TARGET_FILL: "Target traded (noisy)",
    events.ORDER_UPDATE: "Resting order finished",
    events.ERROR: "Errors",
    events.STARTUP: "Bot started",
    events.SHUTDOWN: "Bot stopped",
}
ALL_EVENTS = set(EVENT_LABELS)
DEFAULT_EVENTS = ALL_EVENTS - {events.COPY_SKIPPED, events.TARGET_FILL, events.ORDER_UPDATE}

_ICONS = {
    events.STARTUP: "🟢", events.SHUTDOWN: "⚪", events.COPY_START: "▶️", events.COPY_STOP: "⏹",
    events.COPY_SUCCESS: "✅", events.COPY_FAILURE: "❌", events.COPY_SKIPPED: "⏭",
    events.TARGET_FILL: "🎯", events.ORDER_UPDATE: "📋", events.ERROR: "⚠️",
}
_TITLES = {
    events.COPY_SUCCESS: "Copied", events.COPY_FAILURE: "Copy failed", events.COPY_SKIPPED: "Skipped",
    events.TARGET_FILL: "Target trade", events.ORDER_UPDATE: "Order update", events.ERROR: "Error",
}


def _esc(text: object) -> str:
    return html.escape(str(text))


def event_name(a: Activity) -> str:
    """Telegram event name for an activity (system activities carry theirs in data)."""
    if a.kind == events.SYSTEM:
        return str(a.data.get("event") or events.SYSTEM)
    return a.kind


def format_message(a: Activity) -> str:
    name = event_name(a)
    icon = _ICONS.get(name, "ℹ️")
    title = _TITLES.get(name)
    venue = f"[{a.venue}] " if a.venue != events.VENUE_SYSTEM else ""
    head = f"{icon} <b>{_esc(venue + title)}</b>\n" if title else f"{icon} "
    lines = [head + _esc(a.summary)]
    latency = a.data.get("latency_ms")
    if latency is not None:
        lines.append(f"latency: {_esc(latency)}ms")
    order_id = a.data.get("order_id")
    if order_id:
        lines.append(f"order: <code>{_esc(str(order_id)[:14])}</code>")
    return "\n".join(lines)


class TelegramNotifier:
    """Optional Telegram notifier — no-ops when disabled."""

    def __init__(self, config: dict, session: aiohttp.ClientSession):
        self.session = session
        self._pending: set[asyncio.Task] = set()
        self.configure(config)

    def configure(self, config: dict) -> None:
        """(Re)read the `telegram` section — called at startup and on settings changes."""
        tg = config.get("telegram") or {}
        enabled = bool(tg.get("enabled", False))
        bot_token = (tg.get("bot_token") or "").strip()
        chat_ids = self._parse_chat_ids(tg.get("chat_id"))
        notify_on = tg.get("notify_on")
        notify_on = DEFAULT_EVENTS if notify_on is None else set(notify_on)
        if enabled:
            if not bot_token or not chat_ids:
                raise ValueError("telegram.enabled requires bot_token and chat_id")
            unknown = notify_on - ALL_EVENTS
            if unknown:
                raise ValueError(f"telegram.notify_on unknown events: {sorted(unknown)}")
            log.info(f"Telegram notifications ON — {len(chat_ids)} recipient(s)")
        self.enabled, self.bot_token, self.chat_ids, self.notify_on = enabled, bot_token, chat_ids, notify_on

    @staticmethod
    def _parse_chat_ids(raw: object) -> list[str]:
        items = raw if isinstance(raw, (list, tuple)) else [raw]
        out: list[str] = []
        for it in items:
            s = str(it).strip() if it is not None else ""
            if s and s not in out:
                out.append(s)
        return out

    def attach(self, bus: EventBus) -> None:
        # Always subscribed so enabling from the dashboard takes effect live.
        bus.subscribe(self.on_activity)

    def on_activity(self, a: Activity) -> None:
        if self.enabled and event_name(a) in self.notify_on:
            self.send(format_message(a))

    def send(self, text: str) -> None:
        task = asyncio.create_task(self._send(text))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def flush(self, timeout_s: float = 5.0) -> None:
        """Wait briefly for in-flight sends (e.g. on shutdown)."""
        if not self._pending:
            return
        try:
            await asyncio.wait_for(asyncio.gather(*list(self._pending), return_exceptions=True), timeout_s)
        except asyncio.TimeoutError:
            log.warning(f"Telegram flush timed out with {len(self._pending)} pending")

    async def _send(self, text: str) -> None:
        url = TELEGRAM_API.format(token=self.bot_token)
        await asyncio.gather(*(self._send_one(url, c, text) for c in self.chat_ids), return_exceptions=True)

    async def _send_one(self, url: str, chat_id: str, text: str) -> None:
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
        try:
            async with self.session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    log.warning(f"Telegram send failed {resp.status} chat={chat_id}: {body[:200]}")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning(f"Telegram send error chat={chat_id}: {e}")
