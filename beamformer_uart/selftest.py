"""End-to-end self test for the Beamformer UART Console.

Runs three checks:

1. protocol frame build/parse/CRC/resync round trip
2. offscreen GUI construction smoke test
3. optional serial loopback using the bundled board simulator

For the loopback test a couple of virtual ports (e.g. com0com COM4 <-> COM5)
are required.  Configure them with the ``--app-port`` / ``--sim-port`` /
``--baud`` options.  Exit code is non-zero if any executed check fails.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

from . import protocol
from .data_model import HistoryManager


def _result(name: str, ok: bool, detail: str = "") -> bool:
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}" + (f"  ({detail})" if detail else ""), flush=True)
    return ok


def check_protocol() -> bool:
    return _result("protocol", protocol._self_test())


def check_gui() -> bool:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtWidgets import QApplication

        from .main_window import MainWindow
        from .theme import stylesheet

        app = QApplication.instance() or QApplication(sys.argv)
        app.setStyleSheet(stylesheet())
        window = MainWindow()
        ok = (
            window.windowTitle() == "Beamformer UART Console"
            and len(window.tiles) == protocol.NUM_BANDS
            and window._history.capacity == 101
        )
        window.close()
        return _result("gui", ok)
    except Exception as exc:  # pragma: no cover
        return _result("gui", False, repr(exc))


def check_loopback(app_port: str, sim_port: str, baud: int, crc: str, byteorder: str) -> bool:
    from PySide6.QtCore import QCoreApplication, QTimer

    from .crc import get_crc
    from .protocol import CMD_START, CMD_START_CALIBRATION, FrameParser, ParserConfig, build_command
    from .uart_manager import UartWorker

    simulator = subprocess.Popen(
        [
            sys.executable, "-m", "beamformer_uart.serial_simulator",
            "--port", sim_port, "--baud", str(baud), "--rate", "100",
            "--crc", crc, "--byteorder", byteorder, "--calib-hold", "0.5",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1.0)  # let the simulator open the port

    app = QCoreApplication.instance() or QCoreApplication(sys.argv)
    config = ParserConfig(crc_fn=get_crc(crc), verify_crc=True, byteorder=byteorder)
    worker = UartWorker(app_port, baud, FrameParser(config))
    history = HistoryManager()
    stats = {"frames": 0, "calib_done": False, "commands": 0, "failed": None}

    def on_frame(frame) -> None:
        stats["frames"] += 1
        if frame.calibration_done:
            stats["calib_done"] = True
        history.add(
            values=frame.bands,
            calibration_done=frame.calibration_done,
            band_states=frame.band_states,
            crc_ok=frame.crc_ok,
        )

    def on_connected(_info: dict) -> None:
        worker.send_command(build_command(CMD_START, config))
        worker.send_command(build_command(CMD_START_CALIBRATION, config))

    def on_command_sent(_frame: bytes) -> None:
        stats["commands"] += 1

    def on_failed(message: str) -> None:
        stats["failed"] = message

    worker.connected.connect(on_connected)
    worker.frame_received.connect(on_frame)
    worker.command_sent.connect(on_command_sent)
    worker.failed.connect(on_failed)

    QTimer.singleShot(3000, app.quit)
    worker.start()
    app.exec()
    worker.stop()
    worker.wait(1500)

    simulator.terminate()
    try:
        simulator.wait(2)
    except Exception:
        simulator.kill()

    ok = (
        stats["failed"] is None
        and stats["commands"] >= 2
        and stats["frames"] > 120
        and stats["calib_done"]
        and len(history) == 101
        and history.latest is not None
        and all(v is not None for v in history.latest.values)
    )
    detail = (
        f"commands={stats['commands']} frames={stats['frames']} "
        f"calib={stats['calib_done']} history={len(history)}"
        + (f" err={stats['failed']}" if stats["failed"] else "")
    )
    return _result("serial loopback", ok, detail)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--app-port", default="COM4", help="port the app opens (default COM4)")
    ap.add_argument("--sim-port", default="COM5", help="port the simulator opens (default COM5)")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--crc", default="CRC-16/CCITT-FALSE")
    ap.add_argument("--byteorder", default=">f", choices=[">f", "<f"])
    ap.add_argument("--skip-loopback", action="store_true", help="skip the serial test")
    args = ap.parse_args(argv)

    results = [check_protocol(), check_gui()]
    if not args.skip_loopback:
        try:
            results.append(
                check_loopback(args.app_port, args.sim_port, args.baud, args.crc, args.byteorder)
            )
        except Exception as exc:  # pragma: no cover
            results.append(_result("serial loopback", False, repr(exc)))

    print("\nOVERALL:", "PASS" if all(results) else "FAIL")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
