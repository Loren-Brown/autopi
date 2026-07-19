"""
SSM telemetry collector service (no UI).

Polls the ECU over CAN via Subaru SSM and streams snapshots / updates to
WebSocket clients (dashboard, loggers, etc.). The poll loop runs on a
background thread; FastAPI/uvicorn handles HTTP and WebSocket I/O.

Entry
-----
::

    uv run src/main.py --collector

Endpoints
---------
``GET /health``
    Liveness + running/ecu/error/client count.
``GET /snapshot``
    Full state including meta and history.
``WS /ws``
    Initial snapshot, then ~20 Hz ``update`` messages.

Environment
-----------
``COLLECTOR_HOST`` / ``COLLECTOR_PORT``
    Bind address (defaults ``0.0.0.0`` / ``8090``).
Plus all ``ssm_runtime`` CAN / ``SSM_ECU_ID`` variables.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from ssm_client import SSMClient, SsmParam
from ssm_runtime import create_bus, load_enabled_channel_ids, load_params, resolve_ecu_id

POLL_INTERVAL = 0.020  # 50 Hz SSM poll
BROADCAST_INTERVAL = 0.050  # 20 Hz client push
HISTORY_SECONDS = 90.0
HISTORY_HZ = 20.0
HISTORY_MAXLEN = int(HISTORY_SECONDS * HISTORY_HZ)


@dataclass
class ParamMeta:
    """
    UI-facing metadata for one dashboard channel.

    Attributes:
        id: SSM param id (e.g. ``\"P2\"``).
        key: Short UI key (RomRaider id lowercased, e.g. ``\"p2\"``).
        label: Gauge / chart title (RomRaider param name).
        name: Full name from the address map.
        units: Engineering units string.
        min: Gauge lower bound.
        max: Gauge upper bound.
    """

    id: str
    key: str
    label: str
    name: str
    units: str
    min: float
    max: float


class TelemetryStore:
    """
    Thread-safe latest values and rolling history for WebSocket clients.

    Written by the SSM poll thread; read by asyncio broadcast / HTTP handlers.
    History is sampled at ``HISTORY_HZ`` for up to ``HISTORY_SECONDS``.
    """

    def __init__(self) -> None:
        """Allocate empty store state and the mutual-exclusion lock."""
        self._lock = threading.Lock()
        self.meta: dict[str, ParamMeta] = {}
        self.values: dict[str, float] = {}
        self.history: dict[str, deque[tuple[float, float]]] = {}
        self.ecu_id: str | None = None
        self.error: str | None = None
        self.running = False
        self._last_history_t = 0.0

    def configure(self, params: list[SsmParam]) -> None:
        """
        Reset meta/values/history for the active parameter set.

        UI metadata (key, label, units, gauge min/max) comes from each
        :class:`~ssm_client.SsmParam` / RomRaider XML conversion — not from
        ``channels.json``.

        Args:
            params: Loaded SSM parameters to expose on the WebSocket feed.
        """
        with self._lock:
            self.meta.clear()
            self.values.clear()
            self.history.clear()
            for p in params:
                self.meta[p.id] = ParamMeta(
                    id=p.id,
                    key=p.id.lower(),
                    label=p.name,
                    name=p.name,
                    units=p.units,
                    min=p.gauge_min,
                    max=p.gauge_max,
                )
                self.values[p.id] = float("nan")
                self.history[p.id] = deque(maxlen=HISTORY_MAXLEN)

    def update(self, results: dict[str, float], now: float) -> None:
        """
        Apply a poll result and optionally append history samples.

        Args:
            results: ``param_id → value`` from :meth:`SSMClient.batch_read`.
            now: Wall-clock timestamp used for history points.
        """
        with self._lock:
            self.values.update(results)
            if now - self._last_history_t >= (1.0 / HISTORY_HZ):
                self._last_history_t = now
                for pid, val in results.items():
                    if pid in self.history and val == val:  # skip NaN
                        self.history[pid].append((now, val))

    def snapshot(self) -> dict[str, Any]:
        """
        Build a full state message for new WebSocket clients / ``GET /snapshot``.

        Returns:
            JSON-serializable dict with ``type=\"snapshot\"``, meta, values,
            and history series.
        """
        with self._lock:
            return {
                "type": "snapshot",
                "t": time.time(),
                "ecu_id": self.ecu_id,
                "error": self.error,
                "running": self.running,
                "meta": {
                    pid: {
                        "id": m.id,
                        "key": m.key,
                        "label": m.label,
                        "name": m.name,
                        "units": m.units,
                        "min": m.min,
                        "max": m.max,
                    }
                    for pid, m in self.meta.items()
                },
                "values": dict(self.values),
                "history": {
                    pid: [[t, v] for t, v in series] for pid, series in self.history.items()
                },
            }

    def update_message(self) -> dict[str, Any]:
        """
        Build a lightweight incremental update for connected clients.

        Returns:
            JSON-serializable dict with ``type=\"update\"`` and current values
            (no history).
        """
        with self._lock:
            return {
                "type": "update",
                "t": time.time(),
                "ecu_id": self.ecu_id,
                "error": self.error,
                "running": self.running,
                "values": dict(self.values),
            }


store = TelemetryStore()
_clients: set[WebSocket] = set()
_clients_lock = asyncio.Lock()
_poll_thread: threading.Thread | None = None


def _poll_loop() -> None:
    """
    Background thread: SSM init, configure store, then poll until stopped.

    Sets ``store.error`` and clears ``store.running`` on failure or exit.
    Always shuts down the CAN bus in ``finally``.
    """
    bus = None
    try:
        bus = create_bus()
        client = SSMClient(bus)
        print("Connecting to ECU via SSM...")
        detected = client.init()
        print(f"ECU ID: {detected}")
        ecu_id = resolve_ecu_id(detected)
        store.ecu_id = ecu_id

        try:
            channel_ids = load_enabled_channel_ids()
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            store.error = f"Invalid channels.json: {exc}"
            print(store.error)
            return

        params = load_params(ecu_id, channel_ids)
        if not params:
            store.error = "No params loaded — check SSM_ECU_ID / ROMRAIDER_XML"
            print(store.error)
            return

        store.configure(params)
        store.running = True
        store.error = None
        print(f"Polling {len(params)} params at {1000 * POLL_INTERVAL:.0f} ms")

        while store.running:
            loop_start = time.monotonic()
            results = client.batch_read(params)
            store.update(results, time.time())
            elapsed = time.monotonic() - loop_start
            remaining = POLL_INTERVAL - elapsed
            if remaining > 0:
                time.sleep(remaining)
    except Exception as exc:
        store.error = str(exc)
        print(f"SSM poll error: {exc}")
    finally:
        store.running = False
        if bus is not None:
            bus.shutdown()


async def _broadcast_loop() -> None:
    """
    Periodically push ``update`` messages to all connected WebSocket clients.

    Dead sockets are removed after a failed send. Sleeps ``BROADCAST_INTERVAL``
    between iterations; skips work when no clients are connected.
    """
    while True:
        await asyncio.sleep(BROADCAST_INTERVAL)
        if not _clients:
            continue
        msg = store.update_message()
        dead: list[WebSocket] = []
        async with _clients_lock:
            clients = list(_clients)
        for ws in clients:
            try:
                await ws.send_json(msg)
            except Exception:
                dead.append(ws)
        if dead:
            async with _clients_lock:
                for ws in dead:
                    _clients.discard(ws)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """
    FastAPI lifespan: start poll thread + broadcast task; stop on shutdown.

    Args:
        _app: FastAPI application instance (unused).

    Yields:
        Control to the running application; cleanup runs after the yield.
    """
    global _poll_thread
    store.running = True
    _poll_thread = threading.Thread(target=_poll_loop, name="ssm-poll", daemon=True)
    _poll_thread.start()
    broadcast_task = asyncio.create_task(_broadcast_loop())
    yield
    store.running = False
    broadcast_task.cancel()
    try:
        await broadcast_task
    except asyncio.CancelledError:
        pass
    if _poll_thread is not None:
        _poll_thread.join(timeout=2.0)


app = FastAPI(title="autopi SSM collector", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, Any]:
    """
    Return process and poll-loop health for probes / ops.

    Returns:
        Dict with ``ok``, ``running``, ``ecu_id``, ``error``, and ``clients``.
    """
    return {
        "ok": True,
        "running": store.running,
        "ecu_id": store.ecu_id,
        "error": store.error,
        "clients": len(_clients),
    }


@app.get("/snapshot")
async def snapshot() -> dict[str, Any]:
    """
    Return a one-shot full telemetry snapshot (same payload as WS hello).

    Returns:
        Output of :meth:`TelemetryStore.snapshot`.
    """
    return store.snapshot()


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    """
    Accept a client, send an initial snapshot, then keep the socket open.

    Incremental ``update`` frames are pushed by :func:`_broadcast_loop`.
    Inbound text is ignored (read only to detect disconnect).

    Args:
        ws: Newly connected FastAPI WebSocket.
    """
    await ws.accept()
    async with _clients_lock:
        _clients.add(ws)
    try:
        await ws.send_json(store.snapshot())
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        async with _clients_lock:
            _clients.discard(ws)


def main() -> None:
    """
    Bind uvicorn for the collector app using ``COLLECTOR_HOST`` / ``PORT``.
    """
    host = os.getenv("COLLECTOR_HOST", "0.0.0.0")
    port = int(os.getenv("COLLECTOR_PORT", "8090"))
    print(f"SSM collector → ws://{host}:{port}/ws")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
