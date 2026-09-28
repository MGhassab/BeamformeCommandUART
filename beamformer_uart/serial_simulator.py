"""Virtual beamformer board over a serial port.

Useful for testing the console without hardware.  Run it on one end of a
virtual serial pair (e.g. ``com0com`` COM4 <-> COM5), then point the
application at the other end::

    python -m beamformer_uart.serial_simulator --port COM5 --baud 115200

The simulator decodes command frames exactly as the protocol module does and
streams back RX frames carrying six band outputs (the 6 x 1 output matrix).
"""

from __future__ import annotations

import argparse
import math
import random
import struct
import sys
import time

import serial

from . import protocol
from .crc import CRC_ALGORITHMS, DEFAULT_CRC_NAME


class BoardState:
    def __init__(self) -> None:
        self.running = False
        self.calibrating = False
        self.calibration_done = False
        self._calibration_deadline = 0.0

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False

    def start_calibration(self, hold_s: float) -> None:
        self.calibrating = True
        self.calibration_done = False
        self._calibration_deadline = time.monotonic() + hold_s

    def update(self) -> None:
        if self.calibrating and time.monotonic() >= self._calibration_deadline:
            self.calibrating = False
            self.calibration_done = True
            print("[board] calibration complete", flush=True)

    def status_byte(self) -> int:
        byte = 0
        if self.calibration_done:
            byte |= 1 << protocol.BIT_CALIBRATION_DONE
        if self.running:
            for band in range(protocol.NUM_BANDS):
                byte |= 1 << (protocol.BIT_BAND_STATE_BASE + band)
        return byte


def band_values(t: float) -> list:
    """Synthesise six plausible band output floats."""
    return [
        800.0 * math.sin(2 * math.pi * 0.7 * t + 0.0) + random.uniform(-2, 2),
        400.0 * math.sin(2 * math.pi * 0.9 * t + 0.7) + random.uniform(-2, 2),
        200.0 * math.sin(2 * math.pi * 1.3 * t + 1.4) + random.uniform(-2, 2),
        100.0 * math.sin(2 * math.pi * 1.7 * t + 2.1) + random.uniform(-1, 1),
        50.0 * math.sin(2 * math.pi * 2.3 * t + 2.8) + random.uniform(-1, 1),
        25.0 * math.sin(2 * math.pi * 3.1 * t + 3.5) + random.uniform(-1, 1),
    ]


def build_rx_frame(state: BoardState, t: float, config: protocol.ParserConfig) -> bytes:
    records = [bytes((protocol.STATUS_RECORD_INDEX, 0, 0, 0, state.status_byte()))]
    for band, value in enumerate(band_values(t), start=1):
        records.append(bytes((band,)) + struct.pack(config.byteorder, value))
    return protocol.build_frame(records, config)


def run(port: str, baud: int, rate: float, crc_name: str, byteorder: str, calib_hold: float) -> None:
    config = protocol.ParserConfig(
        crc_fn=CRC_ALGORITHMS.get(crc_name, CRC_ALGORITHMS[DEFAULT_CRC_NAME]),
        verify_crc=False,
        byteorder=byteorder,
    )
    parser = protocol.FrameParser(config)
    state = BoardState()
    interval = 1.0 / rate if rate > 0 else 0.05

    print(f"[sim] opening {port} @ {baud} 8-N-1 (CRC {crc_name})", flush=True)
    with serial.Serial(port=port, baudrate=baud, timeout=0.01) as ser:
        start = time.monotonic()
        last_sent = 0.0
        sent = 0
        try:
            while True:
                data = ser.read(4096)
                if data:
                    for frame in parser.feed(data):
                        if frame.error:
                            print(f"[sim] malformed frame: {frame.error}", flush=True)
                            continue
                        _handle_command(frame, state, calib_hold)

                state.update()
                now = time.monotonic()
                if now - last_sent >= interval:
                    rx = build_rx_frame(state, now - start, config)
                    ser.write(rx)
                    sent += 1
                    if sent % max(1, int(rate)) == 0:
                        print(f"[sim] {sent} frames sent", flush=True)
                    last_sent = now
        except KeyboardInterrupt:
            print("\n[sim] stopped", flush=True)


def _handle_command(frame, state: BoardState, calib_hold: float) -> None:
    if not frame.records:
        return
    index, payload = frame.records[0]
    if index != protocol.STATUS_RECORD_INDEX:
        return
    bitwise = payload[3]
    if bitwise & (1 << protocol.BIT_START_CALIBRATION):
        print("[board] START CALIBRATION", flush=True)
        state.start_calibration(calib_hold)
    if bitwise & (1 << protocol.BIT_START):
        print("[board] START", flush=True)
        state.start()
    if bitwise & (1 << protocol.BIT_STOP):
        print("[board] STOP", flush=True)
        state.stop()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Beamformer UART board simulator")
    ap.add_argument("--port", required=True, help="serial port to open, e.g. COM5")
    ap.add_argument("--baud", type=int, default=115200, help="baud rate (default 115200)")
    ap.add_argument("--rate", type=float, default=20.0, help="frames per second (default 20)")
    ap.add_argument("--crc", default=DEFAULT_CRC_NAME, choices=list(CRC_ALGORITHMS.keys()))
    ap.add_argument("--byteorder", default=">f", choices=[">f", "<f"],
                    help="float byte order: >f big-endian (default), <f little-endian")
    ap.add_argument("--calib-hold", type=float, default=1.0,
                    help="seconds the simulated calibration takes (default 1)")
    args = ap.parse_args(argv)

    try:
        run(args.port, args.baud, args.rate, args.crc, args.byteorder, args.calib_hold)
    except serial.SerialException as exc:
        print(f"[sim] could not open {args.port}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
