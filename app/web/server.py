"""Dashboard HTTP server: REST API + live websocket + built UI (app/web/static).

All routes live under /api. When `web.token` is set every API call needs
`Authorization: Bearer <token>` (or `?token=` for the websocket).
"""

import asyncio
import hmac
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

import orjson
from aiohttp import WSMsgType, web

from app.events import Activity
from app.runtime import Runtime
from app.targets import TargetConflict, TargetError

log = logging.getLogger("web")

STATIC_DIR = Path(__file__).resolve().parent / "static"
STATUS_PUSH_INTERVAL_S = 2.0
WS_QUEUE_MAX = 500
ACTIVITY_PAGE_MAX = 500

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]

_NOT_BUILT = """<!doctype html><meta charset=utf-8><title>Polymarket Copy Bot</title>
<body style="font-family:system-ui;background:#0b0e14;color:#e6e6e6;padding:3rem">
<h2>Dashboard not built</h2><p>The API is running. Build the UI once:</p>
<pre style="background:#151a23;padding:1rem;border-radius:8px">cd ui
npm install
npm run build</pre><p>then reload this page.</p></body>"""


def _json(data: Any, status: int = 200) -> web.Response:
    return web.Response(body=orjson.dumps(data), status=status, content_type="application/json")


def _error(status: int, message: str) -> web.Response:
    return _json({"error": message}, status=status)


