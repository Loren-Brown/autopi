"""
Shared SSM runtime helpers: CAN bus setup and parameter map loading.

Used by both the terminal logger (``ssm_main``) and the WebSocket collector
(``ssm_collector``). Parameter definitions are read from
``configs/ssm_configs.json`` (generated offline; not imported from
RomRaider XML at runtime).

Environment
-----------
``CAN_MODE``
    ``native`` (default SocketCAN ``can0`` @ 500 kbit/s) or ``socketcand``.
``SOCKETCAND_HOST`` / ``SOCKETCAND_PORT``
    socketcand endpoint when ``CAN_MODE=socketcand``.
``SSM_ECU_ID``
    Optional override for the address map key (hex ECU ID string).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import can
from dotenv import load_dotenv

from ssm_client import SsmParam

load_dotenv()

_COLLECTOR_DIR = Path(__file__).resolve().parent
SSM_JSON = _COLLECTOR_DIR / "configs" / "ssm_configs.json"


def create_bus() -> can.BusABC:
    """
    Open the project CAN interface for SSM traffic.

    Returns:
        A live ``can.BusABC``. Caller owns shutdown.

    Environment:
        See module docstring for ``CAN_MODE`` / socketcand variables.
    """
    mode = os.getenv("CAN_MODE", "native")
    if mode == "socketcand":
        host = os.getenv("SOCKETCAND_HOST", "localhost")
        port = int(os.getenv("SOCKETCAND_PORT", "29536"))
        print(f"CAN mode: socketcand → {host}:{port}/can0")
        return can.Bus(interface="socketcand", host=host, port=port, channel="can0")
    print("CAN mode: native → can0")
    return can.Bus(interface="socketcan", channel="can0", bitrate=500000)


def load_params(
    ecu_id: str,
    param_specs: list[tuple[str, str]],
) -> list[SsmParam]:
    """
    Build :class:`~ssm_client.SsmParam` objects from ``ssm_configs.json``.

    Looks up each id in ``__standard__`` plus that ECU's ``extended_params``.
    For each spec, prefers a conversion whose ``units`` match
    ``preferred_units``, otherwise the first conversion listed.

    Args:
        ecu_id: Hex ECU ID used as the map key (e.g. ``\"5C42504007\"``).
        param_specs: Sequence of ``(param_id, preferred_units)`` pairs.

    Returns:
        Loaded parameters (unknown ids are skipped with a warning).
    """
    data = json.loads(SSM_JSON.read_text())
    std = data["__standard__"]
    ext = data["ecus"].get(ecu_id, {}).get("extended_params", [])
    all_raw = {p["id"]: p for p in std + ext}

    params: list[SsmParam] = []
    for pid, preferred_units in param_specs:
        raw = all_raw.get(pid)
        if raw is None:
            print(f"  Warning: param {pid} not found for ECU {ecu_id}, skipping")
            continue

        convs = raw.get("conversions", [])
        conv = next(
            (c for c in convs if c.get("units") == preferred_units),
            convs[0] if convs else {},
        )
        params.append(
            SsmParam(
                id=pid,
                name=raw["name"],
                address=int(raw["address"], 16),
                length=raw["length"],
                conversions=[conv] if conv else convs,
            )
        )
    return params


def resolve_ecu_id(detected_id: str) -> str:
    """
    Choose the address-map ECU ID after SSM init.

    Args:
        detected_id: ID returned by :meth:`ssm_client.SSMClient.init`.

    Returns:
        ``SSM_ECU_ID`` from the environment when set; otherwise
        ``detected_id``. Logs when the override differs from detection.
    """
    configured = os.getenv("SSM_ECU_ID", detected_id)
    if configured != detected_id:
        print(f"Using configured ECU ID {configured} (detected: {detected_id})")
    return configured
