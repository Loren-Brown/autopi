#!/usr/bin/env python3
"""
Generate a channels.json template from the RomRaider logger XML.

Every standard + ECU-specific parameter and RomRaider switch is included with
``\"enabled\": false``. Human-readable fields live under ``info`` (ignored at
runtime). The collector only reads ``id`` and ``enabled``.

Usage
-----
::

    uv run src/ssm-collector/generate_channels_json.py
    uv run src/ssm-collector/generate_channels_json.py --ecu 5C42504007 \\
        --out src/ssm-collector/configs/channels.generated.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from raider_reader import (
    format_romraider_xml_path,
    load_logger_map,
    resolve_romraider_xml,
)

load_dotenv()

_COLLECTOR_DIR = Path(__file__).resolve().parent
DEFAULT_OUT = _COLLECTOR_DIR / "configs" / "channels.generated.json"


def _slug_key(param_id: str, name: str) -> str:
    """Build a short UI key from param id (preferred) or name."""
    raw = param_id.strip() or name
    key = re.sub(r"[^A-Za-z0-9]+", "_", raw).strip("_").lower()
    return key or "channel"


def _channel_from_param(param: dict[str, Any]) -> dict[str, Any]:
    """Map one RomRaider param or switch dict to a channels.json entry (disabled)."""
    pid = str(param.get("id") or "")
    name = str(param.get("name") or pid)

    if param.get("type") == "switch" or param.get("bit") is not None:
        return {
            "id": pid,
            "enabled": False,
            "info": {
                "units": "bool",
                "key": _slug_key(pid, name),
                "label": name,
                "min": 0.0,
                "max": 1.0,
            },
        }

    convs = param.get("conversions") or []
    conv = convs[0] if convs else {}
    units = str(conv.get("units") or "")
    default_min, default_max = (0.0, 1.0) if units == "multiplier" else (0.0, 100.0)
    try:
        gmin = float(conv["gauge_min"]) if conv.get("gauge_min") is not None else default_min
    except (TypeError, ValueError):
        gmin = default_min
    try:
        gmax = float(conv["gauge_max"]) if conv.get("gauge_max") is not None else default_max
    except (TypeError, ValueError):
        gmax = default_max
    if gmax == gmin:
        gmax = gmin + 1.0

    return {
        "id": pid,
        "enabled": False,
        "info": {
            "units": units,
            "key": _slug_key(pid, name),
            "label": name,
            "min": gmin,
            "max": gmax,
        },
    }


def build_channels(ecu_id: str, xml_path: Path | None = None) -> list[dict[str, Any]]:
    """
    Build disabled channel entries for standard params, switches, and ECU extended.

    Args:
        ecu_id: Hex ECU ID for extended-parameter selection.
        xml_path: Optional logger XML; defaults to :func:`resolve_romraider_xml`.

    Returns:
        Channel dicts suitable for ``channels.json``.
    """
    data = load_logger_map(xml_path)
    standard = data.get("__standard__", [])
    extended = data.get("ecus", {}).get(ecu_id, {}).get("extended_params", [])
    if ecu_id not in data.get("ecus", {}) and not extended:
        print(f"Warning: ECU {ecu_id} has no extended params in this XML")

    seen: set[str] = set()
    channels: list[dict[str, Any]] = []
    for param in standard + extended:
        pid = param.get("id")
        if not pid or pid in seen:
            continue
        seen.add(pid)
        channels.append(_channel_from_param(param))
    return channels


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--xml",
        type=Path,
        default=None,
        help="RomRaider logger XML (default: ROMRAIDER_XML from .env)",
    )
    p.add_argument(
        "--ecu",
        default=os.getenv("SSM_ECU_ID", "5C42504007"),
        help="ECU id for extended params (default: SSM_ECU_ID or 5C42504007)",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"Output path (default: {DEFAULT_OUT})",
    )
    return p.parse_args()


def main() -> None:
    """CLI: write a full disabled channels.json from the logger XML."""
    args = _parse_args()
    xml_path = args.xml
    if xml_path is not None and not xml_path.is_absolute():
        xml_path = (Path(__file__).resolve().parents[2] / xml_path).resolve()
    if xml_path is None:
        xml_path = resolve_romraider_xml()

    print(f"Reading {format_romraider_xml_path(xml_path)}")
    print(f"ECU {args.ecu}")
    channels = build_channels(args.ecu, xml_path)
    out = {"channels": channels}

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2) + "\n")
    print(f"Wrote {len(channels)} channels (all enabled=false) → {args.out}")


if __name__ == "__main__":
    main()
