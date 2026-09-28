"""Beamformer UART Console.

A standalone PySide6 desktop application that talks to the beamformer board
over a serial (UART / RS422) link instead of UDP.

The board protocol is recovered from ``Document.pdf``; see
:mod:`beamformer_uart.protocol` for the wire format.
"""

__version__ = "1.0.0"