class DashboardServer:
    def __init__(self, runtime: Runtime, host: str, port: int, token: str = "") -> None:
        self.runtime = runtime
        self.host = host
        self.port = port
        self.token = token or ""
        self._clients: dict[web.WebSocketResponse, asyncio.Queue] = {}
        self._runner: Optional[web.AppRunner] = None
        self.app = self._build_app()

    # ── App ──

    def _build_app(self) -> web.Application:
        app = web.Application(middlewares=[self._errors_mw, self._auth_mw])
        r = app.router
        r.add_get("/api/meta", self.meta)
        r.add_get("/api/status", self.status)
        r.add_post("/api/pause", self.pause)
        r.add_put("/api/copy", self.select_venue)
        r.add_post("/api/copy/start", self.start_copy)
        r.add_post("/api/copy/stop", self.stop_copy)
        r.add_get("/api/targets", self.list_targets)
        r.add_post("/api/targets", self.create_target)
        r.add_put("/api/targets/{id}", self.update_target)
        r.add_patch("/api/targets/{id}", self.patch_target)
        r.add_delete("/api/targets/{id}", self.delete_target)
        r.add_get("/api/settings", self.get_settings)
        r.add_put("/api/settings", self.update_settings)
        r.add_get("/api/positions", self.positions)
        r.add_get("/api/orders", self.orders)
        r.add_get("/api/activity", self.activity)
        r.add_get("/api/ws", self.ws)
        r.add_route("*", "/api/{tail:.*}", self.not_found)
        r.add_get("/{tail:.*}", self.spa)
        return app

    @web.middleware
    async def _errors_mw(self, request: web.Request, handler: Handler) -> web.StreamResponse:
        try:
            return await handler(request)
        except TargetError as e:
            return _error(400, str(e))
        except TargetConflict as e:
            return _error(409, str(e))
        except KeyError:
            return _error(404, "not found")
        except web.HTTPException:
            raise
        except Exception as e:
            log.exception(f"{request.method} {request.path} failed")
            return _error(500, f"internal error: {e}")

    @web.middleware
    async def _auth_mw(self, request: web.Request, handler: Handler) -> web.StreamResponse:
        if self.token and request.path.startswith("/api/"):
            header = request.headers.get("Authorization", "")
            supplied = header[7:] if header.startswith("Bearer ") else request.query.get("token", "")
            if not hmac.compare_digest(supplied.encode(), self.token.encode()):
                return _error(401, "unauthorized")
        return await handler(request)

    async def start(self) -> None:
        self._runner = web.AppRunner(self.app, access_log=None)
        await self._runner.setup()
        await web.TCPSite(self._runner, self.host, self.port).start()
        log.info(f"dashboard on http://{self.host}:{self.port}"
                 + ("" if STATIC_DIR.joinpath("index.html").exists() else " (UI not built — run `npm install && npm run build` in ui/)"))

    async def run(self, shutdown: asyncio.Event) -> None:
        await self.start()
        unsubscribe = self.runtime.bus.subscribe(self._on_activity)
        try:
            while not shutdown.is_set():
                try:
                    await asyncio.wait_for(shutdown.wait(), timeout=STATUS_PUSH_INTERVAL_S)
                except asyncio.TimeoutError:
                    pass
                if self._clients:
                    self._broadcast({"type": "status", "status": self.runtime.status()})
        finally:
            unsubscribe()
            await self.stop()

    async def stop(self) -> None:
        for ws in list(self._clients):
            await ws.close()
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    # ── Helpers ──

    @staticmethod
    async def _body(request: web.Request) -> dict:
        try:
            data = await request.json(loads=orjson.loads)
        except Exception:
            raise TargetError("request body must be JSON") from None
        if not isinstance(data, dict):
            raise TargetError("request body must be a JSON object")
        return data

    @staticmethod
    def _int_param(request: web.Request, name: str, default: Optional[int] = None) -> Optional[int]:
        raw = request.query.get(name)
        if raw in (None, "", "null"):
            return default
        try:
            return int(raw)
        except ValueError:
            raise TargetError(f"{name} must be an integer") from None

    # ── Routes ──

    async def meta(self, request: web.Request) -> web.Response:
        return _json(self.runtime.meta())

    async def status(self, request: web.Request) -> web.Response:
        return _json(self.runtime.status())

    async def pause(self, request: web.Request) -> web.Response:
        paused = (await self._body(request)).get("paused")
        if not isinstance(paused, bool):
            raise TargetError("paused must be true/false")
        return _json(self.runtime.set_paused(paused))

    async def select_venue(self, request: web.Request) -> web.Response:
        venue = (await self._body(request)).get("venue")
        if not isinstance(venue, str):
            raise TargetError("body must be {venue}")
        return self._status_changed(self.runtime.select_venue(venue))

    async def start_copy(self, request: web.Request) -> web.Response:
        venue = (await self._body(request)).get("venue") if request.can_read_body else None
        if venue is not None and not isinstance(venue, str):
            raise TargetError("venue must be a string")
        return self._status_changed(await self.runtime.start_copy(venue))

    async def stop_copy(self, request: web.Request) -> web.Response:
        return self._status_changed(await self.runtime.stop_copy())

    def _status_changed(self, status: dict) -> web.Response:
        # Push immediately so every open dashboard flips state without waiting a tick.
        if self._clients:
            self._broadcast({"type": "status", "status": status})
        return _json(status)

    async def list_targets(self, request: web.Request) -> web.Response:
        return _json(self.runtime.targets())

    async def create_target(self, request: web.Request) -> web.Response:
        return _json(self.runtime.create_target(await self._body(request)), status=201)

    async def update_target(self, request: web.Request) -> web.Response:
        data = await self._body(request)
        data.pop("id", None)
        data.pop("stats", None)
        return _json(self.runtime.update_target(request.match_info["id"], data))

    async def patch_target(self, request: web.Request) -> web.Response:
        data = await self._body(request)
        if set(data) != {"enabled"}:
            raise TargetError("PATCH only supports {enabled}")
        return _json(self.runtime.set_target_enabled(request.match_info["id"], data["enabled"]))

    async def delete_target(self, request: web.Request) -> web.Response:
        self.runtime.delete_target(request.match_info["id"])
        return web.Response(status=204)

    async def get_settings(self, request: web.Request) -> web.Response:
        return _json(self.runtime.get_settings())

    async def update_settings(self, request: web.Request) -> web.Response:
        values = (await self._body(request)).get("values")
        if not isinstance(values, dict):
            raise TargetError("body must be {values: {setting: value}}")
        return _json(self.runtime.update_settings(values))

    async def positions(self, request: web.Request) -> web.Response:
        q = request.query
        return _json(self.runtime.positions(q.get("venue") or None, q.get("target_id") or None))

    async def orders(self, request: web.Request) -> web.Response:
        return _json(self.runtime.orders())

    async def activity(self, request: web.Request) -> web.Response:
        q = request.query
        limit = max(1, min(self._int_param(request, "limit", 100), ACTIVITY_PAGE_MAX))
        items = await self.runtime.history.query(
            limit=limit,
            before_id=self._int_param(request, "before_id"),
            target_id=q.get("target_id") or None,
            venue=q.get("venue") or None,
            kind=q.get("kind") or None,
        )
        next_before = items[-1]["id"] if len(items) == limit else None
        return _json({"items": items, "next_before_id": next_before})

    async def not_found(self, request: web.Request) -> web.Response:
        return _error(404, "not found")

    async def spa(self, request: web.Request) -> web.StreamResponse:
        index = STATIC_DIR / "index.html"
        if not index.exists():
            return web.Response(text=_NOT_BUILT, content_type="text/html")
        tail = request.match_info.get("tail", "")
        candidate = (STATIC_DIR / tail).resolve()
        if tail and candidate.is_file() and STATIC_DIR in candidate.parents:
            return web.FileResponse(candidate)
        return web.FileResponse(index, headers={"Cache-Control": "no-cache"})

    # ── Websocket ──

    async def ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=25)
        await ws.prepare(request)
        queue: asyncio.Queue = asyncio.Queue(maxsize=WS_QUEUE_MAX)
        self._clients[ws] = queue
        writer = asyncio.create_task(self._ws_writer(ws, queue))
        await queue.put(orjson.dumps({"type": "status", "status": self.runtime.status()}).decode())
        try:
            async for msg in ws:
                if msg.type == WSMsgType.ERROR:
                    break
        finally:
            self._clients.pop(ws, None)
            writer.cancel()
        return ws

    @staticmethod
    async def _ws_writer(ws: web.WebSocketResponse, queue: asyncio.Queue) -> None:
        try:
            while True:
                await ws.send_str(await queue.get())
        except (ConnectionResetError, RuntimeError, asyncio.CancelledError):
            pass

    def _on_activity(self, activity: Activity) -> None:
        if self._clients:
            self._broadcast({"type": "activity", "item": activity.to_dict()})

    def _broadcast(self, message: dict) -> None:
        text = orjson.dumps(message).decode()
        for ws, queue in list(self._clients.items()):
            try:
                queue.put_nowait(text)
            except asyncio.QueueFull:
                # Slow client — drop it; the UI reconnects and refetches.
                self._clients.pop(ws, None)
                asyncio.create_task(ws.close())
