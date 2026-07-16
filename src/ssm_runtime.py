"""Shared SSM bus setup and parameter loading."""

from __future__ import annotations

import json
import os
from pathlib import Path

import can
from dotenv import load_dotenv

from ssm_client import SsmParam

load_dotenv()

REPO_ROOT = Path(__file__).parent.parent
SSM_JSON = REPO_ROOT / "docs/romraider/ssm_configs.json"


def create_bus() -> can.BusABC:
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
    """Load params from ssm_configs.json.

    param_specs: list of (param_id, preferred_units)
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
    configured = os.getenv("SSM_ECU_ID", detected_id)
    if configured != detected_id:
        print(f"Using configured ECU ID {configured} (detected: {detected_id})")
    return configured
