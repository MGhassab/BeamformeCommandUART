"""CRC-16 variants for the beamformer UART protocol.

``Document.pdf`` states that the frame CRC is calculated over
``FT + LEN + DATA + PAD`` and is transmitted high byte first, but it does not
name the algorithm.  To avoid inventing a protocol, the correct algorithm is
exposed as a selectable setting and several industry-standard CRC-16 variants
are provided here.

Every function takes ``bytes`` and returns an ``int`` in ``0..0xFFFF``.
"""

from __future__ import annotations

from typing import Callable, Dict

__all__ = [
    "crc16_ccitt_false",
    "crc16_xmodem",
    "crc16_modbus",
    "crc16_ibm_arc",
    "crc16_none",
    "CRC_ALGORITHMS",
    "get_crc",
]


def _reflect(value: int, bits: int) -> int:
    """Reverse the low ``bits`` bits of ``value``."""
    result = 0
    for _ in range(bits):
        result = (result << 1) | (value & 1)
        value >>= 1
    return result


def _crc16(
    data: bytes,
    poly: int,
    init: int,
    refin: bool,
    refout: bool,
    xorout: int,
) -> int:
    """Generic bit-wise CRC-16 implementation (MSB-first register)."""
    crc = init
    for byte in data:
        if refin:
            byte = _reflect(byte, 8)
        crc ^= (byte << 8) & 0xFFFF
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ poly) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    if refout:
        crc = _reflect(crc, 16)
    return (crc ^ xorout) & 0xFFFF


def crc16_ccitt_false(data: bytes) -> int:
    """CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF, non-reflected."""
    return _crc16(data, poly=0x1021, init=0xFFFF, refin=False, refout=False, xorout=0x0000)


def crc16_xmodem(data: bytes) -> int:
    """CRC-16/XMODEM: poly 0x1021, init 0x0000, non-reflected."""
    return _crc16(data, poly=0x1021, init=0x0000, refin=False, refout=False, xorout=0x0000)


def crc16_modbus(data: bytes) -> int:
    """CRC-16/MODBUS: poly 0x8005, init 0xFFFF, reflected in/out."""
    return _crc16(data, poly=0x8005, init=0xFFFF, refin=True, refout=True, xorout=0x0000)


def crc16_ibm_arc(data: bytes) -> int:
    """CRC-16/IBM (ARC): poly 0x8005, init 0x0000, reflected in/out."""
    return _crc16(data, poly=0x8005, init=0x0000, refin=True, refout=True, xorout=0x0000)


def crc16_none(data: bytes) -> int:  # noqa: ARG001 - signature compatibility
    """Placeholder used when CRC checking is disabled: always returns 0."""
    return 0


#: Human-readable name -> CRC function.  ``None`` disables CRC checking.
CRC_ALGORITHMS: Dict[str, Callable[[bytes], int]] = {
    "CRC-16/CCITT-FALSE": crc16_ccitt_false,
    "CRC-16/XMODEM": crc16_xmodem,
    "CRC-16/MODBUS": crc16_modbus,
    "CRC-16/IBM (ARC)": crc16_ibm_arc,
    "None": crc16_none,
}

DEFAULT_CRC_NAME = "CRC-16/CCITT-FALSE"


def get_crc(name: str) -> Callable[[bytes], int]:
    """Return the CRC function registered under ``name``.

    Falls back to CRC-16/CCITT-FALSE for unknown names so the application
    never crashes on a bad setting.
    """
    return CRC_ALGORITHMS.get(name, crc16_ccitt_false)
