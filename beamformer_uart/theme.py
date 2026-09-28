"""Application theme (Qt style sheet).

A single dark, modern theme with card surfaces, rounded corners and clear
status colours.  Kept separate from the UI code so it can be tuned without
touching behaviour.
"""

from __future__ import annotations

# Palette ------------------------------------------------------------------- #
BG = "#0e1420"
CARD = "#161e2c"
CARD_ALT = "#1d2738"
BORDER = "#2a3546"
TEXT = "#e7edf7"
MUTED = "#8b97ad"
PRIMARY = "#4f8cff"
PRIMARY_HOVER = "#6ba0ff"
SUCCESS = "#2ecc71"
DANGER = "#ff5c6c"
DANGER_HOVER = "#ff7b88"
WARNING = "#f5a623"
INFO = "#22d3ee"


def stylesheet() -> str:
    """Return the global Qt style sheet."""
    return f"""
    QWidget {{
        background-color: {BG};
        color: {TEXT};
        font-family: "Segoe UI", "Inter", "Roboto", Arial, sans-serif;
        font-size: 13px;
    }}

    QMainWindow, QScrollArea, QWidget#centralRoot {{ background-color: {BG}; }}

    /* ---------- Cards ---------- */
    QFrame#card {{
        background-color: {CARD};
        border: 1px solid {BORDER};
        border-radius: 14px;
    }}
    QLabel#cardTitle {{
        font-size: 15px;
        font-weight: 600;
        color: {TEXT};
        background: transparent;
    }}
    QLabel#mutedLabel {{ color: {MUTED}; background: transparent; }}
    QLabel#fieldLabel {{ color: {MUTED}; background: transparent; }}

    /* ---------- Header ---------- */
    QFrame#header {{
        background-color: {CARD};
        border: 1px solid {BORDER};
        border-radius: 14px;
    }}
    QLabel#appTitle {{
        font-size: 22px;
        font-weight: 700;
        color: {TEXT};
        background: transparent;
    }}
    QLabel#appSubtitle {{ color: {MUTED}; font-size: 12px; background: transparent; }}

    /* ---------- Status pill ---------- */
    QLabel#statusPill {{
        border-radius: 13px;
        padding: 5px 14px;
        font-weight: 600;
        font-size: 12px;
        border: 1px solid {BORDER};
        background-color: {CARD_ALT};
        color: {MUTED};
    }}
    QLabel#statusPill[state="connecting"] {{
        color: {WARNING}; border-color: {WARNING}; background-color: rgba(245,166,35,0.12);
    }}
    QLabel#statusPill[state="connected"] {{
        color: {SUCCESS}; border-color: {SUCCESS}; background-color: rgba(46,204,113,0.12);
    }}
    QLabel#statusPill[state="error"] {{
        color: {DANGER}; border-color: {DANGER}; background-color: rgba(255,92,108,0.12);
    }}

    /* ---------- Buttons ---------- */
    QPushButton {{
        background-color: {CARD_ALT};
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: 9px;
        padding: 8px 14px;
        font-weight: 600;
    }}
    QPushButton:hover {{ background-color: #263349; border-color: {PRIMARY}; }}
    QPushButton:pressed {{ background-color: #1a2434; }}
    QPushButton:disabled {{ color: #5b6577; border-color: #232d3d; background-color: #141b27; }}

    QPushButton#primaryButton {{ background-color: {PRIMARY}; border-color: {PRIMARY}; color: #ffffff; }}
    QPushButton#primaryButton:hover {{ background-color: {PRIMARY_HOVER}; border-color: {PRIMARY_HOVER}; }}
    QPushButton#primaryButton:disabled {{ background-color: #2a3852; border-color: #2a3852; color: #6f7d94; }}

    QPushButton#successButton {{ background-color: {SUCCESS}; border-color: {SUCCESS}; color: #062315; }}
    QPushButton#successButton:hover {{ background-color: #4bdc8d; border-color: #4bdc8d; }}
    QPushButton#successButton:disabled {{ background-color: #23402f; border-color: #23402f; color: #5c7a68; }}

    QPushButton#dangerButton {{ background-color: {DANGER}; border-color: {DANGER}; color: #2a060b; }}
    QPushButton#dangerButton:hover {{ background-color: {DANGER_HOVER}; border-color: {DANGER_HOVER}; }}
    QPushButton#dangerButton:disabled {{ background-color: #40232a; border-color: #40232a; color: #7a5c63; }}

    QPushButton#warningButton {{ background-color: {WARNING}; border-color: {WARNING}; color: #2a1c02; }}
    QPushButton#warningButton:hover {{ background-color: #ffb945; border-color: #ffb945; }}
    QPushButton#warningButton:disabled {{ background-color: #3f3520; border-color: #3f3520; color: #7d715a; }}

    QPushButton#ghostButton {{ background-color: transparent; }}

    QPushButton#commandButton {{
        font-size: 15px;
        padding: 14px 18px;
        border-radius: 11px;
    }}

    /* ---------- Inputs ---------- */
    QComboBox, QLineEdit, QSpinBox {{
        background-color: {CARD_ALT};
        border: 1px solid {BORDER};
        border-radius: 8px;
        padding: 6px 10px;
        min-height: 20px;
        color: {TEXT};
    }}
    QComboBox:hover, QLineEdit:hover {{ border-color: {PRIMARY}; }}
    QComboBox:disabled, QLineEdit:disabled {{ color: #5b6577; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{
        background-color: {CARD_ALT};
        border: 1px solid {BORDER};
        selection-background-color: {PRIMARY};
        selection-color: #ffffff;
        outline: none;
    }}

    QCheckBox {{ spacing: 8px; background: transparent; }}
    QCheckBox::indicator {{
        width: 16px; height: 16px; border-radius: 4px;
        border: 1px solid {BORDER}; background-color: {CARD_ALT};
    }}
    QCheckBox::indicator:checked {{ background-color: {PRIMARY}; border-color: {PRIMARY}; }}

    /* ---------- Latest value tiles ---------- */
    QFrame#valueTile {{
        background-color: {CARD_ALT};
        border: 1px solid {BORDER};
        border-radius: 12px;
    }}
    QLabel#channelName {{
        color: {MUTED};
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 1px;
        background: transparent;
    }}
    QLabel#valueBig {{
        color: {TEXT};
        font-family: "Cascadia Mono", "Consolas", "DejaVu Sans Mono", monospace;
        font-size: 24px;
        font-weight: 700;
        background: transparent;
    }}
    QLabel#bandState {{ color: {MUTED}; font-size: 10px; background: transparent; }}
    QLabel#bandState[on="true"] {{ color: {SUCCESS}; }}

    QLabel#calibBadge {{
        border-radius: 11px; padding: 3px 12px; font-size: 11px; font-weight: 700;
        border: 1px solid {BORDER}; color: {MUTED}; background-color: {CARD_ALT};
    }}
    QLabel#calibBadge[done="true"] {{ color: {SUCCESS}; border-color: {SUCCESS}; background-color: rgba(46,204,113,0.12); }}

    /* ---------- Tables ---------- */
    QTableView {{
        background-color: {CARD};
        alternate-background-color: #131b28;
        gridline-color: {BORDER};
        border: 1px solid {BORDER};
        border-radius: 10px;
        selection-background-color: {PRIMARY};
        selection-color: #ffffff;
        outline: none;
    }}
    QHeaderView::section {{
        background-color: {CARD_ALT};
        color: {MUTED};
        padding: 7px 8px;
        border: none;
        border-right: 1px solid {BORDER};
        border-bottom: 1px solid {BORDER};
        font-weight: 700;
    }}
    QTableCornerButton::section {{ background-color: {CARD_ALT}; border: none; }}

    /* ---------- Log ---------- */
    QPlainTextEdit#logView {{
        background-color: #0b111b;
        border: 1px solid {BORDER};
        border-radius: 10px;
        color: #c8d3e6;
        font-family: "Cascadia Mono", "Consolas", "DejaVu Sans Mono", monospace;
        font-size: 12px;
        padding: 8px;
    }}

    /* ---------- Scrollbars ---------- */
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 24px; }}
    QScrollBar::handle:vertical:hover {{ background: #3a4860; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {BORDER}; border-radius: 5px; min-width: 24px; }}

    QSplitter::handle {{ background-color: {BG}; }}
    QToolTip {{
        background-color: {CARD_ALT}; color: {TEXT}; border: 1px solid {BORDER};
        padding: 4px; border-radius: 6px;
    }}
    """
