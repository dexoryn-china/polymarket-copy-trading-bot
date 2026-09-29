"""Dashboard HTTP API + websocket against DashboardServer.app (no live network)."""

from __future__ import annotations

import asyncio
import json

import aiohttp
from aiohttp.test_utils import TestClient, TestServer

from app import events
from app.session import VenuePipeline
from app.targets import VENUE_PREDICTIONS
from app.web.server import DashboardServer
from tests.fakes import WALLET_A, make_runtime, make_settings_store


def _server(tmp_path, token="", settings=None):
    runtime, pred_engine, perps_engine = make_runtime(tmp_path, settings=settings)
    server = DashboardServer(runtime, "127.0.0.1", 0, token=token)
    return server, runtime, pred_engine


def _client(app):
    """TestClient with ThreadedResolver — aiodns/pycares can crash on Windows."""
    connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())
    return TestClient(TestServer(app), connector=connector)


def test_api_contract(tmp_path):
    asyncio.run(_api(tmp_path))


async def _api(tmp_path):
    server, runtime, pred_engine = _server(tmp_path)
    async with _client(server.app) as client:
        meta = await (await client.get("/api/meta")).json()
        assert meta["name"] == "Polymarket Copy Bot"
        assert meta["mode"] == "dry_run"
        assert "version" in meta
        assert {v["id"] for v in meta["venues"]} == {"predictions", "perps"}
        pred = next(v for v in meta["venues"] if v["id"] == "predictions")
        for key in ("label", "wallet_label", "wallet_placeholder",
                    "close_label", "sizing_fields"):
            assert key in pred
        assert "enabled" not in pred
        assert pred["label"] == "Prediction markets"
        assert pred["sizing_fields"]

        st = await (await client.get("/api/status")).json()
        for key in ("mode", "copy", "paused", "started_at_ms", "uptime_s", "feeds",
                    "venues", "counts", "latency"):
            assert key in st
        assert st["paused"] is False
        assert st["feeds"] == []
        assert st["copy"]["venue"] == "predictions"
        assert st["copy"]["state"] == "stopped"
        assert st["copy"]["running"] is False
        pred_v = next(v for v in st["venues"] if v["id"] == "predictions")
        perp_v = next(v for v in st["venues"] if v["id"] == "perps")
        assert pred_v["active"] is True
        assert perp_v["active"] is False
        assert "enabled" not in pred_v

        paused = await (await client.post("/api/pause", json={"paused": True})).json()
        assert paused["paused"] is True
        bad = await client.post("/api/pause", json={"paused": "yes"})
        assert bad.status == 400
        assert "error" in await bad.json()

        created = await client.post("/api/targets", json={
            "name": "whale",
            "venue": VENUE_PREDICTIONS,
            "wallet": WALLET_A,
            "sizing": {"fixed_usd_per_fill": 11},
        })
        assert created.status == 201
        body = await created.json()
        tid = body["id"]
        assert body["sizing"]["fixed_usd_per_fill"] == 11.0
        assert "stats" in body

        invalid = await client.post("/api/targets", json={"venue": "nope", "wallet": WALLET_A})
        assert invalid.status == 400
        assert "error" in await invalid.json()

        upd = await client.put(f"/api/targets/{tid}", json={"name": "whale-2", "sizing": {"max_open_usd": 70}})
        assert upd.status == 200
        updated = await upd.json()
        assert updated["name"] == "whale-2"
        assert updated["sizing"]["max_open_usd"] == 70.0
        assert updated["sizing"]["fixed_usd_per_fill"] == 11.0

        patched = await client.patch(f"/api/targets/{tid}", json={"enabled": False})
        assert patched.status == 200
        assert (await patched.json())["enabled"] is False
        extra = await client.patch(f"/api/targets/{tid}", json={"enabled": True, "name": "x"})
        assert extra.status == 400

        listed = await (await client.get("/api/targets")).json()
        assert any(t["id"] == tid for t in listed)

        pred_engine.add_position(
            id="p1", venue="predictions", target_id=tid, opened_at_ms=2, label="m",
        )
        positions = await (await client.get("/api/positions")).json()
        assert positions and positions[0]["id"] == "p1"
        filtered = await (await client.get(f"/api/positions?venue=predictions&target_id={tid}")).json()
        assert len(filtered) == 1
        empty = await (await client.get("/api/positions?venue=perps")).json()
        assert empty == []

        orders = await (await client.get("/api/orders")).json()
        assert orders == []

        runtime.bus.emit(events.COPY_SUCCESS, "copied one", venue="predictions", target=runtime.store.get(tid))
        runtime.bus.emit(events.TARGET_FILL, "fill", venue="predictions")
        act = await (await client.get("/api/activity?limit=1")).json()
        assert "items" in act and "next_before_id" in act
        assert len(act["items"]) == 1
        page = await (await client.get(f"/api/activity?limit=1&before_id={act['items'][0]['id']}")).json()
        assert page["items"][0]["id"] < act["items"][0]["id"]

        gone = await client.delete("/api/targets/does-not-exist")
        assert gone.status == 404

        pred_engine.open[tid] = True
        conflict = await client.delete(f"/api/targets/{tid}")
        assert conflict.status == 409
        pred_engine.open[tid] = False
        deleted = await client.delete(f"/api/targets/{tid}")
        assert deleted.status == 204

        unknown = await client.get("/api/x")
        assert unknown.status == 404
        assert "error" in await unknown.json()

        html = await client.get("/")
        assert html.status == 200
        assert "html" in html.headers.get("Content-Type", "").lower()

    runtime.history.close()


