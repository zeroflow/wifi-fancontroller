"""Dut records flash and boot timings into reports/timings.json (CI-05), with fakes only (OTA timings: test_ota.py)."""

import json
from types import SimpleNamespace

import pytest
from test_dut_state import BOOT, DOWNLOAD, FakeClock, FakeSupervisor, ScriptedTap, make_dut

from hil import contract
from hil import dut as dut_module
from hil.dut import Dut
from hil.flasher import FlashResult

IMAGE = SimpleNamespace(offset="0x0", path="firmware.factory.bin")


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(dut_module, "time", fake)
    return fake


def timings(tmp_path_factory_reports):
    return json.loads((tmp_path_factory_reports / "timings.json").read_text(encoding="utf-8"))


@pytest.fixture
def reports(tmp_path, monkeypatch):
    monkeypatch.setenv("HIL_REPORTS_DIR", str(tmp_path))
    return tmp_path


class FakeFlasher:
    def __init__(self, results):
        self.results = list(results)

    def write(self, regions, deadline_s):
        return self.results.pop(0)


def result(seconds, ok=True):
    return FlashResult(ok=ok, duration_s=seconds, verified=ok, output_tail="", reason="" if ok else "exit 2")


def flashing_dut(results):
    tap = ScriptedTap()
    supervisor = FakeSupervisor(tap)
    supervisor.on_press[contract.BUTTON["A"]["bootloader"]] = DOWNLOAD
    cfg = SimpleNamespace(host="192.0.2.20", chip="esp32s2")
    return Dut("A", cfg, supervisor, FakeFlasher(results), tap=tap), tap


def answering(device):
    device.probe = lambda psk: SimpleNamespace(project_version="v")


def test_flash_records_its_duration(clock, reports):
    device, _tap = flashing_dut([result(70.04)])
    device.flash(IMAGE)
    assert timings(reports) == {"flash": 70.0}


def test_a_flash_with_a_retry_records_the_sum_of_both_attempts(clock, reports):
    device, _tap = flashing_dut([result(30.0, ok=False), result(40.04)])
    device.flash(IMAGE)
    assert timings(reports)["flash"] == 70.0


def test_a_teardown_flash_with_its_own_report_name_records_no_timing(clock, reports):
    device, tap = flashing_dut([result(70.0)])
    device.flash_regions([("0x0", "known-good.bin")], report_name="teardown-flash-dut-a.json")
    tap.feed(BOOT)
    answering(device)
    device.wait_api(noise_psk="k")
    assert not (reports / "timings.json").exists()


def test_boot_is_the_time_from_the_flash_reset_press_to_the_api_answer(clock, reports):
    device, tap = flashing_dut([result(70.0)])
    device.flash(IMAGE)
    tap.feed(BOOT)
    answering(device)
    clock.now += 5.0
    device.wait_api(noise_psk="k")
    assert timings(reports) == {"flash": 70.0, "boot": 5.0}


def test_wait_running_after_a_flash_reset_records_boot_too(clock, reports):
    device, tap = flashing_dut([result(70.0)])
    device.flash(IMAGE)
    tap.feed(BOOT)
    answering(device)
    clock.now += 6.0
    device.wait_running("k", "reset_2")
    assert timings(reports)["boot"] == 6.0


def test_only_the_first_answer_after_the_flash_reset_is_a_boot_time(clock, reports):
    device, tap = flashing_dut([result(70.0)])
    device.flash(IMAGE)
    tap.feed(BOOT)
    answering(device)
    clock.now += 4.0
    device.wait_api(noise_psk="k")
    clock.now += 100.0
    device.wait_api(noise_psk="k")
    assert timings(reports)["boot"] == 4.0


def test_an_en_reset_is_not_a_flash_boot(clock, reports):
    device, tap, _sv = make_dut()
    answering(device)
    mark = device.reset()
    tap.feed(BOOT)
    clock.now += 3.0
    device.wait_running("k", mark)
    assert not (reports / "timings.json").exists()


def test_a_failed_flash_still_records_its_attempts_and_the_boot_after_its_reset(clock, reports):
    """The board is reset after a failed flash too; the run stops with a RigError, the timings stay honest."""
    device, tap = flashing_dut([result(30.0, ok=False), result(31.0, ok=False)])
    with pytest.raises(dut_module.RigError):
        device.flash(IMAGE)
    tap.feed(BOOT)
    answering(device)
    clock.now += 2.0
    device.wait_api(noise_psk="k")
    assert timings(reports) == {"flash": 61.0, "boot": 2.0}
