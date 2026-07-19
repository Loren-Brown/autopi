"""
RomRaider logger XML reader for SSM address maps.

Resolution order
----------------
1. ``ROMRAIDER_XML`` if set and the path exists as a file (laptop / explicit).
2. Otherwise the single ``*.xml`` under ``ssm-collector/configs/`` (Pi deploy
   copy — real basename preserved by ``deploy.sh``).

Environment
-----------
``ROMRAIDER_XML``
    Optional on the Pi. On a laptop, set to your logger XML under
    ``docs/romraider/`` (see ``.env.example``).

CLI
---
::

    uv run src/ssm-collector/raider_reader.py --summary
    uv run src/ssm-collector/raider_reader.py --ecu 5C42504007 --id E31
"""

from __future__ import annotations

import argparse
import json
import os
import xml.etree.ElementTree as ET
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from ssm_client import SsmParam

load_dotenv()

_COLLECTOR_DIR = Path(__file__).resolve().parent
REPO_ROOT = _COLLECTOR_DIR.parent.parent  # …/src/ssm-collector → repo root
CONFIGS_DIR = _COLLECTOR_DIR / "configs"


def find_configs_xml() -> Path | None:
    """
    Find the single RomRaider ``*.xml`` under ``ssm-collector/configs/``.

    Returns:
        Absolute path when exactly one XML is present, else ``None``.

    Raises:
        FileNotFoundError: More than one ``*.xml`` is present (ambiguous).
    """
    if not CONFIGS_DIR.is_dir():
        return None
    matches = sorted(CONFIGS_DIR.glob("*.xml"))
    if len(matches) == 1:
        return matches[0].resolve()
    if len(matches) > 1:
        names = ", ".join(m.name for m in matches)
        raise FileNotFoundError(
            f"Multiple RomRaider XML files in {CONFIGS_DIR}: {names}. "
            "Keep only one *.xml (deploy.sh replaces the set on each deploy)."
        )
    return None


def resolve_romraider_xml() -> Path:
    """
    Resolve the RomRaider logger XML path.

    Prefers ``ROMRAIDER_XML`` when that file exists; otherwise discovers the
    single ``*.xml`` in ``ssm-collector/configs/``.

    Returns:
        Absolute filesystem path to the logger XML.

    Raises:
        FileNotFoundError: No usable XML path.
    """
    raw = os.getenv("ROMRAIDER_XML", "").strip()
    if raw:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = REPO_ROOT / path
        if path.is_file():
            return path.resolve()

    found = find_configs_xml()
    if found is not None:
        return found

    if raw:
        raise FileNotFoundError(f"ROMRAIDER_XML not found: {raw} (and no *.xml in {CONFIGS_DIR})")
    raise FileNotFoundError(
        f"ROMRAIDER_XML is not set and no *.xml found in {CONFIGS_DIR} "
        "(see .env.example; on the Pi run ./deploy.sh to copy the logger XML)"
    )


