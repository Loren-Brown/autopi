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
    "RPM":          0x0C,
    "SPEED":        0x0D,
    "COOLANT_TEMP": 0x05,
    "THROTTLE_POS": 0x11,
    "MAF":          0x10,
    "O2_VOLTAGE":   0x14,
}

# ANSI helpers
CLEAR_LINE = "\033[K"
CURSOR_UP  = "\033[{}A"
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"


def create_bus() -> can.BusABC:
    mode = os.getenv("CAN_MODE", "native")
    if mode == "socketcand":
        host = os.getenv("SOCKETCAND_HOST", "localhost")
        port = int(os.getenv("SOCKETCAND_PORT", "29536"))
        print(f"CAN mode: socketcand → {host}:{port}/can0")
        return can.Bus(interface="socketcand", host=host, port=port, channel="can0")
    else:
        print("CAN mode: native → can0")
        return can.Bus(interface="socketcan", channel="can0", bitrate=500000)


def parse_response(pid: int, payload: bytes) -> str:
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
    return {name: query_pid(bus, name, pid) for name, pid in PIDS.items()}


def render(results: dict[str, str], first: bool) -> None:
    if not first:
        print(CURSOR_UP.format(len(results) + 1), end="")
    print(f"  {'─' * 28}")
    for name, value in results.items():
        print(f"  {name:<14}{value}{CLEAR_LINE}")


def main() -> None:
    bus = create_bus()
    print(HIDE_CURSOR)

    running = True

    def handle_exit(sig, frame):
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
