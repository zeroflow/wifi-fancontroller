"""UART0 boot-log parsing for the red/green gate (D-14: no allowlist).

The log carries ANSI colour codes, ends its lines with a bare carriage return
and starts with binary ROM bytes, so everything here works on decoded text.
"""

import re

from . import RigError

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
ESPHOME_ERROR_RE = re.compile(r"^\[E\]\[[^\]]+:\d+\]")
BOOTLOADER_ERROR_RE = re.compile(r"^E \(\d+\) ")
# ESP-IDF errors reach UART0 wrapped by ESPHome's logger, at its own level (D on Rev 3.2):
# `[D][esp-idf:000]: E (641) rmt: ...`. The wrapper level hides the severity, so look inside.
IDF_FORWARDED_ERROR_RE = re.compile(r"^\[[A-Z]\]\[esp-idf:\d+\]: E \(\d+\) ")
# ROM normal-boot codes from the hil-rig README table.
NORMAL_BOOT = {"esp32s2": "boot:0x8", "esp32c6": "boot:0x6f"}


def strip_ansi(text):
    return ANSI_RE.sub("", text)


def lines(text):
    """Split on carriage return and newline; drop empty lines."""
    return [line for line in re.split(r"[\r\n]+", strip_ansi(text)) if line.strip()]


def error_lines(text):
    """ESPHome `[E][component:line]` lines, bootloader `E (n) ` lines and ESP-IDF `E (n)` lines
    forwarded through ESPHome's logger, ANSI stripped, verbatim."""
    found = []
    for line in lines(text):
        stripped = line.lstrip()
        if (
            ESPHOME_ERROR_RE.match(stripped)
            or BOOTLOADER_ERROR_RE.match(stripped)
            or IDF_FORWARDED_ERROR_RE.match(stripped)
        ):
            found.append(stripped.rstrip())
    return found


def has_boot_banner(text, chip):
    """True when the ROM printed the normal-boot code for this chip."""
    try:
        code = NORMAL_BOOT[chip]
    except KeyError:
        raise RigError("no ROM boot code known for chip '%s'" % chip) from None
    return re.search(re.escape(code) + r"(?![0-9a-fA-F])", strip_ansi(text)) is not None
