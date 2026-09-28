"""Main application window.

Layout (top to bottom):

* header: title + live connection status pill
* UART configuration card  |  command control card
* latest output card (six prominent value tiles + calibration/band state)
* output history card (newest first, latest row highlighted)
* communication log card

The window contains no serial I/O: it talks to :class:`~.uart_manager.UartWorker`
through signals and to :class:`~.command_manager.CommandController` for button
state.  Received frames are buffered in a :class:`~.data_model.HistoryManager`
and the history table is refreshed on a timer so high-rate data cannot stall
the UI.
"""

from __future__ import annotations

import datetime as _dt
import time
from typing import Dict, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from . import protocol
from .command_manager import CommandController
from .crc import CRC_ALGORITHMS, DEFAULT_CRC_NAME, get_crc
from .data_model import HistoryManager, HistoryTableModel, format_value
from .protocol import (
    ALL_COMMANDS,
    CMD_START,
    CMD_START_CALIBRATION,
    CMD_STOP,
    Command,
    FrameParser,
    ParserConfig,
)
from .uart_manager import UartWorker, list_serial_ports

BAUD_RATES = [9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600]
DEFAULT_BAUD = 115200

BYTE_ORDERS: Dict[str, str] = {
    "Big-endian (MSB first)": ">f",
    "Little-endian (LSB first)": "<f",
}
DEFAULT_BYTE_ORDER = "Big-endian (MSB first)"

#: Refresh the (potentially large) history table at most this often.
HISTORY_REFRESH_MS = 100
#: Warn when no frame has arrived for this many seconds.
DATA_TIMEOUT_S = 3.0
#: Maximum number of log lines kept in the log view.
LOG_MAX_LINES = 3000


def set_dynamic_property(widget: QWidget, name: str, value) -> None:
    """Set a Qt dynamic property and re-polish the widget so QSS reacts."""
    if widget.property(name) == value:
        return
    widget.setProperty(name, value)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


