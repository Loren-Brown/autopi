"""
SSM telemetry collector — no UI.

Polls the ECU over CAN and streams snapshots/updates on a WebSocket.
Other processes (web dashboard, loggers, etc.) connect as clients.
"""

from __future__ import annotations

import asyncio
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
from ssm_runtime import create_bus, load_params, resolve_ecu_id

POLL_INTERVAL = 0.020       # 50 Hz SSM poll
BROADCAST_INTERVAL = 0.050  # 20 Hz client push
HISTORY_SECONDS = 90.0
HISTORY_HZ = 20.0
HISTORY_MAXLEN = int(HISTORY_SECONDS * HISTORY_HZ)

# (param_id, preferred_units, ui_key, label, gauge_min, gauge_max)
DASHBOARD_SPECS: list[tuple[str, str, str, str, float, float]] = [
    ("P2",  "C",          "coolant", "Coolant Temp", -20.0, 120.0),
    ("P11", "C",          "iat",     "Intake Temp",  -20.0,  80.0),
    ("E31", "multiplier", "dam",     "DAM",            0.0,   1.0),
    ("E41", "degrees",    "flkc",    "Fine Knock",    -5.0,   5.0),
]


@dataclass
class ParamMeta:
    id: str
    key: str
    label: str
    name: str
    units: str
    min: float
    max: float


class TelemetryStore:
    """Thread-safe latest values + rolling history for WebSocket clients."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.meta: dict[str, ParamMeta] = {}
        self.values: dict[str, float] = {}
        self.history: dict[str, deque[tuple[float, float]]] = {}
        self.ecu_id: str | None = None
        self.error: str | None = None
        self.running = False
        self._last_history_t = 0.0

    def configure(
        self,
        params: list[SsmParam],
        specs: list[tuple[str, str, str, str, float, float]],
    ) -> None:
        spec_by_id = {s[0]: s for s in specs}
        with self._lock:
            self.meta.clear()
            self.values.clear()
            self.history.clear()
            for p in params:
                pid, _units, key, label, gmin, gmax = spec_by_id[p.id]
                self.meta[pid] = ParamMeta(
                    id=pid,
                    key=key,
                    label=label,
                    name=p.name,
                    units=p.units,
                    min=gmin,
                    max=gmax,
                )
                self.values[pid] = float("nan")
                self.history[pid] = deque(maxlen=HISTORY_MAXLEN)

    def update(self, results: dict[str, float], now: float) -> None:
        with self._lock:
            self.values.update(results)
            if now - self._last_history_t >= (1.0 / HISTORY_HZ):
                self._last_history_t = now
                for pid, val in results.items():
                    if pid in self.history and val == val:  # skip NaN
                        self.history[pid].append((now, val))

    def snapshot(self) -> dict[str, Any]:
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
                    pid: [[t, v] for t, v in series]
                    for pid, series in self.history.items()
                },
            }

    def update_message(self) -> dict[str, Any]:
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
    bus = None
    try:
        bus = create_bus()
        client = SSMClient(bus)
        print("Connecting to ECU via SSM...")
        detected = client.init()
        print(f"ECU ID: {detected}")
        ecu_id = resolve_ecu_id(detected)
        store.ecu_id = ecu_id

        param_specs = [(pid, units) for pid, units, *_ in DASHBOARD_SPECS]
        params = load_params(ecu_id, param_specs)
        if not params:
            store.error = "No params loaded — check SSM_ECU_ID and ssm_configs.json"
            print(store.error)
            return

        store.configure(params, DASHBOARD_SPECS)
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
    return {
        "ok": True,
        "running": store.running,
        "ecu_id": store.ecu_id,
        "error": store.error,
        "clients": len(_clients),
    }


@app.get("/snapshot")
async def snapshot() -> dict[str, Any]:
    return store.snapshot()


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
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
    host = os.getenv("COLLECTOR_HOST", "0.0.0.0")
    port = int(os.getenv("COLLECTOR_PORT", "8090"))
    print(f"SSM collector → ws://{host}:{port}/ws")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