def format_romraider_xml_path(path: Path | None = None) -> str:
    """
    Format a logger XML path for logs (repo-relative when possible).

    Args:
        path: Path to format; defaults to :func:`resolve_romraider_xml`.

    Returns:
        Relative path string under the repo root, or the absolute path.
    """
    p = path if path is not None else resolve_romraider_xml()
    try:
        return str(p.resolve().relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return str(p)


def parse_conversions(el: ET.Element) -> list[dict[str, Any]]:
    """
    Parse ``<conversion>`` children under a parameter / ecuparam / ecu element.

    Args:
        el: XML element that may contain conversion definitions.

    Returns:
        List of conversion dicts with units, expr, format, storagetype, gauges.
    """
    conversions: list[dict[str, Any]] = []
    for conv in el.findall(".//conversion"):
        conversions.append(
            {
                "units": conv.get("units", ""),
                "expr": conv.get("expr", "x"),
                "format": conv.get("format", "0.00"),
                "storagetype": conv.get("storagetype", "uint8"),
                "gauge_min": conv.get("gauge_min"),
                "gauge_max": conv.get("gauge_max"),
            }
        )
    return conversions


def parse_xml(xml_path: Path) -> dict[str, list[dict[str, Any]]]:
    """
    Parse a RomRaider logger XML into standard params/switches + per-ECU lists.

    Args:
        xml_path: Path to ``logger_*.xml``.

    Returns:
        Mapping with ``\"__standard__\"`` (parameters + switches) plus one list
        per ECU id string for extended params.
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()

    search_root = root.find(".//protocol[@id='SSM']")
    if search_root is None:
        search_root = root

    ecu_params: dict[str, list[dict[str, Any]]] = defaultdict(list)

    seen_ids: set[str] = set()
    for param in search_root.findall(".//parameter"):
        addr_el = param.find("address")
        if addr_el is None or not addr_el.text:
            continue
        addr_str = addr_el.text.strip()
        try:
            addr_int = int(addr_str, 16)
        except ValueError:
            continue
        if addr_int > 0x00FFFF:
            continue
        pid = param.get("id")
        if not pid or pid in seen_ids:
            continue
        seen_ids.add(pid)
        ecu_params["__standard__"].append(
            {
                "id": pid,
                "name": param.get("name"),
                "desc": param.get("desc", ""),
                "address": f"0x{addr_int:06X}",
                "length": int(addr_el.get("length", "1")),
                "type": "standard",
                "conversions": parse_conversions(param),
            }
        )

    for ecuparam in search_root.findall(".//ecuparam[@target='1']"):
        base = {
            "id": ecuparam.get("id"),
            "name": ecuparam.get("name"),
            "desc": ecuparam.get("desc", ""),
            "type": "extended",
        }
        top_conversions = parse_conversions(ecuparam)

        for ecu_el in ecuparam.findall("ecu"):
            addr_el = ecu_el.find("address")
            if addr_el is None or not addr_el.text:
                continue
            ecu_conversions = parse_conversions(ecu_el) or top_conversions
            entry = {
                **base,
                "address": addr_el.text.strip(),
                "length": int(addr_el.get("length", "1")),
                "conversions": ecu_conversions,
            }
            for ecu_id in ecu_el.get("id", "").split(","):
                ecu_id = ecu_id.strip()
                if ecu_id:
                    ecu_params[ecu_id].append(entry)

    # RomRaider switches: empty elements with byte + bit (no conversions).
    # Do not filter by target — e.g. S142 Parking is target="2".
    for sw in search_root.findall(".//switch"):
        pid = sw.get("id")
        if not pid or pid in seen_ids:
            continue
        byte_str = (sw.get("byte") or "").strip()
        bit_str = (sw.get("bit") or "").strip()
        if not byte_str or not bit_str:
            continue
        try:
            addr_int = int(byte_str, 16)
            bit = int(bit_str)
        except ValueError:
            continue
        if addr_int > 0x00FFFF or not (0 <= bit <= 7):
            continue
        seen_ids.add(pid)
        ecu_params["__standard__"].append(
            {
                "id": pid,
                "name": sw.get("name") or pid,
                "desc": sw.get("desc", ""),
                "address": f"0x{addr_int:06X}",
                "length": 1,
                "bit": bit,
                "type": "switch",
                "conversions": [],
            }
        )

    return ecu_params


def build_output(ecu_params: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """
    Reshape parse results into ``{__standard__, ecus: {...}}``.

    Args:
        ecu_params: Output of :func:`parse_xml` (``__standard__`` is popped).

    Returns:
        Nested map used by :func:`param_index`.
    """
    standard = ecu_params.pop("__standard__", [])
    out: dict[str, Any] = {"__standard__": standard, "ecus": {}}
    for ecu_id, params in sorted(ecu_params.items()):
        out["ecus"][ecu_id] = {
            "ecu_id": ecu_id,
            "extended_params": params,
            "extended_count": len(params),
        }
    return out


@lru_cache(maxsize=4)
def _load_map_cached(xml_path: str, mtime_ns: int) -> dict[str, Any]:
    """Cache parsed logger maps keyed by path + mtime."""
    del mtime_ns  # used only for cache invalidation
    return build_output(parse_xml(Path(xml_path)))


def load_logger_map(xml_path: Path | None = None) -> dict[str, Any]:
    """
    Load and cache the RomRaider logger map.

    Args:
        xml_path: Explicit path, or ``None`` to use :func:`resolve_romraider_xml`.

    Returns:
        Parsed map with ``__standard__`` and per-ECU ``extended_params``.

    Raises:
        FileNotFoundError: ``ROMRAIDER_XML`` unset or logger XML missing.
    """
    path = xml_path if xml_path is not None else resolve_romraider_xml()
    if not path.is_file():
        raise FileNotFoundError(
            f"RomRaider XML not found: {format_romraider_xml_path(path)} "
            f"(check ROMRAIDER_XML in .env)"
        )
    return _load_map_cached(str(path), path.stat().st_mtime_ns)


def param_index(
    ecu_id: str,
    xml_path: Path | None = None,
) -> dict[str, dict[str, Any]]:
    """
    Build ``param_id → raw param dict`` for one ECU (standard + extended + switches).

    Args:
        ecu_id: Five-byte ECU id hex string.
        xml_path: Optional override for the logger XML.

    Returns:
        Merged dict keyed by RomRaider id (e.g. ``\"P2\"``, ``\"E31\"``, ``\"S142\"``).
    """
    data = load_logger_map(xml_path)
    std = data.get("__standard__", [])
    ext = data.get("ecus", {}).get(ecu_id, {}).get("extended_params", [])
    return {p["id"]: p for p in std + ext}


def load_params_from_xml(
    ecu_id: str,
    param_ids: list[str],
    xml_path: Path | None = None,
) -> list[SsmParam]:
    """
    Resolve parameter / switch ids against a RomRaider XML file.

    Uses the first conversion listed for each parameter (unit-system XMLs
    control which conversion is first). Switches use ``bit`` extraction instead.

    Args:
        ecu_id: Hex ECU ID used to select extended addresses.
        param_ids: RomRaider ids (e.g. ``\"P2\"``, ``\"E31\"``, ``\"S142\"``).
        xml_path: Optional XML path; defaults to :func:`resolve_romraider_xml`.

    Returns:
        :class:`SsmParam` list (unknown ids skipped with a warning).
    """
    all_raw = param_index(ecu_id, xml_path)
    params: list[SsmParam] = []
    for pid in param_ids:
        raw = all_raw.get(pid)
        if raw is None:
            print(f"  Warning: param {pid} not found for ECU {ecu_id}, skipping")
            continue
        convs = raw.get("conversions", [])
        conv = convs[0] if convs else {}
        bit = raw.get("bit")
        params.append(
            SsmParam(
                id=pid,
                name=raw["name"],
                address=int(raw["address"], 16),
                length=raw["length"],
                conversions=[conv] if conv else [],
                bit=int(bit) if bit is not None else None,
            )
        )
    return params


def print_summary(out: dict[str, Any]) -> None:
    """Print ECU / parameter / switch counts for a loaded logger map."""
    standard = out.get("__standard__", [])
    switch_count = sum(1 for p in standard if p.get("type") == "switch")
    param_count = len(standard) - switch_count
    ecu_entries = sorted(
        out["ecus"].items(),
        key=lambda x: x[1]["extended_count"],
        reverse=True,
    )
    print(f"\n{'ECU ID':<20} {'Extended':>10} {'Standard':>10} {'Total':>8}")
    print("─" * 52)
    for ecu_id, data in ecu_entries:
        total = data["extended_count"] + len(standard)
        print(f"{ecu_id:<20} {data['extended_count']:>10} {len(standard):>10} {total:>8}")
    print(
        f"\n{len(ecu_entries)} ECU IDs | {param_count} standard params | "
        f"{switch_count} switches (shared)"
    )


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
        help="ECU id for --id lookup (default: SSM_ECU_ID or 5C42504007)",
    )
    p.add_argument("--id", dest="param_id", help="Print one parameter for --ecu")
    p.add_argument("--summary", action="store_true", help="Print ECU summary table")
    return p.parse_args()


def main() -> None:
    """CLI entry: summary / parameter lookup."""
    args = _parse_args()
    xml_path = args.xml
    if xml_path is not None and not xml_path.is_absolute():
        xml_path = (REPO_ROOT / xml_path).resolve()
    if xml_path is None:
        try:
            xml_path = resolve_romraider_xml()
        except FileNotFoundError as exc:
            raise SystemExit(str(exc)) from exc
    if not xml_path.is_file():
        raise SystemExit(f"XML not found: {format_romraider_xml_path(xml_path)}")

    print(f"Reading {format_romraider_xml_path(xml_path)}")
    out = load_logger_map(xml_path)

    if args.param_id:
        idx = param_index(args.ecu, xml_path)
        raw = idx.get(args.param_id)
        if raw is None:
            raise SystemExit(f"{args.param_id} not found for ECU {args.ecu}")
        print(json.dumps(raw, indent=2))

    if args.summary or args.param_id is None:
        print_summary(out)


if __name__ == "__main__":
    main()
