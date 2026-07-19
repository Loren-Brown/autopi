"""
Shared SSM runtime helpers: CAN bus setup and parameter map loading.

Used by both the terminal logger (``ssm_main``) and the WebSocket collector
(``ssm_collector``). Parameter definitions come from a RomRaider logger XML
file via :mod:`raider_reader` (``ROMRAIDER_XML``). Collector poll channels
come from ``configs/channels.json`` (``id`` + ``enabled`` only).

Environment
-----------
``CAN_MODE``
    ``native`` (default SocketCAN ``can0`` @ 500 kbit/s) or ``socketcand``.
``SOCKETCAND_HOST`` / ``SOCKETCAND_PORT``
    socketcand endpoint when ``CAN_MODE=socketcand``.
``SSM_ECU_ID``
    Optional override for the address map key (hex ECU ID string).
``ROMRAIDER_XML``
    Path to RomRaider ``logger_*.xml`` on the laptop (usually under
    ``docs/romraider/``). On the Pi, omit this — runtime finds the single
    ``*.xml`` that ``deploy.sh`` copied into ``ssm-collector/configs/``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import can
from dotenv import load_dotenv
from raider_reader import (
    format_romraider_xml_path,
    load_params_from_xml,
    resolve_romraider_xml,
)

from ssm_client import SsmParam

load_dotenv()

_COLLECTOR_DIR = Path(__file__).resolve().parent
CHANNELS_JSON = _COLLECTOR_DIR / "configs" / "channels.json"


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


def load_enabled_channel_ids(path: Path | None = None) -> list[str]:
    """
    Load enabled RomRaider param ids from ``configs/channels.json``.

    Only ``id`` and ``enabled`` are read. Optional ``info`` is ignored
    (human-readable notes only).

    Args:
        path: Optional override path; defaults to the package ``channels.json``.

    Returns:
        Param ids for channels with ``\"enabled\": true``, in file order.

    Raises:
        FileNotFoundError: Config file missing.
        ValueError: JSON missing ``channels``, a required field, or no
            enabled channels.
    """
    cfg_path = path if path is not None else CHANNELS_JSON
    if not cfg_path.is_file():
        raise FileNotFoundError(f"Collector channels config not found: {cfg_path}")

    data = json.loads(cfg_path.read_text())
    channels = data.get("channels")
    if not isinstance(channels, list) or not channels:
        raise ValueError(f'{cfg_path}: expected non-empty "channels" array')

    ids: list[str] = []
    for i, ch in enumerate(channels):
        if not isinstance(ch, dict):
            raise ValueError(f"{cfg_path}: channels[{i}] must be an object")
        if "id" not in ch or "enabled" not in ch:
            raise ValueError(f"{cfg_path}: channels[{i}] requires id and enabled")
        if not isinstance(ch["enabled"], bool):
            raise ValueError(f"{cfg_path}: channels[{i}].enabled must be a boolean")
        if not ch["enabled"]:
            continue
        pid = str(ch["id"]).strip()
        if not pid:
            raise ValueError(f"{cfg_path}: channels[{i}].id must be non-empty")
        ids.append(pid)
    if not ids:
        raise ValueError(f"{cfg_path}: no channels with enabled=true")
    return ids


def load_params(
    ecu_id: str,
    param_ids: list[str],
) -> list[SsmParam]:
    """
    Build :class:`~ssm_client.SsmParam` objects from the RomRaider logger XML.

    Looks up each id in standard parameters plus that ECU's extended params.
    Units / gauge bounds come from the first conversion in the XML.

    Args:
        ecu_id: Hex ECU ID used as the map key (e.g. ``\"5C42504007\"``).
        param_ids: RomRaider parameter ids to load.

    Returns:
        Loaded parameters (unknown ids are skipped with a warning). Empty if
        the logger XML cannot be read.
    """
    xml_path = resolve_romraider_xml()
    try:
        print(f"SSM params: RomRaider XML → {format_romraider_xml_path(xml_path)}")
        return load_params_from_xml(ecu_id, param_ids, xml_path)
    except FileNotFoundError as exc:
        print(f"  {exc}")
        return []


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