class Card(QFrame):
    """A rounded panel with an optional title row."""

    def __init__(self, title: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(18, 16, 18, 18)
        self._root.setSpacing(12)
        self.header = QHBoxLayout()
        self.header.setSpacing(10)
        if title:
            label = QLabel(title)
            label.setObjectName("cardTitle")
            self.header.addWidget(label)
        self._root.addLayout(self.header)
        self.body = QVBoxLayout()
        self.body.setSpacing(12)
        self._root.addLayout(self.body)

    def add_header_widget(self, widget: QWidget) -> None:
        self.header.addWidget(widget)

    def add_header_stretch(self) -> None:
        self.header.addStretch(1)

    def add(self, widget: QWidget) -> None:
        self.body.addWidget(widget)

    def add_layout(self, layout) -> None:
        self.body.addLayout(layout)


class ValueTile(QFrame):
    """One large channel readout in the "Latest Output" card."""

    def __init__(self, channel: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("valueTile")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(3)

        self.name = QLabel(channel)
        self.name.setObjectName("channelName")
        self.value = QLabel("\u2014")
        self.value.setObjectName("valueBig")
        self.state = QLabel("\u25cf IDLE")
        self.state.setObjectName("bandState")
        set_dynamic_property(self.state, "on", "false")

        layout.addWidget(self.name)
        layout.addWidget(self.value)
        layout.addWidget(self.state)

    def set_value(self, value: Optional[float]) -> None:
        self.value.setText(format_value(value))

    def set_state(self, active: bool) -> None:
        self.state.setText("\u25cf ACTIVE" if active else "\u25cf IDLE")
        set_dynamic_property(self.state, "on", "true" if active else "false")


class MainWindow(QMainWindow):
    # ------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------ #
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Beamformer UART Console")
        self.resize(1360, 900)

        # --- state ---------------------------------------------------- #
        self._history = HistoryManager()
        self._controller = CommandController(self)
        self._controller.state_changed.connect(self._update_controls)

        self._parser_config = ParserConfig(
            crc_fn=get_crc(DEFAULT_CRC_NAME),
            verify_crc=True,
            byteorder=BYTE_ORDERS[DEFAULT_BYTE_ORDER],
        )
        self._parser = FrameParser(self._parser_config)
        self._worker: Optional[UartWorker] = None
        self._history_dirty = False
        self._last_frame_time: Optional[float] = None
        self._data_timeout_warned = False
        self._error_pending = False
        self._totals = {"ok": 0, "crc": 0, "format": 0}
        self._last_command: Optional[Command] = None
        self._last_command_time: Optional[_dt.datetime] = None

        self._build_ui()
        self._refresh_ports()

        self._history_timer = QTimer(self)
        self._history_timer.setInterval(HISTORY_REFRESH_MS)
        self._history_timer.timeout.connect(self._refresh_history)
        self._history_timer.start()

        self._watchdog = QTimer(self)
        self._watchdog.setInterval(1000)
        self._watchdog.timeout.connect(self._check_data_flow)
        self._watchdog.start()

        self._update_controls()
        self._set_status("disconnected", "\u25cf Disconnected")
        self._log("info", "Ready. Configure a COM port and press Connect.")

    # ------------------------------------------------------------------ #
    # UI
    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("centralRoot")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(14)

        outer.addWidget(self._build_header())

        top_row = QHBoxLayout()
        top_row.setSpacing(14)
        top_row.addWidget(self._build_uart_card(), 5)
        top_row.addWidget(self._build_command_card(), 4)
        outer.addLayout(top_row)

        outer.addWidget(self._build_latest_card(), 0)

        lower = QHBoxLayout()
        lower.setSpacing(14)
        lower.addWidget(self._build_history_card(), 3)
        lower.addWidget(self._build_log_card(), 2)
        outer.addLayout(lower, 1)

        self.setCentralWidget(root)

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("header")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(20, 14, 20, 14)

        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = QLabel("Beamformer UART Console")
        title.setObjectName("appTitle")
        subtitle = QLabel("Serial command & telemetry interface  \u00b7  Band1\u2013Band6 output")
        subtitle.setObjectName("appSubtitle")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        layout.addLayout(titles)
        layout.addStretch(1)

        self.status_pill = QLabel("\u25cf Disconnected")
        self.status_pill.setObjectName("statusPill")
        layout.addWidget(self.status_pill, 0, Qt.AlignVCenter)
        return header

    def _build_uart_card(self) -> Card:
        card = Card("UART Configuration")

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)

        # COM port
        port_label = QLabel("COM Port")
        port_label.setObjectName("fieldLabel")
        self.port_combo = QComboBox()
        self.port_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.refresh_btn = QPushButton("\u21bb")
        self.refresh_btn.setToolTip("Rescan serial ports")
        self.refresh_btn.setFixedWidth(38)
        self.refresh_btn.clicked.connect(self._refresh_ports)
        port_row = QHBoxLayout()
        port_row.setSpacing(8)
        port_row.addWidget(self.port_combo, 1)
        port_row.addWidget(self.refresh_btn)
        grid.addWidget(port_label, 0, 0)
        grid.addLayout(port_row, 0, 1)

        # Baud rate
        baud_label = QLabel("Baud Rate")
        baud_label.setObjectName("fieldLabel")
        self.baud_combo = QComboBox()
        self.baud_combo.setEditable(True)
        self.baud_combo.addItems([str(b) for b in BAUD_RATES])
        self.baud_combo.setCurrentText(str(DEFAULT_BAUD))
        grid.addWidget(baud_label, 1, 0)
        grid.addWidget(self.baud_combo, 1, 1)

        # CRC algorithm + verify
        crc_label = QLabel("CRC")
        crc_label.setObjectName("fieldLabel")
        self.crc_combo = QComboBox()
        self.crc_combo.addItems(list(CRC_ALGORITHMS.keys()))
        self.crc_combo.setCurrentText(DEFAULT_CRC_NAME)
        self.crc_combo.currentTextChanged.connect(self._apply_settings)
        self.verify_check = QCheckBox("Verify")
        self.verify_check.setChecked(True)
        self.verify_check.stateChanged.connect(self._apply_settings)
        crc_row = QHBoxLayout()
        crc_row.setSpacing(8)
        crc_row.addWidget(self.crc_combo, 1)
        crc_row.addWidget(self.verify_check)
        grid.addWidget(crc_label, 2, 0)
        grid.addLayout(crc_row, 2, 1)

        # Float byte order
        order_label = QLabel("Float order")
        order_label.setObjectName("fieldLabel")
        self.byteorder_combo = QComboBox()
        self.byteorder_combo.addItems(list(BYTE_ORDERS.keys()))
        self.byteorder_combo.setCurrentText(DEFAULT_BYTE_ORDER)
        self.byteorder_combo.currentTextChanged.connect(self._apply_settings)
        grid.addWidget(order_label, 3, 0)
        grid.addWidget(self.byteorder_combo, 3, 1)

        card.add_layout(grid)

        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setObjectName("primaryButton")
        self.connect_btn.clicked.connect(self._on_connect_clicked)
        card.add(self.connect_btn)

        hint = QLabel("Defaults: 8-N-1, no flow control. Board interface is RS422.")
        hint.setObjectName("mutedLabel")
        hint.setWordWrap(True)
        card.add(hint)
        return card

    def _build_command_card(self) -> Card:
        card = Card("Command Control")

        self.start_btn = QPushButton("START")
        self.start_btn.setObjectName("successButton")
        self.start_btn.setMinimumHeight(46)
        self.start_btn.clicked.connect(lambda: self._send_command(CMD_START))

        self.stop_btn = QPushButton("STOP")
        self.stop_btn.setObjectName("dangerButton")
        self.stop_btn.setMinimumHeight(46)
        self.stop_btn.clicked.connect(lambda: self._send_command(CMD_STOP))

        self.calibrate_btn = QPushButton("START CALIBRATION")
        self.calibrate_btn.setObjectName("warningButton")
        self.calibrate_btn.setMinimumHeight(46)
        self.calibrate_btn.clicked.connect(lambda: self._send_command(CMD_START_CALIBRATION))

        for btn in (self.start_btn, self.stop_btn, self.calibrate_btn):
            btn.setCursor(Qt.PointingHandCursor)
            card.add(btn)

        info = QGridLayout()
        info.setHorizontalSpacing(10)
        info.setVerticalSpacing(6)
        info.addWidget(self._muted("State"), 0, 0)
        self.state_label = QLabel("Idle")
        info.addWidget(self.state_label, 0, 1)
        info.addWidget(self._muted("Last command"), 1, 0)
        self.last_command_label = QLabel("\u2014")
        info.addWidget(self.last_command_label, 1, 1, 1, 2)
        card.add_layout(info)
        return card

    def _build_latest_card(self) -> Card:
        card = Card("Latest Output")
        card.add_header_stretch()

        self.calib_badge = QLabel("CALIBRATION \u2014")
        self.calib_badge.setObjectName("calibBadge")
        set_dynamic_property(self.calib_badge, "done", "false")
        card.add_header_widget(self.calib_badge)

        self.data_age_label = QLabel("waiting for data")
        self.data_age_label.setObjectName("mutedLabel")
        card.add_header_widget(self.data_age_label)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        self.tiles = []
        for i in range(protocol.NUM_BANDS):
            tile = ValueTile(f"CH{i + 1} / BAND{i + 1}")
            self.tiles.append(tile)
            grid.addWidget(tile, i // 3, i % 3)
        for col in range(3):
            grid.setColumnStretch(col, 1)
        card.add_layout(grid)
        return card

    def _build_history_card(self) -> Card:
        card = Card("Output History")
        card.add_header_stretch()

        self.history_info = QLabel(f"0 / {self._history.capacity} records (newest first)")
        self.history_info.setObjectName("mutedLabel")
        card.add_header_widget(self.history_info)

        clear_btn = QPushButton("Clear")
        clear_btn.setObjectName("ghostButton")
        clear_btn.clicked.connect(self._clear_history)
        card.add_header_widget(clear_btn)

        self.history_model = HistoryTableModel(self)
        self.history_table = QTableView()
        self.history_table.setModel(self.history_model)
        self.history_table.setAlternatingRowColors(True)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setEditTriggers(QTableView.NoEditTriggers)
        self.history_table.setSelectionMode(QTableView.NoSelection)
        self.history_table.setFocusPolicy(Qt.NoFocus)
        self.history_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        for col in range(2, self.history_model.columnCount()):
            self.history_table.horizontalHeader().setSectionResizeMode(col, QHeaderView.Stretch)
        self.history_table.verticalHeader().setDefaultSectionSize(26)
        card.add(self.history_table)
        return card

    def _build_log_card(self) -> Card:
        card = Card("Communication Log")
        card.add_header_stretch()

        self.stats_label = QLabel("RX 0/s")
        self.stats_label.setObjectName("mutedLabel")
        card.add_header_widget(self.stats_label)

        clear_btn = QPushButton("Clear")
        clear_btn.setObjectName("ghostButton")
        clear_btn.clicked.connect(lambda: self.log_view.clear())
        card.add_header_widget(clear_btn)

        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("logView")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(LOG_MAX_LINES)
        card.add(self.log_view)
        return card

    @staticmethod
    def _muted(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("fieldLabel")
        return label

    # ------------------------------------------------------------------ #
    # Settings / ports
    # ------------------------------------------------------------------ #
    def _refresh_ports(self) -> None:
        current = self.port_combo.currentData()
        ports = list_serial_ports()

        self.port_combo.blockSignals(True)
        self.port_combo.clear()
        for device, description in ports:
            self.port_combo.addItem(description, device)
        self.port_combo.blockSignals(False)

        if not ports:
            self.port_combo.addItem("No serial ports found", None)

        # Restore previous selection if still present, otherwise pick the
        # first available port.
        if current is not None:
            index = self.port_combo.findData(current)
            if index >= 0:
                self.port_combo.setCurrentIndex(index)

        self._log("info", f"Detected {len(ports)} serial port(s): " + ", ".join(d for d, _ in ports))
        self._update_controls()

    def _apply_settings(self) -> None:
        crc_name = self.crc_combo.currentText()
        self._parser_config.crc_fn = get_crc(crc_name)
        self._parser_config.verify_crc = self.verify_check.isChecked()
        self._parser_config.byteorder = BYTE_ORDERS.get(
            self.byteorder_combo.currentText(), ">f"
        )
        self._log(
            "info",
            f"Parser settings: CRC={crc_name} "
            f"({'verify' if self._parser_config.verify_crc else 'ignore'}), "
            f"float={self.byteorder_combo.currentText()}",
        )

    def _selected_port(self) -> Optional[str]:
        return self.port_combo.currentData()

    def _selected_baud(self) -> Optional[int]:
        text = self.baud_combo.currentText().strip()
        try:
            baud = int(text)
        except ValueError:
            self._log("error", f"Invalid baud rate: '{text}'")
            return None
        if baud <= 0:
            self._log("error", f"Invalid baud rate: '{text}'")
            return None
        return baud

    # ------------------------------------------------------------------ #
    # Connection
    # ------------------------------------------------------------------ #
    def _on_connect_clicked(self) -> None:
        if self._controller.can_disconnect():
            self._disconnect()
        else:
            self._connect()

    def _connect(self) -> None:
        port = self._selected_port()
        if not port:
            self._log("error", "No COM port selected.")
            self._set_status("error", "\u25cf Error")
            return
        baud = self._selected_baud()
        if baud is None:
            self._set_status("error", "\u25cf Error")
            return

        self._apply_settings()
        self._parser.reset()
        self._error_pending = False

        self._worker = UartWorker(port, baud, self._parser)
        self._worker.connected.connect(self._on_connected)
        self._worker.disconnected.connect(self._on_disconnected)
        self._worker.failed.connect(self._on_failed)
        self._worker.command_sent.connect(self._on_command_sent)
        self._worker.frame_received.connect(self._on_frame)
        self._worker.stats.connect(self._on_stats)

        self._controller.set_connecting(True)
        self._set_status("connecting", "\u25cf Connecting\u2026")
        self._log("info", f"Connecting to {port} @ {baud} baud\u2026")
        self._worker.start()

    def _disconnect(self) -> None:
        if self._worker is None:
            return
        self._log("info", "Disconnecting\u2026")
        self._worker.stop()
        worker = self._worker
        self._worker = None
        worker.wait(1500)
        self._controller.set_connecting(False)
        self._controller.set_connected(False)
        self._set_status("disconnected", "\u25cf Disconnected")

    def _on_connected(self, info: dict) -> None:
        self._controller.set_connecting(False)
        self._controller.set_connected(True)
        self._last_frame_time = None
        self._data_timeout_warned = False
        self._set_status("connected", "\u25cf Connected")
        self._log("success", f"Connected to {info['port']} @ {info['baud']} baud")

    def _on_disconnected(self) -> None:
        was_connected = self._controller.connected
        self._controller.set_connecting(False)
        self._controller.set_connected(False)
        if self._error_pending:
            # An error was already logged/reported by _on_failed; keep it visible.
            self._error_pending = False
            self._set_status("error", "\u25cf Error")
        else:
            self._set_status("disconnected", "\u25cf Disconnected")
            if was_connected:
                self._log("warning", "Serial link closed.")
        if self.sender() is self._worker:
            self._worker = None

    def _on_failed(self, message: str) -> None:
        self._error_pending = True
        self._controller.set_connecting(False)
        self._controller.set_connected(False)
        self._set_status("error", "\u25cf Error")
        self._log("error", message)

    # ------------------------------------------------------------------ #
    # Commands
    # ------------------------------------------------------------------ #
    def _send_command(self, command: Command) -> None:
        if self._worker is None or not self._controller.connected:
            self._log("error", f"Cannot send {command.label}: not connected.")
            return
        if not self._controller.allowed(command):
            self._log("warning", f"{command.label} ignored (invalid in current state).")
            return

        frame = protocol.build_command(command, self._parser_config)
        self._worker.send_command(frame)

        self._last_command = command
        self._last_command_time = _dt.datetime.now()
        stamp = self._last_command_time.strftime("%H:%M:%S.") + f"{self._last_command_time.microsecond // 1000:03d}"
        self.last_command_label.setText(f"{command.label}   \u00b7   {stamp}")

        if command is CMD_START:
            self._controller.set_running(True)
        elif command is CMD_STOP:
            self._controller.set_running(False)
        elif command is CMD_START_CALIBRATION:
            self._controller.set_calibrating(True)
            self._log("info", "Calibration started \u2014 waiting for board confirmation\u2026")

    def _on_command_sent(self, frame: bytes) -> None:
        label = self._last_command.label if self._last_command else "?"
        self._log("tx", f"TX {label} \u2192 {frame.hex(' ').upper()}")

    # ------------------------------------------------------------------ #
    # Data
    # ------------------------------------------------------------------ #
    def _on_frame(self, frame) -> None:
        self._last_frame_time = time.monotonic()
        if self._data_timeout_warned:
            self._data_timeout_warned = False
            self._log("success", "Data stream resumed.")

        self._history.add(
            values=frame.bands,
            calibration_done=frame.calibration_done,
            band_states=frame.band_states,
            crc_ok=frame.crc_ok,
        )
        self._history_dirty = True

        if frame.bands is not None:
            for tile, value in zip(self.tiles, frame.bands):
                tile.set_value(value)
        for tile, active in zip(self.tiles, frame.band_states):
            tile.set_state(active)

        set_dynamic_property(self.calib_badge, "done", "true" if frame.calibration_done else "false")
        self.calib_badge.setText("CALIBRATION DONE" if frame.calibration_done else "CALIBRATION \u2014")

        if frame.calibration_done and self._controller.calibrating:
            self._controller.set_calibrating(False)
            self._log("success", "Calibration completed successfully.")

    def _on_stats(self, counters: dict) -> None:
        self._totals["ok"] += counters.get("ok", 0)
        self._totals["crc"] += counters.get("crc", 0)
        self._totals["format"] += counters.get("format", 0)
        self.stats_label.setText(
            f"RX {counters.get('ok', 0)}/s   \u00b7   CRC err {self._totals['crc']}   "
            f"\u00b7   Format err {self._totals['format']}"
        )
        if counters.get("crc", 0):
            self._log("error", f"{counters['crc']} frame(s)/s failed CRC (check CRC algorithm).")
        if counters.get("format", 0):
            self._log("warning", f"{counters['format']} malformed frame(s)/s discarded.")

    def _refresh_history(self) -> None:
        if not self._history_dirty:
            return
        self._history_dirty = False
        self.history_model.set_records(self._history.records())
        self.history_info.setText(
            f"{len(self._history)} / {self._history.capacity} records (newest first)"
        )

    def _clear_history(self) -> None:
        self._history.clear()
        self.history_model.set_records([])
        self.history_info.setText(f"0 / {self._history.capacity} records (newest first)")
        self._log("info", "History cleared.")

    def _check_data_flow(self) -> None:
        if not self._controller.connected:
            return
        if self._last_frame_time is None:
            age_text = "waiting for data"
        else:
            age = time.monotonic() - self._last_frame_time
            age_text = f"last frame {age:.1f} s ago"
            if age > DATA_TIMEOUT_S and not self._data_timeout_warned:
                self._data_timeout_warned = True
                self._log("warning", f"No data received for {age:.0f} s \u2014 board may have stopped sending.")
        self.data_age_label.setText(age_text)

    # ------------------------------------------------------------------ #
    # Control state / status
    # ------------------------------------------------------------------ #
    def _update_controls(self) -> None:
        controller = self._controller

        self.connect_btn.setText("Disconnect" if controller.can_disconnect() else "Connect")
        self.connect_btn.setEnabled(controller.can_connect() or controller.can_disconnect())

        self.start_btn.setEnabled(controller.can_start())
        self.stop_btn.setEnabled(controller.can_stop())
        self.calibrate_btn.setEnabled(controller.can_calibrate())

        editable = not (controller.connected or controller.connecting)
        for widget in (
            self.port_combo,
            self.refresh_btn,
            self.baud_combo,
            self.crc_combo,
            self.verify_check,
            self.byteorder_combo,
        ):
            widget.setEnabled(editable)

        if controller.calibrating:
            state = "Calibrating\u2026"
        elif controller.running:
            state = "Running"
        elif controller.connected:
            state = "Idle"
        elif controller.connecting:
            state = "Connecting\u2026"
        else:
            state = "Idle"
        self.state_label.setText(state)

    def _set_status(self, state: str, text: str) -> None:
        self.status_pill.setText(text)
        set_dynamic_property(self.status_pill, "state", state)

    # ------------------------------------------------------------------ #
    # Logging
    # ------------------------------------------------------------------ #
    _LOG_COLORS = {
        "info": "#9db0cc",
        "success": "#57d98a",
        "warning": "#f5b942",
        "error": "#ff7b88",
        "tx": "#5aa9ff",
    }

    def _log(self, level: str, message: str) -> None:
        now = _dt.datetime.now()
        timestamp = now.strftime("%H:%M:%S.") + f"{now.microsecond // 1000:03d}"
        color = self._LOG_COLORS.get(level, "#c8d3e6")
        tag = {"tx": "TX", "info": "INFO", "success": "OK", "warning": "WARN", "error": "ERR"}.get(level, "LOG")
        safe = (
            message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )
        self.log_view.appendHtml(
            f'<span style="color:#66748c">{timestamp}</span> '
            f'<span style="color:{color};font-weight:600">[{tag}]</span> '
            f'<span style="color:#c8d3e6">{safe}</span>'
        )

    # ------------------------------------------------------------------ #
    # Shutdown
    # ------------------------------------------------------------------ #
    def closeEvent(self, event) -> None:  # noqa: N802
        if self._worker is not None:
            self._worker.stop()
            self._worker.wait(1500)
            self._worker = None
        super().closeEvent(event)
