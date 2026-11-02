"""Boot-log gate parsing, on synthetic text only."""

import re
from pathlib import Path

import pytest

from hil import bootlog

ESC = "\x1b"


def test_ansi_coloured_error_line_is_found():
    text = "%s[0;31m[E][rmt:123]: synthetic failure%s[0m\r\n" % (ESC, ESC)
    assert bootlog.error_lines(text) == ["[E][rmt:123]: synthetic failure"]


def test_warning_and_debug_lines_are_ignored():
    text = (
        "%s[0;33m[W][wifi:45]: synthetic warning%s[0m\r\n"
        "%s[0;36m[D][sensor:7]: synthetic debug%s[0m\r\n"
        "%s[0;32m[I][app:1]: synthetic info%s[0m\r\n" % (ESC, ESC, ESC, ESC, ESC, ESC)
    )
    assert bootlog.error_lines(text) == []


def test_second_stage_bootloader_error_is_found():
    text = "E (123) boot: synthetic bootloader failure\r\nI (130) boot: fine\r\n"
    assert bootlog.error_lines(text) == ["E (123) boot: synthetic bootloader failure"]


def test_boot_banner_found_for_s2_normal_boot():
    text = "ESP-ROM:esp32s2-rc4-20191025\r\nrst:0x1 (POWERON),boot:0x8 (SPI_FAST_FLASH_BOOT)\r\n"
    assert bootlog.has_boot_banner(text, "esp32s2")


def test_boot_banner_found_for_c6_normal_boot():
    assert bootlog.has_boot_banner("rst:0x1 (POWERON),boot:0x6f (SPI_FAST_FLASH_BOOT)\r\n", "esp32c6")


def test_download_mode_is_not_a_normal_boot_banner():
    assert not bootlog.has_boot_banner("rst:0x1 (POWERON),boot:0x0 (DOWNLOAD(USB/UART0))\r\n", "esp32s2")


def test_empty_text_has_no_banner_and_no_error_lines():
    assert bootlog.error_lines("") == []
    assert not bootlog.has_boot_banner("", "esp32s2")


def test_carriage_return_only_line_endings_split_correctly():
    text = "[I][app:1]: one\r[E][x:2]: two\r[I][app:3]: three\r"
    assert bootlog.lines(text) == ["[I][app:1]: one", "[E][x:2]: two", "[I][app:3]: three"]
    assert bootlog.error_lines(text) == ["[E][x:2]: two"]


def test_unknown_chip_is_a_rig_error():
    import pytest

    from hil import RigError

    with pytest.raises(RigError):
        bootlog.has_boot_banner("boot:0x8", "esp32")


def test_idf_error_forwarded_through_esphome_debug_log_is_found():
    text = (
        "%s[0;36m[D][esp-idf:000]: E (641) rmt: synthetic: no free tx channels%s[0m\r\n"
        "%s[0;36m[D][esp-idf:000]: I (642) rmt: synthetic info%s[0m\r\n" % (ESC, ESC, ESC, ESC)
    )
    assert bootlog.error_lines(text) == ["[D][esp-idf:000]: E (641) rmt: synthetic: no free tx channels"]


def test_debug_line_that_merely_mentions_an_error_is_not_an_error_line():
    assert bootlog.error_lines("[D][app:1]: the E (1) marker appears mid-line only\r\n") == []


# ROM download mode, ESPHome safe mode and the boot-confirmation line (HARN-03, HARN-12).
# The strings are the ones in the pinned ESPHome 2026.10.1 safe_mode component (safe_mode.cpp).

DOWNLOAD_S2 = "ESP-ROM:esp32s2-rc4-20191025\r\nrst:0x1 (POWERON),boot:0x0 (DOWNLOAD(USB/UART0))\r\nwaiting for download\r\n"
ACTIVE = "%s[0;33m[W][safe_mode:248]: SAFE MODE IS ACTIVE%s[0m\r\n" % (ESC, ESC)
LOOP = "%s[1;31m[E][safe_mode:213]: Boot loop detected%s[0m\r\n" % (ESC, ESC)
BOOT_OK = "%s[0;32m[I][safe_mode:154]: Boot seems successful; resetting boot loop counter%s[0m\r\n" % (ESC, ESC)


def test_download_banner_found_for_s2_and_not_the_normal_boot_code():
    assert bootlog.has_download_banner(DOWNLOAD_S2, "esp32s2")
    assert not bootlog.has_download_banner("rst:0x1 (POWERON),boot:0x8 (SPI_FAST_FLASH_BOOT)\r\n", "esp32s2")


def test_download_banner_found_for_c6_with_its_own_code():
    assert bootlog.has_download_banner("rst:0x1 (POWERON),boot:0x67 (DOWNLOAD(USB/UART0))\r\n", "esp32c6")
    assert not bootlog.has_download_banner("boot:0x0 (DOWNLOAD(USB/UART0))\r\n", "esp32c6")


def test_download_code_is_not_matched_inside_a_longer_hex_code():
    assert not bootlog.has_download_banner("boot:0x0f (SOMETHING)\r\n", "esp32s2")
    assert not bootlog.has_download_banner("boot:0x670 (SOMETHING)\r\n", "esp32c6")


