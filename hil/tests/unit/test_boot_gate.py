"""The D-14 boot-log gate (bootlog.check_boot_window) and the smoke test that calls it, driven with fakes:
a gate that cannot see a boot is a rig error."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from hil import RigError, bootlog

SMOKE = Path(__file__).resolve().parents[1] / "rig" / "test_10_smoke_dut_a.py"
BANNER = "rst:0x1 (POWERON),boot:0x8 (SPI_FAST_FLASH_BOOT)\r\n"
BUILD_ID = "3.2+hil." + "a" * 12


class FakeTap:
    def __init__(self, window, closed=False):
        self.window = window
        self.closed = closed
        self.marks = []

    def mark(self, name):
        self.marks.append(name)

    def text(self, since, until=None):
        assert (since, until) == ("reset_pressed", "scan_end")
        return self.window


def run_smoke(tmp_path, monkeypatch, tap, reported=BUILD_ID):
    spec = importlib.util.spec_from_file_location("smoke_under_test", SMOKE)
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
    monkeypatch.setattr(smoke, "BOOT_SETTLE_S", 0)
    monkeypatch.setenv("HIL_REPORTS_DIR", str(tmp_path))
    report = SimpleNamespace(ok=True, verified=True, attempts=1, durations_s=[1.0])
    info = SimpleNamespace(project_version=reported, compilation_time="synthetic")
    dut = SimpleNamespace(flash=lambda image: report, wait_api=lambda noise_psk: info)
    manifest = SimpleNamespace(image=lambda role: object(), build_id=BUILD_ID)
    rig = SimpleNamespace(duts={"A": SimpleNamespace(chip="esp32s2")}, dut_api_key=None)
    smoke.test_commit_image_boots_and_reports_build_id(dut, tap, manifest, rig)


def test_clean_boot_with_banner_passes(tmp_path, monkeypatch, capsys):
    tap = FakeTap(BANNER + "[I][app:1]: fine\r\n")
    run_smoke(tmp_path, monkeypatch, tap)
    out = capsys.readouterr().out
    assert "boot log clean: 0 [E] lines" in out and "build ID matches manifest" in out
    assert tap.marks == ["scan_end"]


def test_empty_capture_is_a_rig_error_not_a_pass(tmp_path, monkeypatch):
    with pytest.raises(RigError, match="no ROM boot banner captured"):
        run_smoke(tmp_path, monkeypatch, FakeTap(""))


def test_closed_tap_is_a_rig_error_not_a_pass(tmp_path, monkeypatch):
    with pytest.raises(RigError, match="lost the bridge"):
        run_smoke(tmp_path, monkeypatch, FakeTap(BANNER, closed=True))


def test_error_lines_and_build_id_mismatch_are_reported_together(tmp_path, monkeypatch, capsys):
    tap = FakeTap(BANNER + "[E][synthetic:9]: first\r\nE (5) boot: second\r\n")
    with pytest.raises(AssertionError) as caught:
        run_smoke(tmp_path, monkeypatch, tap, reported="3.2+hil." + "b" * 12)
    message = str(caught.value)
    assert "[E][synthetic:9]: first" in message and "E (5) boot: second" in message
    assert "project_version" in message
    assert "build ID matches manifest" not in capsys.readouterr().out


WDT = "E (4321) task_wdt: esp_task_wdt_reset(707): task not found"


def test_one_allowlisted_task_wdt_line_passes_with_a_visible_warning(tmp_path, monkeypatch, capsys):
    tap = FakeTap(BANNER + WDT + "\r\n")
    with pytest.warns(UserWarning, match="ALLOWLISTED boot-log line"):
        run_smoke(tmp_path, monkeypatch, tap)
    out = capsys.readouterr().out
    assert "WARNING: ALLOWLISTED boot-log line" in out and WDT in out
    assert "boot log clean: 0 [E] lines (1 allowlisted)" in out
    assert json.loads((tmp_path / "allowlisted-errors.json").read_text()) == {"lines": ["smoke: " + WDT]}


def test_a_clean_boot_records_an_empty_allowlist_report(tmp_path, monkeypatch):
    run_smoke(tmp_path, monkeypatch, FakeTap(BANNER))
    assert json.loads((tmp_path / "allowlisted-errors.json").read_text()) == {"lines": []}


def test_two_task_wdt_lines_fail_the_smoke_test(tmp_path, monkeypatch):
    tap = FakeTap(BANNER + WDT + "\r\n" + WDT.replace("4321", "5000") + "\r\n")
    with pytest.raises(AssertionError, match=r"2 \[E\] line\(s\)"):
        run_smoke(tmp_path, monkeypatch, tap)


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