def test_token_auth(tmp_path):
    asyncio.run(_auth(tmp_path))


async def _auth(tmp_path):
    server, runtime, _ = _server(tmp_path, token="s3cret")
    async with _client(server.app) as client:
        naked = await client.get("/api/meta")
        assert naked.status == 401
        header = await client.get("/api/meta", headers={"Authorization": "Bearer s3cret"})
        assert header.status == 200
        query = await client.get("/api/meta?token=s3cret")
        assert query.status == 200
        wrong = await client.get("/api/meta", headers={"Authorization": "Bearer nope"})
        assert wrong.status == 401
    runtime.history.close()


def test_websocket_status_then_activity(tmp_path):
    asyncio.run(_ws(tmp_path))


async def _ws(tmp_path):
    server, runtime, _ = _server(tmp_path)
    runtime.bus.subscribe(server._on_activity)
    async with _client(server.app) as client:
        ws = await client.ws_connect("/api/ws")
        first = json.loads(await ws.receive_str())
        assert first["type"] == "status"
        assert "paused" in first["status"]
        runtime.bus.emit(events.COPY_SUCCESS, "ws-copy")
        second = json.loads(await asyncio.wait_for(ws.receive_str(), timeout=1.0))
        assert second["type"] == "activity"
        assert second["item"]["summary"] == "ws-copy"
        await ws.close()
    runtime.history.close()


def test_spa_fallback_when_index_missing(tmp_path, monkeypatch):
    asyncio.run(_fallback(tmp_path, monkeypatch))


async def _fallback(tmp_path, monkeypatch):
    import app.web.server as server_mod
    empty = tmp_path / "nostatic"
    empty.mkdir()
    monkeypatch.setattr(server_mod, "STATIC_DIR", empty)
    server, runtime, _ = _server(tmp_path)
    async with _client(server.app) as client:
        resp = await client.get("/")
        text = await resp.text()
        assert resp.status == 200
        assert "Dashboard not built" in text
        assert "text/html" in resp.headers.get("Content-Type", "")
    runtime.history.close()


def test_settings_api(tmp_path):
    asyncio.run(_settings_api(tmp_path))


async def _settings_api(tmp_path):
    settings = make_settings_store(tmp_path)
    server, runtime, _ = _server(tmp_path, settings=settings)
    async with _client(server.app) as client:
        got = await (await client.get("/api/settings")).json()
        assert got["sections"]
        assert set(got) == {"sections", "values"}
        assert "telegram.bot_token" in got["values"]

        updated = await client.put("/api/settings", json={
            "values": {"perps.poll_interval_s": 2.5},
        })
        assert updated.status == 200
        body = await updated.json()
        assert body["values"]["perps.poll_interval_s"] == 2.5

        act = await (await client.get("/api/activity")).json()
        settings_items = [i for i in act["items"] if i.get("data", {}).get("event") == "settings"]
        assert len(settings_items) == 1
        assert settings_items[0]["kind"] == events.SYSTEM
        assert "Settings updated:" in settings_items[0]["summary"]
        assert "Poll interval" in settings_items[0]["summary"]

        bad = await client.put("/api/settings", json={"values": {"execution.order_type": "market"}})
        assert bad.status == 400
        assert "error" in await bad.json()

        missing = await client.put("/api/settings", json={})
        assert missing.status == 400
        assert "error" in await missing.json()

        not_dict = await client.put("/api/settings", json={"values": ["nope"]})
        assert not_dict.status == 400
    runtime.history.close()


def test_settings_token_auth(tmp_path):
    asyncio.run(_settings_auth(tmp_path))


async def _settings_auth(tmp_path):
    settings = make_settings_store(tmp_path)
    server, runtime, _ = _server(tmp_path, token="s3cret", settings=settings)
    async with _client(server.app) as client:
        naked = await client.get("/api/settings")
        assert naked.status == 401
        ok = await client.get("/api/settings", headers={"Authorization": "Bearer s3cret"})
        assert ok.status == 200
        put = await client.put(
            "/api/settings",
            json={"values": {"perps.poll_interval_s": 2.0}},
        )
        assert put.status == 401
        put_ok = await client.put(
            "/api/settings",
            json={"values": {"perps.poll_interval_s": 2.0}},
            headers={"Authorization": "Bearer s3cret"},
        )
        assert put_ok.status == 200
    runtime.history.close()


