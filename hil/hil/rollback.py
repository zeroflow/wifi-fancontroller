"""The OTA rollback state of every OTA boot, read from its own log window (REG-05, D-39, D-41).

ESPHome 2026.10.1's safe_mode dump_config prints `Bootloader rollback: not supported` when the running
image's OTA state is NEW, `supported` when it is PENDING_VERIFY (an EN reset before the mark would roll
back), and `support unknown` for anything else (valid, undefined). After a rollback the restored image
prints `OTA rollback detected! Rolled back from partition '...'`.

Each OTA's window runs from its end mark to the start of the next upload or the next Bootloader press
(Dut.ota_windows), so a later boot's line is never attributed to it. The line is read from UART0; the
release-to-commit upgrade runs under the release bootloader, which leaves UART0 dark (03-11), so that
one OTA is read from its API-log window instead and recorded as unobservable when the line is not there.
The broken image has no safe_mode and prints no rollback line; its row carries the image's own OTA state
(`HIL broken image OTA state:`, 03-05), which settles D-41. Pure functions, no waits: nothing here adds
time to an OTA.
"""

import json
import re

from . import bootlog, config, recovery

ROLLBACK_STATE_RE = re.compile(r"Bootloader rollback: (supported|not supported|support unknown)")
ROLLBACK_DONE_RE = re.compile(r"OTA rollback detected")
ROLLBACK_LINE_S = 20  # the most a test waits for the state line after an OTA's boot (test_15)
STATES_REPORT = "rollback-states.json"
TEST_REPORT = "rollback-dut-a.json"
SOURCE_UART = "uart0"
SOURCE_API = "api"
SOURCE_UNOBSERVABLE = "unobservable (release bootloader)"


def state_in(text):
    """The state of the first `Bootloader rollback:` line in `text`, or None without one."""
    if not text:
        return None
    found = ROLLBACK_STATE_RE.search(bootlog.strip_ansi(text))
    return found.group(1) if found else None


def rolled_back(text):
    """True only when `text` holds an `OTA rollback detected` line."""
    return bool(text) and ROLLBACK_DONE_RE.search(bootlog.strip_ansi(text)) is not None


def rows(windows, uart_window, api_window=None):
    """One row per OTA window, in order: label, role, ok, state, source, image_state, old_uptime_s, rolled_back.

    `uart_window(entry)` and `api_window(entry)` return the window's text or None (no end mark, no log).
    An OTA whose reboot was proven by the build ID (reboot_proof "build id": the plaintext upgrade under
    the release bootloader) is read from the API window, and its source is SOURCE_UNOBSERVABLE when the
    line is not there either. image_state is set for the broken role only (D-41), None for every other.
    """
    found = []
    for entry in windows:
        uart = uart_window(entry)
        state, source = state_in(uart), SOURCE_UART
        if entry.get("reboot_proof") == "build id":
            api = api_window(entry) if api_window is not None else None
            state = state_in(api)
            source = SOURCE_API if state is not None else SOURCE_UNOBSERVABLE
        found.append(
            {
                "label": entry.get("label"),
                "role": entry.get("role"),
                "ok": entry.get("ok"),
                "state": state,
                "source": source,
                "image_state": recovery.ota_state_in(uart or "") if entry.get("role") == "broken" else None,
                "old_uptime_s": entry.get("old_uptime_s"),
                "rolled_back": rolled_back(uart),
            }
        )
    return found


def write_states(found):
    """reports/rollback-states.json: the rows of rows()."""
    reports = config.reports_dir()
    reports.mkdir(parents=True, exist_ok=True)
    (reports / STATES_REPORT).write_text(json.dumps(found, indent=2, sort_keys=True) + "\n", encoding="utf-8")
