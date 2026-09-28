"""Output data model and history.

The board streams ``Band1..Band6 Output`` values (the "6 x 1 output matrix").
This module keeps the latest snapshot plus the previous 100 snapshots
(101 records total) and exposes them to Qt through a table model.
"""

from __future__ import annotations

import datetime as _dt
from collections import deque
from dataclasses import dataclass
from math import isfinite
from typing import Deque, Iterable, List, Optional, Sequence

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor, QFont

MAX_RECORDS = 101          # newest record + 100 previous
NUM_BANDS = 6


def format_value(value: Optional[float]) -> str:
    """Format a band output for display in a compact, readable way."""
    if value is None:
        return "\u2014"      # em dash
    if not isfinite(value):
        return "NaN" if value != value else ("+inf" if value > 0 else "-inf")
    magnitude = abs(value)
    if magnitude != 0 and (magnitude >= 1e6 or magnitude < 1e-3):
        return f"{value:.4e}"
    return f"{value:.4f}"


@dataclass
class OutputSnapshot:
    """One received output frame."""

    counter: int
    timestamp: _dt.datetime
    values: Sequence[Optional[float]]
    calibration_done: bool = False
    band_states: Sequence[bool] = (False,) * NUM_BANDS
    crc_ok: bool = True


class HistoryManager:
    """Keeps the latest snapshot plus the previous 100 (newest first).

    ``deque(maxlen=MAX_RECORDS)`` automatically evicts the oldest record once
    the buffer is full, which satisfies the "latest + 100 previous" rule.
    """

    def __init__(self, max_records: int = MAX_RECORDS) -> None:
        self._records: Deque[OutputSnapshot] = deque(maxlen=max_records)
        self._counter = 0
        self._last_bands: List[Optional[float]] = [None] * NUM_BANDS

    @property
    def capacity(self) -> int:
        return self._records.maxlen or MAX_RECORDS

    def __len__(self) -> int:
        return len(self._records)

    def clear(self) -> None:
        self._records.clear()
        self._last_bands = [None] * NUM_BANDS

    @property
    def latest(self) -> Optional[OutputSnapshot]:
        return self._records[0] if self._records else None

    @property
    def last_values(self) -> Sequence[Optional[float]]:
        return tuple(self._last_bands)

    def records(self) -> List[OutputSnapshot]:
        return list(self._records)

    def add(
        self,
        values: Optional[Sequence[Optional[float]]] = None,
        calibration_done: bool = False,
        band_states: Sequence[bool] = (False,) * NUM_BANDS,
        crc_ok: bool = True,
        timestamp: Optional[_dt.datetime] = None,
    ) -> OutputSnapshot:
        """Append a new snapshot at the front of the history.

        ``values`` may contain ``None`` for bands missing from a frame; the
        last known value for that band is carried forward so the table stays
        readable.
        """
        if values is not None:
            for i, value in enumerate(values):
                if value is not None:
                    self._last_bands[i] = value

        self._counter += 1
        snapshot = OutputSnapshot(
            counter=self._counter,
            timestamp=timestamp or _dt.datetime.now(),
            values=tuple(self._last_bands),
            calibration_done=calibration_done,
            band_states=tuple(band_states),
            crc_ok=crc_ok,
        )
        self._records.appendleft(snapshot)
        return snapshot


class HistoryTableModel(QAbstractTableModel):
    """Read-only table model: #, Time, CH1..CH6 (newest first)."""

    HEADERS = ["#", "Time", "CH1", "CH2", "CH3", "CH4", "CH5", "CH6"]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._records: List[OutputSnapshot] = []
        self._highlight = QColor(31, 62, 108)
        self._highlight_text = QColor(180, 220, 255)
        self._bold = QFont()
        self._bold.setBold(True)

    def set_records(self, records: Iterable[OutputSnapshot]) -> None:
        self.beginResetModel()
        self._records = list(records)
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._records)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.HEADERS)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._records)):
            return None
        record = self._records[index.row()]
        column = index.column()

        if role == Qt.DisplayRole:
            if column == 0:
                return str(record.counter)
            if column == 1:
                return record.timestamp.strftime("%H:%M:%S.") + f"{record.timestamp.microsecond // 1000:03d}"
            return format_value(record.values[column - 2])
        if role == Qt.TextAlignmentRole:
            return int(Qt.AlignCenter)
        if role == Qt.FontRole and index.row() == 0:
            return self._bold
        if role == Qt.BackgroundRole and index.row() == 0:
            return self._highlight
        if role == Qt.ForegroundRole and index.row() == 0:
            return self._highlight_text
        return None

    def headerData(self, section: int, orientation, role: int = Qt.DisplayRole):  # noqa: N802
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            if 0 <= section < len(self.HEADERS):
                return self.HEADERS[section]
        return None
