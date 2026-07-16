"""
Live SSM data display for Subaru EJ257 (2011 STI).

Connects to the ECU via SSM over CAN, reads the ECU ID to select the
correct address map, then polls a curated set of parameters at ~50 Hz
(every 20 ms) and displays them with in-place updates.
"""

import signal
import time

from ssm_client import SSMClient
from ssm_runtime import create_bus, load_params, resolve_ecu_id

POLL_INTERVAL = 0.020  # 20 ms → ~50 Hz
DISPLAY_INTERVAL = 0.100  # refresh terminal at 10 Hz to avoid flicker

# ── Parameters to display — (param_id, preferred_units) ──────────────────────
DISPLAY_PARAMS = [
    ("P8",  "rpm"),       # Engine Speed
    ("P9",  "mph"),       # Vehicle Speed
    ("P2",  "C"),         # Coolant Temperature
    ("P12", "g/s"),       # Mass Airflow
    ("P13", "%"),         # Throttle Opening Angle
    ("P25", "psi"),       # Manifold Relative Pressure (boost)
    ("P36", "%"),         # Primary Wastegate Duty Cycle
    ("P23", "degrees"),   # Knock Correction Advance
    ("P10", "degrees"),   # Ignition Total Timing
    ("E31", "multiplier"),# IAM*
    ("E39", "degrees"),   # Feedback Knock Correction (4-byte)*
    ("E41", "degrees"),   # Fine Learning Knock Correction (4-byte)*
]

# ANSI helpers
CLEAR_LINE  = "\033[K"
CURSOR_UP   = "\033[{}A"
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"


def fmt_value(val: float, units: str) -> str:
    if val != val:  # NaN
        return f"{'---':>8}"
    if units in ("rpm",):
        return f"{val:>8.0f}"
    if units in ("multiplier",):
        return f"{val:>8.4f}"
    return f"{val:>8.2f}"


def render(params, results: dict[str, float], first: bool) -> None:
    if not first:
        print(CURSOR_UP.format(len(params) + 2), end="")
    print(f"  {'─' * 42}{CLEAR_LINE}")
    for p in params:
        val   = results.get(p.id, float("nan"))
        units = p.units
        print(f"  {p.name:<32}{fmt_value(val, units):>8} {units}{CLEAR_LINE}")
    print(f"  {'─' * 42}{CLEAR_LINE}")


def main() -> None:
    bus = create_bus()
    client = SSMClient(bus)

    print("\nConnecting to ECU via SSM...")
    try:
        ecu_id = client.init()
    except RuntimeError as e:
        print(f"SSM init failed: {e}")
        bus.shutdown()
        return

    print(f"ECU ID: {ecu_id}")
    ecu_id = resolve_ecu_id(ecu_id)

    params = load_params(ecu_id, DISPLAY_PARAMS)
    if not params:
        print("No params loaded — check SSM_ECU_ID and ssm_configs.json")
        bus.shutdown()
        return

    print(f"Loaded {len(params)} params for ECU {ecu_id}")
    print(HIDE_CURSOR)

    running = True

    def handle_exit(sig, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    print(f"\nPolling SSM at {1000*POLL_INTERVAL:.0f} ms  (Ctrl-C to quit)\n")
    first         = True
    last_results: dict[str, float] = {}
    last_display  = 0.0

    try:
        while running:
            loop_start = time.monotonic()

            last_results = client.batch_read(params)

            # Render at display rate to avoid terminal flicker at 50 Hz
            now = time.monotonic()
            if now - last_display >= DISPLAY_INTERVAL:
                render(params, last_results, first)
                first        = False
                last_display = now

            elapsed   = time.monotonic() - loop_start
            remaining = POLL_INTERVAL - elapsed
            if remaining > 0:
                time.sleep(remaining)
    finally:
        print(SHOW_CURSOR)
        print("\nStopped.")
        bus.shutdown()


if __name__ == "__main__":
    main()
