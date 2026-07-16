"""
Subaru SSM over CAN client.

Implements ISO 15765-2 (ISO-TP) transport and the SSM command set used by
this project to talk to the ECU on the OBD-II CAN bus.

Protocol summary
----------------
* Request CAN ID ``0x7E0`` (tester → ECU)
* Response CAN ID ``0x7E8`` (ECU → tester)
* SSM init ``0xBF`` → response ``0xFF`` + 5-byte ECU ID
* SSM batch read ``0xA8`` → response ``0xE8`` + one byte per address slot

Public types
------------
``SsmParam``
    Parameter metadata + decode helpers.
``SSMClient``
    Init and batch-read against a ``python-can`` bus.
"""

from __future__ import annotations

import struct
import time
from dataclasses import dataclass

import can

SSM_REQUEST_ID = 0x7E0
SSM_RESPONSE_ID = 0x7E8

SSM_CMD_INIT = 0xBF
SSM_CMD_READ = 0xA8
SSM_RESP_INIT = 0xFF
SSM_RESP_READ = 0xE8

ISOTP_TIMEOUT = 2.0  # seconds to wait for a complete response
FC_TIMEOUT = 0.5  # seconds to wait for flow control


@dataclass
class SsmParam:
    """
    One SSM memory parameter with optional engineering-unit conversion.

    Attributes:
        id: Stable parameter id from the config map (e.g. ``\"P2\"``, ``\"E31\"``).
        name: Human-readable name.
        address: ECU memory start address (24-bit).
        length: Number of bytes to read.
        conversions: RomRaider-style conversion dicts; the first entry is used
            by :meth:`decode` and :attr:`units`.
    """

    id: str
    name: str
    address: int
    length: int
    conversions: list[dict]

    def decode(self, raw: bytes) -> float:
        """
        Convert raw ECU bytes to an engineering value.

        Uses ``storagetype`` (``uint8`` / ``uint16`` / ``int16`` / ``int8`` /
        ``float``) and evaluates the conversion ``expr`` with ``x`` bound to
        the unpacked number. Builtins are not available inside ``expr``.

        Args:
            raw: Bytes read for this parameter (length should match
                :attr:`length`).

        Returns:
            Decoded float, or the unpacked numeric value if ``expr`` fails.
            With no conversions, returns the big-endian integer of ``raw``.
        """
        if not self.conversions:
            return float(int.from_bytes(raw[: self.length], "big"))

        conv = self.conversions[0]
        st = conv.get("storagetype", "uint8").lower()

        if st == "float" and len(raw) >= 4:
            x = struct.unpack(">f", raw[:4])[0]
        elif st == "uint16" and len(raw) >= 2:
            x = struct.unpack(">H", raw[:2])[0]
        elif st == "int16" and len(raw) >= 2:
            x = struct.unpack(">h", raw[:2])[0]
        elif st == "int8" and len(raw) >= 1:
            x = struct.unpack("b", raw[:1])[0]
        else:
            x = raw[0] if raw else 0

        try:
            return float(eval(conv["expr"], {"__builtins__": {}}, {"x": x}))
        except Exception:
            return x

    @property
    def units(self) -> str:
        """Engineering units string from the first conversion, or ``\"\"``."""
        return self.conversions[0].get("units", "") if self.conversions else ""


