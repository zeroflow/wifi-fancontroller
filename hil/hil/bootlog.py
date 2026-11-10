"""UART0 boot-log parsing for the red/green gate (D-14: no allowlist, one expiring exception, see ALLOWED_ERRORS).

The log carries ANSI colour codes, ends its lines with a bare carriage return
and starts with binary ROM bytes, so everything here works on decoded text.
"""

import json
import re
import warnings

from . import RigError, config

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


def count_boot_banners(text, chip):
    """How many ROM normal-boot banners of this chip `text` holds (download banners and cut lines do not count)."""
    return len(re.findall(_banner_regex(NORMAL_BOOT, "boot", chip), strip_ansi(text)))


def download_banner_regex(chip):
    """Regex (for SerialTap.wait_for) of the ROM download-mode code of this chip."""
    return _banner_regex(DOWNLOAD_BOOT, "download-mode", chip)


def has_download_banner(text, chip):
    """True when the ROM printed the download-mode code for this chip (the bootloader was entered)."""
    return re.search(download_banner_regex(chip), strip_ansi(text)) is not None


def safe_mode_lines(text):
    """Lines that say the DUT is in ESPHome safe mode, ANSI stripped, verbatim."""
    return [line.strip() for line in lines(text) if SAFE_MODE_RE.search(line)]


ALLOWLISTED_REPORT = "allowlisted-errors.json"


def _report_allowed(allowed, label):
    """Print, warn and append every allowlisted line as "<label>: <line>" to reports/allowlisted-errors.json."""
    for line in allowed:
        message = "ALLOWLISTED boot-log line (D-14 amendment, expires with the ESPHome 2026.10.1 pin): %s" % line
        print("WARNING: " + message)
        warnings.warn(message, stacklevel=3)
    reports = config.reports_dir()
    reports.mkdir(parents=True, exist_ok=True)
    path = reports / ALLOWLISTED_REPORT
    try:
        lines = json.loads(path.read_text(encoding="utf-8"))["lines"]
        if not isinstance(lines, list):
            lines = []
    except (OSError, ValueError, KeyError, TypeError):
        lines = []
    lines.extend("%s: %s" % (label, line) for line in allowed)
    path.write_text(json.dumps({"lines": lines}, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def check_boot_window(tap, since, until, chip, label):
    """The D-14 gate (with the Amendment 4 exception) over the UART0 text between two tap marks.

    RigError when the tap lost the bridge or the window holds no ROM boot banner: a gate that cannot see
    the boot would pass vacuously. Otherwise returns (errors, allowed) from classify_errors. Every
    allowlisted line is printed as a WARNING, raised as a UserWarning and appended as "<label>: <line>" to
    reports/allowlisted-errors.json (created when missing), so the lines of several windows accumulate in
    one file that `hil run` deletes at its start. The caller decides what the error lines mean.
    """
    window = tap.text(since, until)
    if tap.closed:
        raise RigError("serial tap lost the bridge during the scan window; boot log gate would be vacuous (%s)" % label)
    if not has_boot_banner(window, chip):
        raise RigError("no ROM boot banner captured after reset; boot log gate would be vacuous (%s)" % label)
    errors, allowed = classify_errors(window)
    _report_allowed(allowed, label)
    return errors, allowed


def check_api_log(log_lines, label):
    """The same D-14 gate over DutLink API log lines (03-11, the upgrade under the release bootloader).

    While the release's bootloader is in flash UART0 shows no app line, so the upgraded boot is gated on
    its API log (DutLink.log_since). The lines must hold the image's `Boot seems successful`: without it
    the log is not that boot's and the gate would pass vacuously (RigError). Allowlisted lines are reported
    exactly as check_boot_window reports them. Returns (errors, allowed).
    """
    text = "\n".join(log_lines)
    if not BOOT_OK_RE.search(strip_ansi(text)):
        raise RigError("API log holds no 'Boot seems successful'; boot log gate would be vacuous (%s)" % label)
    errors, allowed = classify_errors(text)
    _report_allowed(allowed, label)
    return errors, allowed