def test_copy_api(tmp_path):
    asyncio.run(_copy_api(tmp_path))


async def _copy_api(tmp_path):
    server, runtime, _ = _server(tmp_path)
    try:
        async with _client(server.app) as client:
            st = await (await client.get("/api/status")).json()
            assert st["copy"]["state"] == "stopped"
            assert st["feeds"] == []
            assert next(v for v in st["venues"] if v["id"] == "predictions")["active"] is True
            assert next(v for v in st["venues"] if v["id"] == "perps")["active"] is False

            ws = await client.ws_connect("/api/ws")
            hello = json.loads(await ws.receive_str())
            assert hello["type"] == "status"

            started = await client.post("/api/copy/start", json={})
            assert started.status == 200
            body = await started.json()
            assert body["copy"]["state"] == "running"
            assert body["copy"]["running"] is True
            assert body["copy"]["venue"] == "predictions"
            assert body["feeds"]
            assert body["feeds"][0]["id"] == "predictions-ws"
            assert next(v for v in body["venues"] if v["id"] == "predictions")["active"] is True

            pushed = json.loads(await asyncio.wait_for(ws.receive_str(), timeout=1.0))
            assert pushed["type"] == "status"
            assert pushed["status"]["copy"]["state"] == "running"

            conflict = await client.post("/api/copy/start", json={})
            assert conflict.status == 409
            assert "error" in await conflict.json()

            switch = await client.put("/api/copy", json={"venue": "perps"})
            assert switch.status == 409

            same = await client.put("/api/copy", json={"venue": "predictions"})
            assert same.status == 200

            stopped = await client.post("/api/copy/stop")
            assert stopped.status == 200
            stopped_body = await stopped.json()
            assert stopped_body["copy"]["state"] == "stopped"
            assert stopped_body["copy"]["running"] is False
            assert stopped_body["feeds"] == []
            assert next(v for v in stopped_body["venues"] if v["id"] == "predictions")["active"] is True

            selected = await client.put("/api/copy", json={"venue": "perps"})
            assert selected.status == 200
            sel = await selected.json()
            assert sel["copy"]["venue"] == "perps"
            assert sel["copy"]["state"] == "stopped"
            assert next(v for v in sel["venues"] if v["id"] == "perps")["active"] is True
            assert next(v for v in sel["venues"] if v["id"] == "predictions")["active"] is False
            assert sel["feeds"] == []

            started_perps = await client.post("/api/copy/start", json={"venue": "perps"})
            assert started_perps.status == 200
            assert (await started_perps.json())["copy"]["venue"] == "perps"
            await client.post("/api/copy/stop")

            bad_type = await client.put("/api/copy", json={"venue": 1})
            assert bad_type.status == 400
            missing = await client.put("/api/copy", json={})
            assert missing.status == 400
            unknown = await client.put("/api/copy", json={"venue": "spot"})
            assert unknown.status == 400
            assert "venue" in (await unknown.json())["error"]

            bad_start = await client.post("/api/copy/start", json={"venue": 1})
            assert bad_start.status == 400
            unknown_start = await client.post("/api/copy/start", json={"venue": "spot"})
            assert unknown_start.status == 400

            await ws.close()
    finally:
        if runtime.session.running:
            await runtime.stop_copy()
        runtime.history.close()


def test_copy_start_prepare_failure(tmp_path):
    asyncio.run(_copy_prepare_fail(tmp_path))


async def _copy_prepare_fail(tmp_path):
    async def boom():
        raise RuntimeError("no session")

    server, runtime, _ = _server(tmp_path)
    pipe = runtime.session.pipelines[VENUE_PREDICTIONS]
    runtime.session.pipelines[VENUE_PREDICTIONS] = VenuePipeline(
        pipe.label, pipe.jobs, prepare=boom, drain=pipe.drain,
    )
    async with _client(server.app) as client:
        resp = await client.post("/api/copy/start", json={})
        assert resp.status == 400
        body = await resp.json()
        assert "error" in body
        assert "no session" in body["error"]
        st = await (await client.get("/api/status")).json()
        assert st["copy"]["state"] == "stopped"
    runtime.history.close()


def test_copy_token_auth(tmp_path):
    asyncio.run(_copy_auth(tmp_path))


async def _copy_auth(tmp_path):
    server, runtime, _ = _server(tmp_path, token="s3cret")
    headers = {"Authorization": "Bearer s3cret"}
    async with _client(server.app) as client:
        assert (await client.put("/api/copy", json={"venue": "perps"})).status == 401
        assert (await client.post("/api/copy/start", json={})).status == 401
        assert (await client.post("/api/copy/stop")).status == 401
        ok = await client.put("/api/copy", json={"venue": "perps"}, headers=headers)
        assert ok.status == 200
        assert (await ok.json())["copy"]["venue"] == "perps"
        started = await client.post("/api/copy/start", json={}, headers=headers)
        assert started.status == 200
        stopped = await client.post("/api/copy/stop", headers=headers)
        assert stopped.status == 200
    runtime.history.close()