class SSMClient:
    """
    Subaru Select Monitor client on top of a ``python-can`` bus.

    Handles ISO-TP segmentation/reassembly and the SSM init / batch-read
    commands. Not thread-safe; use one client per bus from a single thread.
    """

    def __init__(self, bus: can.BusABC) -> None:
        """
        Args:
            bus: Open CAN interface used for all request/response traffic.
        """
        self._bus = bus
        self._ecu_id: str | None = None

    # ── Public API ────────────────────────────────────────────────────────────

    def init(self) -> str:
        """
        Send SSM init and return the ECU identifier.

        Returns:
            Five-byte ECU ID as an uppercase hex string (10 hex chars).

        Raises:
            RuntimeError: Missing/invalid init response or ISO-TP failure.
        """
        self._send_isotp(bytes([SSM_CMD_INIT, 0x40]))
        resp = self._recv_isotp()
        if not resp or resp[0] != SSM_RESP_INIT or len(resp) < 6:
            raise RuntimeError(
                f"Bad SSM init response: {resp.hex() if resp else 'timeout'}"
            )
        self._ecu_id = resp[1:6].hex().upper()
        return self._ecu_id

    def batch_read(self, params: list[SsmParam]) -> dict[str, float]:
        """
        Request all parameters in one SSM ``0xA8`` batch and decode them.

        The A8 response returns exactly one byte per requested address.
        Multi-byte parameters are expanded into sequential per-byte address
        slots, then reassembled big-endian before :meth:`SsmParam.decode`.

        Args:
            params: Parameters to read (order preserved in the request).

        Returns:
            Mapping ``param_id → float``. On a bad/missing response, every
            id maps to ``NaN``.
        """
        if not params:
            return {}

        # Expand each param into len(param) sequential 1-byte address slots.
        # slots tracks (param, byte_index_within_param) for response reassembly.
        payload = bytearray([SSM_CMD_READ, 0x00])
        slots: list[tuple[SsmParam, int]] = []
        for p in params:
            for byte_idx in range(p.length):
                payload += (p.address + byte_idx).to_bytes(3, "big")
                slots.append((p, byte_idx))

        self._send_isotp(bytes(payload))
        resp = self._recv_isotp()

        if not resp or resp[0] != SSM_RESP_READ:
            return {p.id: float("nan") for p in params}

        # Reassemble: 1 byte per slot → big-endian byte array per param
        raw: dict[str, bytearray] = {p.id: bytearray(p.length) for p in params}
        for i, (p, byte_idx) in enumerate(slots):
            resp_offset = 1 + i
            if resp_offset < len(resp):
                raw[p.id][byte_idx] = resp[resp_offset]

        return {p.id: p.decode(bytes(raw[p.id])) for p in params}

    # ── ISO-TP send ───────────────────────────────────────────────────────────

    def _send_isotp(self, payload: bytes) -> None:
        """
        Transmit an SSM payload using ISO-TP single or multi-frame send.

        Args:
            payload: Complete SSM PDU (command + data), not including ISO-TP
                PCI bytes.

        Raises:
            RuntimeError: Multi-frame send did not receive flow control.
        """
        if len(payload) <= 7:
            self._send_can(bytes([0x00 | len(payload)]) + payload)
        else:
            # First frame
            total = len(payload)
            self._send_can(
                bytes([0x10 | ((total >> 8) & 0x0F), total & 0xFF]) + payload[:6]
            )
            # Wait for flow control
            fc = self._recv_single(timeout=FC_TIMEOUT)
            if fc is None or (fc[0] & 0xF0) != 0x30:
                raise RuntimeError("No flow control from ECU")

            # Consecutive frames
            seq, offset = 1, 6
            while offset < total:
                chunk = payload[offset : offset + 7]
                self._send_can(bytes([0x20 | (seq & 0x0F)]) + chunk)
                seq += 1
                offset += 7
                time.sleep(0.0005)

    def _send_can(self, data: bytes) -> None:
        """
        Send one 8-byte CAN frame on the SSM request ID.

        Args:
            data: Up to 8 payload bytes; shorter buffers are zero-padded.
        """
        msg = can.Message(
            arbitration_id=SSM_REQUEST_ID,
            data=data + bytes(8 - len(data)),  # pad to 8 bytes
            is_extended_id=False,
        )
        self._bus.send(msg)

    # ── ISO-TP receive ────────────────────────────────────────────────────────

    def _recv_isotp(self) -> bytes | None:
        """
        Reassemble a complete ISO-TP response from the ECU.

        Handles single-frame and first/consecutive-frame sequences, sending
        flow control after a first frame.

        Returns:
            Reassembled PDU bytes, or ``None`` on timeout / sequence error.
        """
        deadline = time.monotonic() + ISOTP_TIMEOUT
        buf = bytearray()
        total_expected = 0
        seq_expected = 1

        while time.monotonic() < deadline:
            raw = self._recv_single(timeout=deadline - time.monotonic())
            if raw is None:
                break

            frame_type = raw[0] & 0xF0

            if frame_type == 0x00:  # single frame
                length = raw[0] & 0x0F
                return bytes(raw[1 : 1 + length])

            elif frame_type == 0x10:  # first frame
                total_expected = ((raw[0] & 0x0F) << 8) | raw[1]
                buf = bytearray(raw[2:8])
                # Send flow control
                self._send_can(bytes([0x30, 0x00, 0x00]))

            elif frame_type == 0x20:  # consecutive frame
                seq = raw[0] & 0x0F
                if seq != (seq_expected & 0x0F):
                    return None  # sequence error
                seq_expected += 1
                buf += raw[1:8]
                if len(buf) >= total_expected:
                    return bytes(buf[:total_expected])

        return bytes(buf) if buf else None

    def _recv_single(self, timeout: float) -> bytes | None:
        """
        Read one CAN frame from the SSM response ID.

        Args:
            timeout: Seconds to wait for a matching frame.

        Returns:
            Frame data bytes, or ``None`` if the deadline expires.
        """
        deadline = time.monotonic() + max(timeout, 0)
        while time.monotonic() < deadline:
            msg = self._bus.recv(timeout=deadline - time.monotonic())
            if msg and msg.arbitration_id == SSM_RESPONSE_ID:
                return bytes(msg.data)
        return None
