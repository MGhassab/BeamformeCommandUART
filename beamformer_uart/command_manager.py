"""Command/state manager.

Encapsulates the board's operational state so the GUI can decide which command
buttons are valid.  This keeps the "avoid accidental repeated commands" rule in
one place instead of scattering ``setEnabled`` calls through the UI code.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from .protocol import CMD_START, CMD_START_CALIBRATION, CMD_STOP, Command


class CommandController(QObject):
    """Tracks connection / running / calibration state and emits change events."""

    state_changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._connected = False
        self._connecting = False
        self._running = False
        self._calibrating = False

    # -- state ------------------------------------------------------------- #
    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def connecting(self) -> bool:
        return self._connecting

    @property
    def running(self) -> bool:
        return self._running

    @property
    def calibrating(self) -> bool:
        return self._calibrating

    # -- transitions ------------------------------------------------------- #
    def set_connecting(self, value: bool) -> None:
        self._connecting = value
        self._emit()

    def set_connected(self, value: bool) -> None:
        self._connected = value
        if not value:
            self._running = False
            self._calibrating = False
        self._emit()

    def set_running(self, value: bool) -> None:
        self._running = value
        self._emit()

    def set_calibrating(self, value: bool) -> None:
        self._calibrating = value
        self._emit()

    # -- button enable rules ---------------------------------------------- #
    def can_connect(self) -> bool:
        return not self._connected and not self._connecting

    def can_disconnect(self) -> bool:
        return self._connected or self._connecting

    def can_start(self) -> bool:
        return self._connected and not self._running and not self._calibrating

    def can_stop(self) -> bool:
        return self._connected and self._running

    def can_calibrate(self) -> bool:
        return self._connected and not self._running and not self._calibrating

    def allowed(self, command: Command) -> bool:
        if command is CMD_START:
            return self.can_start()
        if command is CMD_STOP:
            return self.can_stop()
        if command is CMD_START_CALIBRATION:
            return self.can_calibrate()
        return False

    # -- helpers ----------------------------------------------------------- #
    def _emit(self) -> None:
        self.state_changed.emit()
