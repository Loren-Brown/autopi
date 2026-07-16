"""
Generic OBD-II (SAE J1979) Mode 01 terminal poller.

Opens a CAN interface (native SocketCAN or socketcand), broadcasts
standard PID requests on ``0x7DF``, accepts responses on ``0x7E8``, and
redraws decoded values in place in the terminal at ~1 Hz.

This path does **not** speak Subaru SSM. For high-rate or Subaru-only
channels, use ``ssm-collector`` instead.

Entry
-----
::

    uv run src/main.py --obd

Environment
-----------
``CAN_MODE``
    ``native`` (default) or ``socketcand``.
``SOCKETCAND_HOST`` / ``SOCKETCAND_PORT``
    Used when ``CAN_MODE=socketcand`` (defaults ``localhost`` / ``29536``).
"""

from __future__ import annotations

import os
import signal
import time

import can
from dotenv import load_dotenv

load_dotenv()

OBD_REQUEST_ID = 0x7DF
OBD_RESPONSE_ID = 0x7E8
RESPONSE_TIMEOUT = 1.0
POLL_INTERVAL = 1.0

PIDS = {
    "RPM": 0x0C,
    "SPEED": 0x0D,
    "COOLANT_TEMP": 0x05,
    "THROTTLE_POS": 0x11,
    "MAF": 0x10,
    "O2_VOLTAGE": 0x14,
}

# ANSI helpers
CLEAR_LINE = "\033[K"
CURSOR_UP = "\033[{}A"
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"


def create_bus() -> can.BusABC:
    """
    Open a python-can bus for OBD traffic on ``can0``.

    Returns:
        A live ``can.BusABC`` instance. Caller must call ``shutdown()``.

    Environment:
        Honors ``CAN_MODE``, ``SOCKETCAND_HOST``, and ``SOCKETCAND_PORT``.
    """
    mode = os.getenv("CAN_MODE", "native")
    if mode == "socketcand":
        host = os.getenv("SOCKETCAND_HOST", "localhost")
        port = int(os.getenv("SOCKETCAND_PORT", "29536"))
        print(f"CAN mode: socketcand → {host}:{port}/can0")
        return can.Bus(interface="socketcand", host=host, port=port, channel="can0")
    print("CAN mode: native → can0")
    return can.Bus(interface="socketcan", channel="can0", bitrate=500000)


def parse_response(pid: int, payload: bytes) -> str:
    """
    Decode a Mode 01 PID payload into a fixed-width display string.

    Args:
        pid: Requested PID (e.g. ``0x0C`` for RPM).
        payload: Data bytes following the ``0x41 <pid>`` response header.

    Returns:
        Human-readable value with units, or a hex dump for unknown PIDs.
    """
    if pid == 0x0C:
        return f"{(payload[0] * 256 + payload[1]) / 4:>8.1f} RPM"
    if pid == 0x0D:
        return f"{payload[0]:>8d} km/h"
    if pid == 0x05:
        return f"{payload[0] - 40:>8d} °C"
    if pid == 0x11:
        return f"{payload[0] * 100 / 255:>8.1f} %"
    if pid == 0x10:
        return f"{(payload[0] * 256 + payload[1]) / 100:>8.2f} g/s"
    if pid == 0x14:
        return f"{payload[0] * 0.005:>8.3f} V"
    return f"  raw: {payload.hex()}"


def query_pid(bus: can.BusABC, name: str, pid: int) -> str:
    """
    Send one Mode 01 request and wait for a matching response.

    Args:
        bus: Open CAN bus.
        name: Display label (unused by the request; kept for call-site clarity).
        pid: Mode 01 PID to query.

    Returns:
        Decoded value string from :func:`parse_response`, or
        ``\"no response\"`` if nothing matching arrives before
        ``RESPONSE_TIMEOUT``.
    """
    request = can.Message(
        arbitration_id=OBD_REQUEST_ID,
        data=[0x02, 0x01, pid, 0xCC, 0xCC, 0xCC, 0xCC, 0xCC],
        is_extended_id=False,
    )
    bus.send(request)

    deadline = time.monotonic() + RESPONSE_TIMEOUT
    while time.monotonic() < deadline:
        msg = bus.recv(timeout=deadline - time.monotonic())
        if msg is None:
            break
        if msg.arbitration_id == OBD_RESPONSE_ID:
            d = msg.data
            if len(d) >= 4 and d[1] == 0x41 and d[2] == pid:
                return parse_response(pid, d[3:])

    return "     no response"


def poll_once(bus: can.BusABC) -> dict[str, str]:
    """
    Query every PID in :data:`PIDS` once.

    Args:
        bus: Open CAN bus.

    Returns:
        Mapping of PID display name → formatted value string.
    """
    return {name: query_pid(bus, name, pid) for name, pid in PIDS.items()}


def render(results: dict[str, str], first: bool) -> None:
    """
    Draw (or redraw in place) the terminal results table.

    Args:
        results: Mapping from :func:`poll_once`.
        first: If False, move the cursor up so the next frame overwrites
            the previous table instead of scrolling.
    """
    if not first:
        print(CURSOR_UP.format(len(results) + 1), end="")
    print(f"  {'─' * 28}")
    for name, value in results.items():
        print(f"  {name:<14}{value}{CLEAR_LINE}")


def main() -> None:
    """
    Run the OBD-II poll loop until SIGINT/SIGTERM.

    Hides the cursor while running, restores it on exit, and always shuts
    down the CAN bus in ``finally``.
    """
    bus = create_bus()
    print(HIDE_CURSOR)

    running = True

    def handle_exit(sig: int, frame: object) -> None:
        """Signal handler: request a clean exit from the poll loop."""
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    try:
        first = True
        print("\nPolling OBD-II  (Ctrl-C to quit)\n")
        while running:
            loop_start = time.monotonic()
            results = poll_once(bus)
            render(results, first)
            first = False
            elapsed = time.monotonic() - loop_start
            remaining = POLL_INTERVAL - elapsed
            if remaining > 0:
                time.sleep(remaining)
    finally:
        print(SHOW_CURSOR)
        print("\nStopped.")
        bus.shutdown()


if __name__ == "__main__":
    main()
