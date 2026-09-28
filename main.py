"""Beamformer UART Console - application entry point.

Run from the ``UART`` directory::

    python main.py
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from beamformer_uart.main_window import MainWindow
from beamformer_uart.theme import stylesheet


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Beamformer UART Console")
    app.setOrganizationName("Beamformer")
    app.setStyle("Fusion")
    app.setStyleSheet(stylesheet())

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
