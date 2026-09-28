"""Wire protocol for the beamformer board (recovered from ``Document.pdf``).

Frame layout, used in both directions::

    +------+------+-----+-----+-----+---------------+-----+-----+-------+-------+-----+
    | SYN1 | SYN2 | STX | FT  | LEN |     DATA      | PAD | EOD | CRC H | CRC L | ETX |
    | 0xAA | 0x55 | 0x7E| 0x00|  n  | n x 5 bytes   |0x00 |0x2A |  hi   |  lo   |0x81 |
    +------+------+-----+-----+-----+---------------+-----+-----+-------+-------+-----+

* ``LEN`` is the number of 5-byte DATA records.
* Each record is ``Index (1 byte) + payload (4 bytes)``.
* **Commands (TX)**: one record with ``Index = 0``, three reserved bytes and a
  bitwise command byte (bit0 = Start Calibration, bit1 = Start, bit2 = Stop).
* **Data (RX)**: seven records.  Record 0 is a status record (``Index = 0``)
  whose bitwise byte carries Calibration Done (bit0) and Band1..Band6 State
  (bits 1..6).  Records 1..6 (``Index = 1..6``) carry ``Band1..Band6 Output``
  as 4-byte IEEE-754 floats.
* ``CRC`` is computed over ``FT + LEN + DATA + PAD`` and transmitted high byte
  first.  The document does not state the algorithm, so it is selectable.
* Floats are transmitted most-significant byte first (big-endian), per the
  document's column order "High-order / Middle-high / Middle-low / Low-order".

The six ``Band Output`` values are the "6 x 1 output matrix" shown in the GUI.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

from .crc import DEFAULT_CRC_NAME, crc16_none, get_crc

# --------------------------------------------------------------------------- #
# Frame constants
# --------------------------------------------------------------------------- #
SYN1 = 0xAA
SYN2 = 0x55
STX = 0x7E
FT = 0x00
PAD = 0x00
EOD = 0x2A
ETX = 0x81

SYNC = bytes((SYN1, SYN2, STX))
RECORD_SIZE = 5                      # 1 index byte + 4 payload bytes
HEADER_SIZE = 5                      # SYN1 SYN2 STX FT LEN
TRAILER_SIZE = 5                     # PAD EOD CRC H CRC L ETX
MIN_FRAME_SIZE = HEADER_SIZE + TRAILER_SIZE          # LEN == 0
MAX_RECORDS = 64                     # sanity cap to bound buffering on desync

NUM_BANDS = 6
STATUS_RECORD_INDEX = 0x00

# Command bit positions inside the TX bitwise byte.
BIT_START_CALIBRATION = 0
BIT_START = 1
BIT_STOP = 2

# Status bit positions inside the RX status bitwise byte.
BIT_CALIBRATION_DONE = 0
BIT_BAND_STATE_BASE = 1              # Band1 state at bit 1 ... Band6 at bit 6


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Command:
    """A board command: its display label and its bit mask in the bitwise byte."""

    key: str
    label: str
    mask: int


CMD_START_CALIBRATION = Command("start_calibration", "START CALIBRATION", 1 << BIT_START_CALIBRATION)
CMD_START = Command("start", "START", 1 << BIT_START)
CMD_STOP = Command("stop", "STOP", 1 << BIT_STOP)

ALL_COMMANDS = (CMD_START, CMD_STOP, CMD_START_CALIBRATION)


# --------------------------------------------------------------------------- #
# Parser configuration
# --------------------------------------------------------------------------- #
@dataclass
class ParserConfig:
    """Live parser settings; the GUI may mutate these while a worker runs.

    Attribute assignment is atomic in CPython, so the worker thread can safely
    read these values without a lock.
    """

    crc_fn: Callable[[bytes], int] = field(default_factory=lambda: get_crc(DEFAULT_CRC_NAME))
    verify_crc: bool = True
    byteorder: str = ">f"            # big-endian IEEE-754 float

    def crc_enabled(self) -> bool:
        """True when a real CRC algorithm (not the ``None`` placeholder) is set."""
        return self.crc_fn is not crc16_none


# --------------------------------------------------------------------------- #
# Parsed frame
# --------------------------------------------------------------------------- #
@dataclass
class ParsedFrame:
    """Result of decoding a single wire frame."""

    raw: bytes
    length: int
    records: List[Tuple[int, bytes]] = field(default_factory=list)
    crc_expected: int = 0
    crc_actual: int = 0
    crc_checked: bool = False
    crc_ok: bool = True
    error: str = ""

    #: Status record fields (only meaningful for RX frames).
    calibration_done: bool = False
    band_states: Tuple[bool, ...] = (False,) * NUM_BANDS
    #: Six band output values, oldest layout; ``None`` where absent.
    bands: Optional[List[float]] = None

    @property
    def ok(self) -> bool:
        return not self.error


# --------------------------------------------------------------------------- #
# Frame construction
# --------------------------------------------------------------------------- #
def _build_data_records(records: List[bytes]) -> bytes:
    return b"".join(records)


def build_frame(records: List[bytes], config: ParserConfig) -> bytes:
    """Assemble a complete frame from already-encoded 5-byte records."""
    length = len(records)
    if length > MAX_RECORDS:
        raise ValueError(f"too many records: {length}")
    for rec in records:
        if len(rec) != RECORD_SIZE:
            raise ValueError(f"record must be {RECORD_SIZE} bytes, got {len(rec)}")

    data = _build_data_records(records)
    crc_region = bytes((FT, length)) + data + bytes((PAD,))
    crc = config.crc_fn(crc_region) & 0xFFFF
    return (
        SYNC
        + crc_region
        + bytes((EOD, (crc >> 8) & 0xFF, crc & 0xFF, ETX))
    )


def build_command(command: Command, config: ParserConfig) -> bytes:
    """Build the UART frame that sends ``command`` to the board."""
    record = bytes((STATUS_RECORD_INDEX, 0x00, 0x00, 0x00, command.mask & 0xFF))
    return build_frame([record], config)


# --------------------------------------------------------------------------- #
# Frame decoding
# --------------------------------------------------------------------------- #
def parse_frame(frame: bytes, config: ParserConfig) -> ParsedFrame:
    """Decode one complete frame (as delimited by :class:`FrameParser`)."""
    result = ParsedFrame(raw=frame, length=0)

    if len(frame) < MIN_FRAME_SIZE:
        result.error = "frame too short"
        return result

    length = frame[4]
    result.length = length
    data_start = HEADER_SIZE
    data_end = data_start + length * RECORD_SIZE
    total = data_end + TRAILER_SIZE
    if len(frame) != total:
        result.error = f"length mismatch (have {len(frame)}, expected {total})"
        return result
    if frame[0:3] != SYNC:
        result.error = "bad sync"
        return result
    if frame[3] != FT:
        result.error = f"unexpected FT 0x{frame[3]:02X}"
        return result

    pad = frame[data_end]
    eod = frame[data_end + 1]
    crc_hi = frame[data_end + 2]
    crc_lo = frame[data_end + 3]
    etx = frame[data_end + 4]
    if pad != PAD:
        result.error = f"unexpected PAD 0x{pad:02X}"
        return result
    if eod != EOD:
        result.error = f"unexpected EOD 0x{eod:02X}"
        return result
    if etx != ETX:
        result.error = f"unexpected ETX 0x{etx:02X}"
        return result

    data = frame[data_start:data_end]
    result.records = [
        (data[i], data[i + 1 : i + RECORD_SIZE]) for i in range(0, len(data), RECORD_SIZE)
    ]

    # CRC over FT + LEN + DATA + PAD.
    crc_region = frame[3 : data_end + 1]
    result.crc_expected = (crc_hi << 8) | crc_lo
    result.crc_actual = config.crc_fn(crc_region) & 0xFFFF
    result.crc_checked = config.verify_crc and config.crc_enabled()
    result.crc_ok = (not result.crc_checked) or (result.crc_expected == result.crc_actual)

    _decode_payload(result, config)
    return result


def _decode_payload(result: ParsedFrame, config: ParserConfig) -> None:
    """Extract status bits and band floats from the decoded records."""
    bands: List[Optional[float]] = [None] * NUM_BANDS
    states = [False] * NUM_BANDS

    for index, payload in result.records:
        if index == STATUS_RECORD_INDEX:
            bitwise = payload[3]
            result.calibration_done = bool(bitwise & (1 << BIT_CALIBRATION_DONE))
            for band in range(NUM_BANDS):
                states[band] = bool(bitwise & (1 << (BIT_BAND_STATE_BASE + band)))
        elif 1 <= index <= NUM_BANDS:
            (value,) = struct.unpack(config.byteorder, payload)
            bands[index - 1] = float(value)

    result.band_states = tuple(states)
    if any(v is not None for v in bands):
        result.bands = bands


class FrameParser:
    """Streaming frame parser with byte-wise resynchronisation.

    Feed raw serial bytes with :meth:`feed`; it returns the list of complete
    frames decoded from the buffer.  Corrupt, incomplete or unexpected byte
    sequences are counted and skipped rather than raising, so a noisy or
    mid-stream connection can never crash the reader.
    """

    def __init__(self, config: Optional[ParserConfig] = None) -> None:
        self.config = config or ParserConfig()
        self._buf = bytearray()
        self.format_errors = 0
        self.frames_decoded = 0

    def reset(self) -> None:
        self._buf.clear()

    def feed(self, data: bytes) -> List[ParsedFrame]:
        if data:
            self._buf.extend(data)

        frames: List[ParsedFrame] = []
        while True:
            idx = self._buf.find(SYNC)
            if idx < 0:
                # Keep the last two bytes in case they are a partial sync.
                if len(self._buf) > 2:
                    del self._buf[:-2]
                return frames
            if idx:
                del self._buf[:idx]
            if len(self._buf) < HEADER_SIZE:
                return frames

            length = self._buf[4]
            if length > MAX_RECORDS:
                # Implausible length -> we are not actually synced.  Skip one
                # byte and search again.
                self.format_errors += 1
                del self._buf[0:1]
                continue

            total = HEADER_SIZE + length * RECORD_SIZE + TRAILER_SIZE
            if len(self._buf) < total:
                return frames

            frame = bytes(self._buf[:total])
            del self._buf[:total]
            parsed = parse_frame(frame, self.config)
            if parsed.error:
                self.format_errors += 1
            else:
                self.frames_decoded += 1
            frames.append(parsed)


# --------------------------------------------------------------------------- #
# Self test
# --------------------------------------------------------------------------- #
def _self_test() -> bool:
    """Round-trip / resync verification (run ``python -m beamformer_uart.protocol``)."""
    ok = True
    config = ParserConfig()

    # Command round trip.  Header up to PAD is fixed; CRC depends on the
    # selected algorithm and occupies the two bytes before ETX.
    frame = build_command(CMD_START, config)
    assert frame[:12] == bytes.fromhex("AA 55 7E 00 01 00 00 00 00 02 00 2A"), frame.hex(" ")
    assert frame[-1] == ETX
    parsed = parse_frame(frame, ParserConfig(verify_crc=False, byteorder=">f"))
    assert parsed.ok, parsed.error
    assert parsed.records[0][0] == 0
    assert parsed.records[0][1][3] == CMD_START.mask

    for cmd in ALL_COMMANDS:
        f = build_command(cmd, config)
        assert len(f) == 15, (cmd.label, len(f))
        p = parse_frame(f, ParserConfig(verify_crc=True, byteorder=">f"))
        assert p.ok, p.error
        assert p.crc_ok, f"CRC mismatch for {cmd.label}"

    # RX frame round trip with 6 band floats + status.
    values = [1.5, -2.25, 0.0, 12345.5, -0.125, 3.25]
    records = [bytes((STATUS_RECORD_INDEX, 0, 0, 0, 0b01000111))]
    for band, val in enumerate(values, start=1):
        records.append(bytes((band,)) + struct.pack(">f", val))
    rx = build_frame(records, config)
    assert len(rx) == HEADER_SIZE + 7 * RECORD_SIZE + TRAILER_SIZE, len(rx)

    parsed = parse_frame(rx, ParserConfig(verify_crc=True, byteorder=">f"))
    assert parsed.ok, parsed.error
    assert parsed.crc_ok
    assert parsed.calibration_done is True          # bit0 set
    assert parsed.band_states == (True, True, False, False, False, True)  # bits 1,2,6
    assert parsed.bands == values, parsed.bands

    # Streaming parser: split across chunks + leading garbage.
    stream = FrameParser(ParserConfig())
    noise = b"\x11\x22\x33"
    out = []
    blob = noise + rx + rx
    for i in range(0, len(blob), 7):
        out.extend(stream.feed(blob[i : i + 7]))
    assert len(out) == 2, len(out)
    assert all(f.ok for f in out)

    # Corrupt a byte -> resync and still decode the following good frame.
    corrupt = bytearray(rx)
    corrupt[10] ^= 0xFF
    stream2 = FrameParser(ParserConfig())
    got = stream2.feed(bytes(corrupt) + rx)
    assert any(not f.ok or not f.crc_ok for f in got), "corruption not detected"
    assert any(f.ok and f.crc_ok for f in got), "failed to resync to good frame"

    print("protocol self-test:", "PASS" if ok else "FAIL")
    return ok


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(0 if _self_test() else 1)
