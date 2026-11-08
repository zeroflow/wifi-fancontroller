"""The D-14 boot-log gate (bootlog.check_boot_window), driven with fakes: a gate that cannot see a boot
is a rig error. The smoke test that called it is gone (D-36); the gate runs on the upgraded boot (test_11)
and the recovery boot (test_41)."""

import json

import pytest

from hil import RigError, bootlog

BANNER = "rst:0x1 (POWERON),boot:0x8 (SPI_FAST_FLASH_BOOT)\r\n"
BUILD_ID = "3.2+hil." + "a" * 12
WDT = "E (4321) task_wdt: esp_task_wdt_reset(707): task not found"


# ---- check_boot_window itself, and the accumulation across windows ---------------------------------


class WindowTap:
    """text(since, until) cut from named windows of one scripted capture."""

    def __init__(self, windows, closed=False):
        self.windows = windows
        self.closed = closed

    def text(self, since, until=None):
        return self.windows[(since, until)]


@pytest.fixture
def reports(tmp_path, monkeypatch):
    monkeypatch.setenv("HIL_REPORTS_DIR", str(tmp_path))
    return tmp_path


def test_a_closed_tap_is_a_rig_error_naming_the_window(reports):
    tap = WindowTap({("a", "b"): BANNER}, closed=True)
    with pytest.raises(RigError, match=r"lost the bridge.*\(recovery\)"):
        bootlog.check_boot_window(tap, "a", "b", "esp32s2", "recovery")


def test_a_window_without_a_rom_banner_is_a_rig_error(reports):
    with pytest.raises(RigError, match="no ROM boot banner captured"):
        bootlog.check_boot_window(WindowTap({("a", "b"): "[I][app:1]: fine\r\n"}), "a", "b", "esp32s2", "smoke")


def test_error_lines_come_back_and_are_not_written_to_the_allowlist_report(reports):
    tap = WindowTap({("a", "b"): BANNER + "[E][synthetic:9]: first\r\n"})
    errors, allowed = bootlog.check_boot_window(tap, "a", "b", "esp32s2", "smoke")
    assert errors == ["[E][synthetic:9]: first"] and allowed == []
    assert json.loads((reports / "allowlisted-errors.json").read_text()) == {"lines": []}


def test_allowlisted_lines_of_two_windows_accumulate_with_their_labels(reports):
    tap = WindowTap({("a", "b"): BANNER + WDT + "\r\n", ("c", "d"): BANNER + WDT.replace("4321", "99") + "\r\n"})
    with pytest.warns(UserWarning):
        bootlog.check_boot_window(tap, "a", "b", "esp32s2", "smoke")
    with pytest.warns(UserWarning):
        errors, allowed = bootlog.check_boot_window(tap, "c", "d", "esp32s2", "recovery")
    assert errors == [] and allowed == [WDT.replace("4321", "99")]
    assert json.loads((reports / "allowlisted-errors.json").read_text()) == {
        "lines": ["smoke: " + WDT, "recovery: " + WDT.replace("4321", "99")]
    }


def test_a_damaged_report_file_is_started_over(reports):
    (reports / "allowlisted-errors.json").write_text("{nope", encoding="utf-8")
    bootlog.check_boot_window(WindowTap({("a", "b"): BANNER}), "a", "b", "esp32s2", "smoke")
    assert json.loads((reports / "allowlisted-errors.json").read_text()) == {"lines": []}


def test_hil_run_deletes_the_accumulated_reports_at_its_start():
    from hil import __main__ as entry

    assert {"allowlisted-errors.json", "recovery-dut-a.json"} <= set(entry.STALE_REPORTS)