def test_download_banner_regex_serves_wait_for_and_an_unknown_chip_is_a_rig_error():
    import re

    import pytest

    from hil import RigError

    assert re.search(bootlog.download_banner_regex("esp32s2"), DOWNLOAD_S2)
    with pytest.raises(RigError, match="download-mode"):
        bootlog.download_banner_regex("esp32")
    with pytest.raises(RigError, match="boot code"):
        bootlog.has_boot_banner("", "esp32")


def test_safe_mode_lines_match_the_coloured_pinned_source_lines_and_come_back_stripped():
    text = "[I][app:1]: fine\r\n" + ACTIVE + LOOP
    assert bootlog.safe_mode_lines(text) == [
        "[W][safe_mode:248]: SAFE MODE IS ACTIVE",
        "[E][safe_mode:213]: Boot loop detected",
    ]


def test_an_ordinary_warning_and_the_restart_announcement_are_not_safe_mode():
    text = (
        "%s[0;33m[W][wifi:45]: synthetic warning%s[0m\r\n"
        "[I][safe_mode.button:12]: Restarting in safe mode\r\n"
        "[W][safe_mode:99]: Last reset too quick; invoke in 3 restarts\r\n"
        "[I][safe_mode:60]: Safe Mode:\r\n" % (ESC, ESC)
    )
    assert bootlog.safe_mode_lines(text) == []
    assert not bootlog.SAFE_MODE_RE.search("Restarting in safe mode")


def test_boot_ok_matches_the_pinned_string_only():
    assert bootlog.BOOT_OK_RE.search(BOOT_OK)
    assert not bootlog.BOOT_OK_RE.search("[I][safe_mode:1]: Boot seems fine\r\n")


# D-14 amendment: one narrow, expiring exception for the ESPHome 2026.10.1 task_wdt line.

WDT = "E (4321) task_wdt: esp_task_wdt_reset(707): task not found"
PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def test_no_error_lines_pass_with_nothing_allowlisted():
    assert bootlog.classify_errors("%s[0;32m[I][app:1]: fine%s[0m\r\n" % (ESC, ESC)) == ([], [])


def test_one_task_wdt_line_is_allowed_and_reported_not_dropped():
    failures, allowed = bootlog.classify_errors("I (1) boot: fine\r\n" + WDT + "\r\n")
    assert failures == [] and allowed == [WDT]


def test_one_task_wdt_line_with_ansi_and_another_number_is_allowed():
    text = "%s[0;31mE (99999) task_wdt: esp_task_wdt_reset(707): task not found%s[0m\r\n" % (ESC, ESC)
    failures, allowed = bootlog.classify_errors(text)
    assert failures == [] and len(allowed) == 1


def test_a_second_task_wdt_line_in_the_window_fails_both():
    failures, allowed = bootlog.classify_errors(WDT + "\r\n" + WDT.replace("4321", "9876") + "\r\n")
    assert allowed == [] and len(failures) == 2


def test_the_allowlist_does_not_hide_other_errors_in_the_same_window():
    other = "[E][synthetic:9]: first"
    failures, allowed = bootlog.classify_errors(WDT + "\r\n" + other + "\r\n")
    assert failures == [other] and allowed == [WDT]


@pytest.mark.parametrize(
    "line",
    [
        "E (4321) task_wdt: esp_task_wdt_reset(708): task not found",
        "E (4321) task_wdt: esp_task_wdt_reset(707): task not found!",
        "E (4321) task_wdt: Task watchdog got triggered. The following tasks did not reset the watchdog in time:",
        "E (4321) task_wdt: esp_task_wdt_add(1): task not found",
        "E (4321) other: esp_task_wdt_reset(707): task not found",
        "[D][esp-idf:000]: E (4321) task_wdt: esp_task_wdt_reset(707): task not found",
        "[E][task_wdt:12]: esp_task_wdt_reset(707): task not found",
        "E (4321) boot: synthetic bootloader failure",
    ],
)
def test_a_near_miss_still_fails(line):
    failures, allowed = bootlog.classify_errors(line + "\r\n")
    assert failures == [line] and allowed == []


def test_each_allowlist_entry_is_narrow_and_names_its_pin():
    assert bootlog.ALLOWED_ERRORS
    for entry in bootlog.ALLOWED_ERRORS:
        assert entry["regex"].pattern.startswith("^") and entry["regex"].pattern.endswith("$")
        assert entry["max_per_boot"] == 1
        assert entry["valid_for_esphome"] and entry["reason"]


def test_allowlist_does_not_outlive_its_esphome_pin():
    """Fails when the esphome pin in pyproject.toml moves while an entry still names the old release.

    On failure: check whether the new ESPHome release fixes http_read_fully's unguarded App.feed_wdt()
    (esp_task_wdt_status(nullptr) == ESP_OK); if it does, delete the ALLOWED_ERRORS entry, otherwise
    update valid_for_esphome after confirming the line still occurs.
    """
    pins = re.findall(r'"esphome==([^"]+)"', PYPROJECT.read_text(encoding="utf-8"))
    assert pins, "no esphome pin found in pyproject.toml"
    pin = pins[0]
    stale = [e["valid_for_esphome"] for e in bootlog.ALLOWED_ERRORS if e["valid_for_esphome"] != pin]
    assert not stale, (
        "ESPHome pin is %s but bootlog.ALLOWED_ERRORS still carries entries for %s: "
        "remove them or re-justify them (D-14 amendment expiry)" % (pin, stale)
    )
