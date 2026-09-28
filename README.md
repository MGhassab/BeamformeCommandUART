# Beamformer UART Console

A modern, standalone PySide6 desktop application that controls the beamformer
board and reads its output over a **UART / RS422** serial link (replacing the
UDP-based `client1.0.3` application).

It can:

* send **START**, **STOP** and **START CALIBRATION** commands to the board,
* continuously receive the board's six band outputs (the "6 x 1 output matrix"),
* show the **latest output** prominently,
* keep the **latest + 100 previous** outputs (101 records) in a history table,
* display a timestamped **communication log**,
* configure **COM port** and **baud rate** (with automatic port detection).

---

## Protocol

The wire format is taken directly from `Document.pdf`; nothing was invented.

```
+------+------+-----+-----+-----+---------------+-----+-----+-------+-------+-----+
| SYN1 | SYN2 | STX | FT  | LEN |     DATA      | PAD | EOD | CRC H | CRC L | ETX |
| 0xAA | 0x55 | 0x7E| 0x00|  n  | n x 5 bytes   |0x00 |0x2A |  hi   |  lo   |0x81 |
+------+------+-----+-----+-----+---------------+-----+-----+-------+-------+-----+
```

* `LEN` is the number of 5-byte DATA records. Each record is `Index (1) + payload (4)`.
* **Commands (TX)** use one record: `Index = 0`, three reserved bytes, then a
  bitwise command byte.

  | bit | command |
  |-----|---------|
  | 0 | Start Calibration |
  | 1 | Start |
  | 2 | Stop |

* **Data (RX)** uses seven records: record 0 is a status record whose bitwise
  byte carries `Calibration Done` (bit 0) and `Band1..Band6 State` (bits 1..6);
  records 1..6 (`Index = 1..6`) carry `Band1..Band6 Output` as 4-byte IEEE-754
  floats, **most-significant byte first (big-endian)**.
* `CRC` covers `FT + LEN + DATA + PAD` and is sent high byte first. The document
  does not name the algorithm, so it is selectable (default `CRC-16/CCITT-FALSE`).

The six `Band Output` values are displayed as **CH1 .. CH6**.

### Configurable settings

| Setting | Options | Default |
|---------|---------|---------|
| Baud rate | 9600 … 921600 (editable) | 115200 |
| CRC | CRC-16/CCITT-FALSE, XMODEM, MODBUS, IBM (ARC), None | CCITT-FALSE |
| CRC verify | on / off | on |
| Float byte order | Big-endian (MSB first), Little-endian (LSB first) | Big-endian |

If the board uses a different CRC, switch the algorithm in the UART card (or
turn *Verify* off). CRC failures are counted and reported in the log.

---

## Project structure

```
UART/
  main.py                          # entry point
  requirements.txt
  beamformer_uart/
    __init__.py
    protocol.py                    # frame constants, build/parse, resync, command defs
    crc.py                         # pluggable CRC-16 implementations
    uart_manager.py                # QThread + pyserial worker (all serial I/O)
    data_model.py                  # HistoryManager (latest + 100) + Qt table model
    command_manager.py             # button/state rules
    theme.py                       # Qt style sheet (modern dark theme)
    main_window.py                 # GUI layout + wiring
    serial_simulator.py            # virtual board for testing without hardware
    selftest.py                    # protocol + GUI + serial loopback tests
```

The GUI never touches the serial port. All I/O runs on the `UartWorker` thread;
commands are queued to it, and received frames come back as Qt signals.
History is buffered and the table refreshes on a 100 ms timer, so high-rate
data cannot freeze the interface.

---

## Install & run

```powershell
pip install -r requirements.txt      # PySide6, pyserial
python main.py
```

1. Pick the COM port (auto-detected; use **↻** to rescan).
2. Choose the baud rate.
3. Press **Connect** (the status pill shows Disconnected / Connecting /
   Connected / Error).
4. Use **START**, **STOP**, **START CALIBRATION**. Buttons enable/disable
   according to the connection and run state.

---

## Testing without hardware

The bundled simulator lets you exercise the whole receive path. Using a
virtual serial pair such as [com0com](https://sourceforge.net/projects/com0com/)
(`COM4` ↔ `COM5`):

```powershell
# terminal 1 - virtual board on COM5
python -m beamformer_uart.serial_simulator --port COM5 --baud 115200 --rate 100

# terminal 2 - the app
python main.py        # connect to COM4
```

### Automated self test

```powershell
python -m beamformer_uart.selftest
```

Runs the protocol round-trip/CRC/resync test, an offscreen GUI construction
test and (if `COM4`/`COM5` exist) a full serial loopback test. Use
`--app-port`, `--sim-port`, `--baud`, `--crc`, `--byteorder` to match your
setup, or `--skip-loopback` to skip the serial part.

---

## Error handling

* Missing / busy / invalid COM port → connect failure reported, app keeps running.
* Cable unplugged mid-session → read error, clean disconnect, status pill `Error`.
* Invalid or corrupt frames → counted, dropped and resynchronised; never crash.
* Board stops sending → "no data" warning after 3 s.
* Wrong CRC algorithm → frames reported as CRC errors (switch algorithm or disable verify).

## Notes

* The board uses an **RS422** interface, which appears to Windows as a normal
  COM port (via a USB-to-RS422 adapter), so no special handling is required.
* Frames are transmitted 8-N-1 with no flow control.
* The board updates roughly every ~19.7 ms (≈50 Hz) according to `Document.pdf`.
