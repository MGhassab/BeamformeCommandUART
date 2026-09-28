"""Serial (UART / RS422) communication manager.

All serial I/O happens on a dedicated :class:`UartWorker` thread.  The GUI only
interacts through Qt signals (for received data) and a thread-safe queue (for
outgoing commands), so the interface never blocks on the port and a disconnect
can never freeze or crash the application.
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Dict, Optional

import serial
from PySide6.QtCore import QThread, Signal

from .protocol import FrameParser, ParserConfig


def list_serial_ports():
    """Return the available serial ports as ``(device, description)`` tuples."""
    from serial.tools import list_ports

    ports = []
    for info in sorted(list_ports.comports(), key=lambda p: p.device):
        description = info.description or ""
        if description and description != info.device:
            ports.append((info.device, f"{info.device} \u2014 {description}"))
        else:
            ports.append((info.device, info.device))
    return ports


class UartWorker(QThread):
    """Owns the serial port: reads frames and writes queued commands.

    Signals
    -------
    connected(dict)          port opened successfully
    disconnected()           port closed (cleanly or after an error)
    failed(str)              the port could not be opened / dropped
    command_sent(bytes)      a command frame was written to the port
    frame_received(object)   a decoded :class:`~.protocol.ParsedFrame`
    stats(dict)              per-second counters (ok / crc / format errors)
    """

    connected = Signal(dict)
    disconnected = Signal()
    failed = Signal(str)
    command_sent = Signal(bytes)
    frame_received = Signal(object)
    stats = Signal(dict)

    def __init__(
        self,
        port: str,
        baud: int,
        parser: FrameParser,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._port = port
        self._baud = baud
        self._parser = parser
        self._tx_queue: "queue.Queue[bytes]" = queue.Queue()
        self._stop_event = threading.Event()

        self._ok = 0
        self._crc_errors = 0
        self._format_errors = 0
        self._last_stats = time.monotonic()

    # -- public API (called from the GUI thread) --------------------------- #
    @property
    def port(self) -> str:
        return self._port

    @property
    def baud(self) -> int:
        return self._baud

    def send_command(self, frame: bytes) -> None:
        """Queue a command frame to be written by the worker thread."""
        self._tx_queue.put(bytes(frame))

    def stop(self) -> None:
        """Ask the worker to shut down and wait briefly for it to finish."""
        self._stop_event.set()

    # -- worker thread ----------------------------------------------------- #
    def run(self) -> None:  # noqa: D401
        try:
            ser = serial.Serial(
                port=self._port,
                baudrate=self._baud,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.02,
                write_timeout=1.0,
            )
        except Exception as exc:  # port missing, busy, invalid baud, ...
            self.failed.emit(self._describe_open_error(exc))
            return

        self.connected.emit({"port": self._port, "baud": self._baud})
        try:
            while not self._stop_event.is_set():
                self._drain_tx(ser)
                try:
                    data = ser.read(4096)
                except Exception as exc:
                    self.failed.emit(f"Serial read error on {self._port}: {exc}")
                    break
                if data:
                    for frame in self._parser.feed(data):
                        self._dispatch(frame)
                self._maybe_emit_stats()
        finally:
            try:
                ser.close()
            except Exception:
                pass
            self.disconnected.emit()

    # -- internals --------------------------------------------------------- #
    def _drain_tx(self, ser: "serial.Serial") -> None:
        while True:
            try:
                frame = self._tx_queue.get_nowait()
            except queue.Empty:
                return
            try:
                ser.write(frame)
                ser.flush()
                self.command_sent.emit(frame)
            except Exception as exc:
                self.failed.emit(f"Serial write error on {self._port}: {exc}")
                self._stop_event.set()
                return

    def _dispatch(self, frame) -> None:
        if frame.error:
            self._format_errors += 1
            return
        if not frame.crc_ok:
            self._crc_errors += 1
            if self._parser.config.verify_crc:
                return  # reject corrupted frames
        self._ok += 1
        self.frame_received.emit(frame)

    def _maybe_emit_stats(self) -> None:
        now = time.monotonic()
        if now - self._last_stats < 1.0:
            return
        self.stats.emit(
            {
                "ok": self._ok,
                "crc": self._crc_errors,
                "format": self._format_errors,
            }
        )
        self._ok = self._crc_errors = self._format_errors = 0
        self._last_stats = now

    @staticmethod
    def _describe_open_error(exc: Exception) -> str:
        text = str(exc)
        lowered = text.lower()
        if "access is denied" in lowered or "busy" in lowered or "in use" in lowered:
            return f"Port is already in use: {text}"
        if "could not open" in lowered or "cannot find" in lowered or "file not found" in lowered:
            return f"Port does not exist or is unavailable: {text}"
        return f"Failed to open port: {text}"


def open_worker(port: str, baud: int, config: Optional[ParserConfig] = None):
    """Convenience factory returning ``(worker, parser)``."""
    parser = FrameParser(config or ParserConfig())
    worker = UartWorker(port, baud, parser)
    return worker, parser
