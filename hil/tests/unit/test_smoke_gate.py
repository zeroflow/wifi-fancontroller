"""The smoke test's verdict logic, driven with fakes: a gate that cannot see a boot is a rig error."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from hil import RigError

SMOKE = Path(__file__).resolve().parents[1] / "rig" / "test_smoke_dut_a.py"
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
