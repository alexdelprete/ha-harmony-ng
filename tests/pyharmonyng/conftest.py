"""A fake Hub serving the recorded fixtures over HTTP and WebSocket."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Mapping
import json
from pathlib import Path
from typing import Any

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer
import pytest

from custom_components.harmony_ng.pyharmonyng import HarmonyNgClient

FIXTURES = Path(__file__).parent / "fixtures"


def load_json(name: str) -> dict[str, Any]:
    """Return a JSON fixture."""
    return json.loads((FIXTURES / f"{name}.json").read_text())


def load_frames(name: str) -> list[dict[str, Any]]:
    """Return the frames of an NDJSON fixture, one object per line."""
    return [json.loads(line) for line in (FIXTURES / f"{name}.ndjson").read_text().splitlines()]


class FakeHub:
    """An aiohttp application that behaves like a Hub running firmware milestone 1."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, str, Any]] = []
        self.responses: dict[str, tuple[int, Any]] = {}
        self.delay: float = 0
        self.required_token: str | None = None
        self.snapshot: dict[str, Any] = load_json("snapshot")
        self.first_frame: dict[str, Any] | None = None
        self.close_before_snapshot = False
        self.silent_connect = False
        self.ws_status: int | None = None
        self.frames_on_connect: list[dict[str, Any]] = []
        self.ack_error: str | None = None
        self.ack_fields: dict[str, Any] = {}
        self.silent_acks = False
        self.actions: list[dict[str, Any]] = []
        self.connections = 0
        self.clients: list[web.WebSocketResponse] = []
        self.app = web.Application()
        self.app.router.add_route("*", "/ws", self._ws)
        self.app.router.add_route("*", "/{tail:.*}", self._http)
        self.server = TestServer(self.app, host="127.0.0.1")

    @property
    def host(self) -> str:
        return self.server.host

    @property
    def port(self) -> int:
        return self.server.port

    async def start(self) -> None:
        await self.server.start_server()

    async def close(self) -> None:
        for client in list(self.clients):
            await client.close()
        await self.server.close()

    async def push(self, frame: Mapping[str, Any]) -> None:
        """Send a frame to every connected WebSocket client."""
        for client in list(self.clients):
            await client.send_json(frame)

    async def drop_clients(self) -> None:
        """Close every WebSocket from the server side."""
        for client in list(self.clients):
            await client.close()

    async def _http(self, request: web.Request) -> web.StreamResponse:
        body = await request.json() if request.can_read_body else None
        self.requests.append((request.method, request.path_qs, body))
        if self.delay:
            await asyncio.sleep(self.delay)
        if (
            self.required_token
            and request.headers.get("Authorization") != f"Bearer {self.required_token}"
        ):
            return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
        if request.path in self.responses:
            status, payload = self.responses[request.path]
            if isinstance(payload, str):
                return web.Response(status=status, text=payload)
            return web.json_response(payload, status=status)
        return web.json_response(_default_response(request.method, request.path))

    async def _ws(self, request: web.Request) -> web.StreamResponse:
        if self.ws_status is not None:
            return web.Response(status=self.ws_status, text="refused")
        if self.required_token and request.query.get("token") != self.required_token:
            return web.Response(status=401, text="unauthorized")
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.connections += 1
        self.clients.append(ws)
        try:
            if self.close_before_snapshot:
                await ws.close()
                return ws
            if self.silent_connect:
                async for _ in ws:
                    pass
                return ws
            if self.first_frame is not None:
                await ws.send_json(self.first_frame)
            else:
                await ws.send_json(self.snapshot)
            for frame in self.frames_on_connect:
                await ws.send_json(frame)
            async for message in ws:
                if message.type is not aiohttp.WSMsgType.TEXT:
                    continue
                await self._handle_action(ws, json.loads(message.data))
        finally:
            self.clients.remove(ws)
        return ws

    async def _handle_action(self, ws: web.WebSocketResponse, request: dict[str, Any]) -> None:
        self.actions.append(request)
        action = request.get("action")
        msg_id = request.get("msgId")
        if action == "get_snapshot":
            await ws.send_json({**self.snapshot, "msgId": msg_id})
        elif action == "ping":
            await ws.send_json({"type": "pong", "msgId": msg_id})
        elif not self.silent_acks:
            reply: dict[str, Any] = {"type": "ack", "action": action, "ok": self.ack_error is None}
            if msg_id is not None:
                reply["msgId"] = msg_id
            if self.ack_error is not None:
                reply["error"] = self.ack_error
            else:
                reply.update(self.ack_fields)
            await ws.send_json(reply)


def _default_response(method: str, path: str) -> Any:
    fixtures = {
        "/api/status": "status",
        "/api/inventory": "inventory",
        "/api/activities": "activities",
        "/api/activity": "activity",
        "/api/rf/status": "rf_status",
        "/api/bt-status": "bt_status",
    }
    if method == "GET" and path in fixtures:
        return load_json(fixtures[path])
    if path == "/api/activity/help":
        return load_json("help")
    if path == "/api/activity":
        return {"success": True, "state": "starting"}
    if path == "/api/rf/wake":
        return {"status": "waking", "slot": 1, "ok": True}
    return {"ok": True}


@pytest.fixture
async def hub(socket_enabled: None) -> AsyncGenerator[FakeHub]:
    """A running fake Hub, on a real loopback socket (pytest-socket blocks sockets by default)."""
    fake = FakeHub()
    await fake.start()
    try:
        yield fake
    finally:
        await fake.close()


@pytest.fixture
async def session() -> AsyncGenerator[aiohttp.ClientSession]:
    """An aiohttp session closed after the test."""
    async with aiohttp.ClientSession() as client_session:
        yield client_session


@pytest.fixture
def client(hub: FakeHub, session: aiohttp.ClientSession) -> HarmonyNgClient:
    """A client pointed at the fake Hub."""
    return HarmonyNgClient(hub.host, session, port=hub.port)
