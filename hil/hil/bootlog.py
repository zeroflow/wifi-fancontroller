"""UART0 boot-log parsing for the red/green gate (D-14: no allowlist, one expiring exception, see ALLOWED_ERRORS).

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
# D-14 amendment (2026-11-02): the one narrow, expiring exception to "no allowlist".
# ESPHome 2026.10.1's http_request update task (HttpRequestUpdate::update_task -> http_read_fully ->
# App.feed_wdt() -> esp_task_wdt_reset()) feeds the task watchdog from a task that is not subscribed to
# it, so ESP-IDF prints this line on roughly 2 boots in 87 on DUT A. HttpContainerIDF::feed_wdt() guards
# the same call with esp_task_wdt_status(nullptr) == ESP_OK; http_read_fully does not. It is an upstream
# bug, harmless at runtime, and not something the HIL firmware can avoid without changing the product.
# EXPIRY: remove this entry when the ESPHome pin moves past 2026.10.1 to a release with the fix.
# test_bootlog.test_allowlist_does_not_outlive_its_esphome_pin fails the moment the pin changes while
# the entry exists, so it cannot outlive the pin silently.
ALLOWED_ERRORS = (
    {
        "regex": re.compile(r"^E \(\d+\) task_wdt: esp_task_wdt_reset\(707\): task not found$"),
        "max_per_boot": 1,
        "valid_for_esphome": "2026.10.1",
        "reason": "ESPHome 2026.10.1 http_request update task feeds the TWDT without being subscribed (upstream bug)",
    },
)
# ROM normal-boot codes from the hil-rig README table.
NORMAL_BOOT = {"esp32s2": "boot:0x8", "esp32c6": "boot:0x6f"}
# ROM download-mode codes from the same table: what the chip prints after the Bootloader button.
DOWNLOAD_BOOT = {"esp32s2": "boot:0x0", "esp32c6": "boot:0x67"}
# ESPHome safe_mode (pinned 2026.10.1, components/safe_mode/safe_mode.cpp). SAFE MODE IS ACTIVE (W)
# is logged once safe mode is up, whether it was entered by the safe mode button ("Manual mode", I)
# or by a boot loop (which also logs "Boot loop detected", E). The line "Restarting in safe mode"
# is the running image announcing the reboot and is deliberately NOT a match: the DUT is not in
# safe mode yet.
SAFE_MODE_RE = re.compile(r"SAFE MODE IS ACTIVE|Boot loop detected")
# The running image marks itself good after boot_is_good_after (I), which also confirms an OTA image.
BOOT_OK_RE = re.compile(r"Boot seems successful; resetting boot loop counter")


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


def classify_errors(text):
    """Split error_lines(text) into (failures, allowed) for one boot window.

    A line matching an ALLOWED_ERRORS entry is allowed only while the entry has at most `max_per_boot`
    matches in the window; one more and every match of that entry is a failure, so a repeating line
    cannot hide behind the allowlist. Both lists keep log order; allowed lines are never dropped
    silently: callers must report them.
    """
    found = error_lines(text)
    allowed_idx = set()
    for entry in ALLOWED_ERRORS:
        hits = [i for i, line in enumerate(found) if entry["regex"].match(line)]
        if len(hits) <= entry["max_per_boot"]:
            allowed_idx.update(hits)
    failures = [line for i, line in enumerate(found) if i not in allowed_idx]
    allowed = [line for i, line in enumerate(found) if i in allowed_idx]
    return failures, allowed


def _banner_regex(table, kind, chip):
    try:
        code = table[chip]
    except KeyError:
        raise RigError("no ROM %s code known for chip '%s'" % (kind, chip)) from None
    return re.escape(code) + r"(?![0-9a-fA-F])"


def has_boot_banner(text, chip):
    """True when the ROM printed the normal-boot code for this chip."""
    return re.search(_banner_regex(NORMAL_BOOT, "boot", chip), strip_ansi(text)) is not None


def download_banner_regex(chip):
    """Regex (for SerialTap.wait_for) of the ROM download-mode code of this chip."""
    return _banner_regex(DOWNLOAD_BOOT, "download-mode", chip)


def has_download_banner(text, chip):
    """True when the ROM printed the download-mode code for this chip (the bootloader was entered)."""
    return re.search(download_banner_regex(chip), strip_ansi(text)) is not None


def safe_mode_lines(text):
    """Lines that say the DUT is in ESPHome safe mode, ANSI stripped, verbatim."""
    return [line.strip() for line in lines(text) if SAFE_MODE_RE.search(line)]


def check_boot_window(tap, since, until, chip, label):
    """Skeleton for the RED commit of 03-06 Task 2."""
    return [], []
