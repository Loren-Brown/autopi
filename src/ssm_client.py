"""
Subaru SSM over CAN client.

Protocol:
  - CAN ID 0x7E0  tester → ECU  (requests)
  - CAN ID 0x7E8  ECU → tester  (responses)
  - ISO 15765-2 (ISO-TP) transport framing
  - SSM command set: init (0xBF), batch read (0xA8)
"""

import struct
import time
from dataclasses import dataclass

import can

SSM_REQUEST_ID  = 0x7E0
SSM_RESPONSE_ID = 0x7E8

SSM_CMD_INIT  = 0xBF
SSM_CMD_READ  = 0xA8
SSM_RESP_INIT = 0xFF
SSM_RESP_READ = 0xE8

ISOTP_TIMEOUT = 2.0   # seconds to wait for a complete response
FC_TIMEOUT    = 0.5   # seconds to wait for flow control


@dataclass
class SsmParam:
    id:          str
    name:        str
    address:     int
    length:      int
    conversions: list[dict]

    def decode(self, raw: bytes) -> float:
        """Decode raw bytes to a human-readable float using the first conversion."""
        if not self.conversions:
            return float(int.from_bytes(raw[:self.length], "big"))

        conv = self.conversions[0]
        st   = conv.get("storagetype", "uint8").lower()

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
        return self.conversions[0].get("units", "") if self.conversions else ""


class SSMClient:
    def __init__(self, bus: can.BusABC):
        self._bus = bus
        self._ecu_id: str | None = None

    # ── Public API ────────────────────────────────────────────────────────────

    def init(self) -> str:
        """Send SSM init and return the 5-byte ECU ID as a hex string."""
        self._send_isotp(bytes([SSM_CMD_INIT, 0x40]))
        resp = self._recv_isotp()
        if not resp or resp[0] != SSM_RESP_INIT or len(resp) < 6:
            raise RuntimeError(f"Bad SSM init response: {resp.hex() if resp else 'timeout'}")
        self._ecu_id = resp[1:6].hex().upper()
        return self._ecu_id

    def batch_read(self, params: list[SsmParam]) -> dict[str, float]:
        """Request all params in one batch and return {param_id: decoded_value}.

        The SSM A8 command returns exactly 1 byte per requested address.
        Multi-byte params (e.g. RPM at 0x0E/0x0F, MAF at 0x13/0x14) are
        expanded into individual per-byte address slots, then the bytes are
        reassembled in big-endian order before decoding.
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
        msg = can.Message(
            arbitration_id=SSM_REQUEST_ID,
            data=data + bytes(8 - len(data)),   # pad to 8 bytes
            is_extended_id=False,
        )
        self._bus.send(msg)

    # ── ISO-TP receive ────────────────────────────────────────────────────────

    def _recv_isotp(self) -> bytes | None:
        """Reassemble a complete ISO-TP response from the ECU."""
        deadline = time.monotonic() + ISOTP_TIMEOUT
        buf = bytearray()
        total_expected = 0
        seq_expected = 1

        while time.monotonic() < deadline:
            raw = self._recv_single(timeout=deadline - time.monotonic())
            if raw is None:
                break

            frame_type = raw[0] & 0xF0

            if frame_type == 0x00:          # single frame
                length = raw[0] & 0x0F
                return bytes(raw[1 : 1 + length])

            elif frame_type == 0x10:        # first frame
                total_expected = ((raw[0] & 0x0F) << 8) | raw[1]
                buf = bytearray(raw[2:8])
                # Send flow control
                self._send_can(bytes([0x30, 0x00, 0x00]))

            elif frame_type == 0x20:        # consecutive frame
                seq = raw[0] & 0x0F
                if seq != (seq_expected & 0x0F):
                    return None             # sequence error
                seq_expected += 1
                buf += raw[1:8]
                if len(buf) >= total_expected:
                    return bytes(buf[:total_expected])

        return bytes(buf) if buf else None

    def _recv_single(self, timeout: float) -> bytes | None:
        """Read one CAN frame from the ECU response ID."""
        deadline = time.monotonic() + max(timeout, 0)
        while time.monotonic() < deadline:
            msg = self._bus.recv(timeout=deadline - time.monotonic())
            if msg and msg.arbitration_id == SSM_RESPONSE_ID:
                return bytes(msg.data)
        return None
