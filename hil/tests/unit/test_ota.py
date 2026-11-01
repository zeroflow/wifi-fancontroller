"""OTA failure classes, deadlines and the key hygiene, with fakes only (no hardware, no esphome import)."""

import hashlib
import json
import logging
import os
import re
import sys
import time
import types
from types import SimpleNamespace

import pytest

from hil import FirmwareFailure, RigError, contract, ota
from hil import dut as dut_module
from hil.dut import Dut
from hil.ota import Ota

KEY = "KEY-VALUE-THAT-MUST-NOT-LEAK"
BANNER = "rst:0x1 (POWERON),boot:0x8 (SPI_FAST_FLASH_BOOT)\r\n"
OLD_ID = "3.2+hil." + "a" * 12
NEW_ID = "3.2+qc." + "a" * 12

FAKE_WORKER = r'''
import json, os, subprocess, sys, time
mode = os.environ["FAKE_MODE"]
state = os.environ["FAKE_STATE"]
json.dump({"argv": sys.argv[1:], "key_set": bool(os.environ.get("HIL_OTA_KEY"))}, open(state + ".call", "w"))
print("worker argv count", len(sys.argv) - 1)
if mode == "ok":
    sys.exit(0)
if mode == "done_slow":
    print("HIL-OTA-DONE", flush=True)
    time.sleep(1.5)
    sys.exit(0)
if mode == "exit1":
    print("synthetic upload failure")
    sys.exit(1)
if mode == "exit3":
    print("synthetic setup failure")
    sys.exit(3)
if mode == "hang":
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    open(state + ".child", "w").write(str(child.pid))
    sys.stdout.flush()
    time.sleep(60)
'''


@pytest.fixture
def worker(tmp_path, monkeypatch):
    script = tmp_path / "fake_worker.py"
    script.write_text(FAKE_WORKER, encoding="utf-8")
    monkeypatch.setenv("FAKE_STATE", str(tmp_path / "state"))

    def make(mode):
        monkeypatch.setenv("FAKE_MODE", mode)
        return Ota("203.0.113.9", worker_cmd=[sys.executable, str(script)])

    return make


def pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


# Launcher -----------------------------------------------------------------------------


def test_key_is_in_the_worker_environment_and_never_in_argv_or_output(worker, tmp_path):
    result = worker("ok").upload(tmp_path / "fw.bin", KEY)
    call = json.loads((tmp_path / "state.call").read_text(encoding="utf-8"))
    assert result.ok and result.reason == ""
    assert call["key_set"] is True
    assert KEY not in json.dumps(call["argv"])
    assert KEY not in result.output_tail
    assert call["argv"][:2] == ["203.0.113.9", str(ota.OTA_PORT)]


def test_done_line_calls_back_before_the_worker_exits_and_is_not_output(worker, tmp_path):
    seen = []
    result = worker("done_slow").upload(tmp_path / "fw.bin", KEY, on_done=lambda: seen.append(time.monotonic()))
    finished = time.monotonic()
    assert result.ok and len(seen) == 1
    assert finished - seen[0] > 1.0, "the callback must not wait for the worker process to exit"
    assert ota.DONE_LINE not in result.output_tail


def test_no_done_line_means_no_callback(worker, tmp_path):
    seen = []
    worker("ok").upload(tmp_path / "fw.bin", KEY, on_done=lambda: seen.append(True))
    assert seen == []


def test_worker_exit_1_is_reason_exit_1(worker, tmp_path):
    result = worker("exit1").upload(tmp_path / "fw.bin", KEY)
    assert (result.ok, result.reason) == (False, "exit 1")
    assert "synthetic upload failure" in result.output_tail


def test_worker_exit_3_is_reason_setup(worker, tmp_path):
    result = worker("exit3").upload(tmp_path / "fw.bin", KEY)
    assert (result.ok, result.reason) == (False, "setup")


def test_deadline_kills_the_worker_and_its_child(worker, tmp_path):
    started = time.monotonic()
    result = worker("hang").upload(tmp_path / "fw.bin", KEY, deadline_s=1)
    assert (result.ok, result.reason) == (False, "deadline")
    assert time.monotonic() - started < 10
    assert "process group killed" in result.output_tail
    child = int((tmp_path / "state.child").read_text(encoding="utf-8"))
    deadline = time.monotonic() + 3
    while pid_alive(child) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not pid_alive(child), "orphan left behind by the OTA deadline"


def test_output_tail_is_capped(worker, tmp_path, monkeypatch):
    monkeypatch.setattr(ota, "TAIL_LINES", 2)
    result = worker("exit1").upload(tmp_path / "fw.bin", KEY)
    assert len(result.output_tail.splitlines()) == 2


# Worker entry -------------------------------------------------------------------------


def stub_espota2(monkeypatch, returns=(0, None), log_success=True):
    calls = []

    def run_ota(*args, **kwargs):
        calls.append((args, kwargs))
        if returns[0] == 0 and log_success:
            logging.getLogger("esphome.espota2").info("OTA successful")
        return returns

    package = types.ModuleType("esphome")
    module = types.ModuleType("esphome.espota2")
    module.run_ota = run_ota
    package.espota2 = module
    monkeypatch.setitem(sys.modules, "esphome", package)
    monkeypatch.setitem(sys.modules, "esphome.espota2", module)
    return calls


def test_main_passes_the_key_as_noise_psk_and_refuses_plaintext(monkeypatch, tmp_path, capsys):
    calls = stub_espota2(monkeypatch)
    monkeypatch.setenv(ota.KEY_ENV, KEY)
    assert ota.main(["203.0.113.9", "3232", str(tmp_path / "fw.bin")]) == ota.EXIT_OK
    assert capsys.readouterr().out.splitlines() == ["OTA successful", ota.DONE_LINE]
    (args, kwargs), = calls
    assert args[:3] == ("203.0.113.9", 3232, None)  # no password
    assert str(args[3]) == str(tmp_path / "fw.bin")
    assert kwargs == {"noise_psk": KEY, "plaintext_fallback": False, "allow_plaintext_upload": False}


def test_main_without_a_key_exits_3_before_importing_esphome(monkeypatch, tmp_path, capsys):
    calls = stub_espota2(monkeypatch)
    monkeypatch.delenv(ota.KEY_ENV, raising=False)
    assert ota.main(["203.0.113.9", "3232", str(tmp_path / "fw.bin")]) == ota.EXIT_SETUP
    assert calls == []
    assert ota.KEY_ENV in capsys.readouterr().out


def test_main_prints_no_done_line_when_espota2_never_logs_success(monkeypatch, tmp_path, capsys):
    stub_espota2(monkeypatch, log_success=False)
    monkeypatch.setenv(ota.KEY_ENV, KEY)
    assert ota.main(["203.0.113.9", "3232", str(tmp_path / "fw.bin")]) == ota.EXIT_OK
    assert ota.DONE_LINE not in capsys.readouterr().out


def test_main_leaves_the_espota2_logger_as_it_found_it(monkeypatch, tmp_path):
    stub_espota2(monkeypatch)
    monkeypatch.setenv(ota.KEY_ENV, KEY)
    logger = logging.getLogger("esphome.espota2")
    before = (list(logger.handlers), logger.level)
    ota.main(["203.0.113.9", "3232", str(tmp_path / "fw.bin")])
    assert (list(logger.handlers), logger.level) == before


def test_real_worker_process_reports_done_before_it_exits(tmp_path, monkeypatch):
    """End to end through python -m hil.ota with a stub esphome package: the callback fires at the
    success log line, well before the worker (which, like espota2, lingers afterwards) exits."""
    package = tmp_path / "stubs" / "esphome"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "espota2.py").write_text(
        "import logging, time\n"
        "def run_ota(host, port, password, filename, ota_type=0, noise_psk=None,\n"
        "            plaintext_fallback=False, allow_plaintext_upload=False):\n"
        "    logging.getLogger(__name__).info('OTA successful')\n"
        "    time.sleep(1.5)\n"
        "    return 0, host\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "stubs"))
    seen = []
    result = Ota("203.0.113.9").upload(tmp_path / "fw.bin", KEY, on_done=lambda: seen.append(time.monotonic()))
    finished = time.monotonic()
    assert result.ok and len(seen) == 1
    assert finished - seen[0] > 1.0
    assert KEY not in result.output_tail and ota.DONE_LINE not in result.output_tail


def test_main_failed_upload_exits_1_without_a_done_line(monkeypatch, tmp_path, capsys):
    stub_espota2(monkeypatch, returns=(1, None))
    monkeypatch.setenv(ota.KEY_ENV, KEY)
    assert ota.main(["203.0.113.9", "3232", str(tmp_path / "fw.bin")]) == ota.EXIT_OTA_FAILED
    assert ota.DONE_LINE not in capsys.readouterr().out


def test_main_without_esphome_names_the_module_and_exits_3(monkeypatch, tmp_path, capsys):
    monkeypatch.setitem(sys.modules, "esphome", types.ModuleType("esphome"))  # no espota2 attribute
    monkeypatch.delitem(sys.modules, "esphome.espota2", raising=False)
    monkeypatch.setenv(ota.KEY_ENV, KEY)
    assert ota.main(["203.0.113.9", "3232", str(tmp_path / "fw.bin")]) == ota.EXIT_SETUP
    out = capsys.readouterr().out
    assert "esphome" in out and KEY not in out


def test_main_rejects_a_wrong_argument_count(capsys):
    assert ota.main(["only-one"]) == ota.EXIT_SETUP


# Dut.ota ------------------------------------------------------------------------------


class FakeOta:
    def __init__(self, result, reports_done=True):
        self.result = result
        self.reports_done = reports_done
        self.uploads = []

    def upload(self, path, key, deadline_s=ota.OTA_ATTEMPT_S, on_done=None):
        self.uploads.append((path, key))
        if self.result.ok and self.reports_done and on_done is not None:
            on_done()
        return self.result


class FakeTap:
    def __init__(self, window=BANNER, closed=False):
        self.window = window
        self.closed = closed
        self.marks = []
        self.asked = []
        self.waited = []

    def mark(self, name):
        self.marks.append(name)

    def text(self, since, until=None):
        self.asked.append(since)
        return self.window

    def wait_for(self, regex, since, deadline_s):
        self.waited.append((regex, since, deadline_s))
        found = re.search(regex, self.window)
        if not found:
            raise RigError("no match for /%s/ within %ss" % (regex, deadline_s))
        return found


class FakeSupervisor:
    def __init__(self):
        self.pressed = []

    def press(self, name):
        self.pressed.append(name)


def ok_result():
    return ota.OtaResult(ok=True, duration_s=12.3, reason="", output_tail="")


def fail_result(reason):
    return ota.OtaResult(ok=False, duration_s=4.0, reason=reason, output_tail="tail line")


@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.setenv("HIL_REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(dut_module.time, "sleep", lambda seconds: None)
    firmware = tmp_path / "fw.ota.bin"
    firmware.write_bytes(b"synthetic firmware")
    image = SimpleNamespace(
        role="qc-auto",
        build_id=NEW_ID,
        ota_path=firmware,
        ota_sha256=hashlib.sha256(b"synthetic firmware").hexdigest(),
    )

    def build(result, versions, tap=None):
        fake_ota = FakeOta(result)
        supervisor = FakeSupervisor()
        tap = tap if tap is not None else FakeTap()
        device = Dut("A", SimpleNamespace(host="203.0.113.9", chip="esp32s2"), supervisor, None, tap=tap, ota=fake_ota)
        sequence = iter(versions)

        def probe(noise_psk):
            item = next(sequence, versions[-1])
            if isinstance(item, Exception):
                raise item
            return SimpleNamespace(project_version=item)

        device.probe = probe
        return device, fake_ota, supervisor, tap

    return SimpleNamespace(build=build, image=image, reports=tmp_path / "reports")


def read_report(rig_):
    return json.loads((rig_.reports / "ota-dut-a.json").read_text(encoding="utf-8"))


def test_ota_old_old_new_is_ok_and_reported(rig, capsys):
    device, fake_ota, _, tap = rig.build(ok_result(), [OLD_ID, OLD_ID, NEW_ID])
    device.ota(rig.image, noise_psk=KEY)
    assert fake_ota.uploads == [(rig.image.ota_path, KEY)]
    assert tap.marks[0] == "ota_start_qc-auto" and tap.marks.count("ota_end_qc-auto") == 1
    assert tap.asked == ["ota_end_qc-auto"]
    (entry,) = read_report(rig)
    assert entry["role"] == "qc-auto" and entry["build_id"] == NEW_ID and entry["ok"] is True
    assert entry["transfer_s"] == 12.3 and entry["reason"] == "" and entry["boot_s"] is not None
    out = capsys.readouterr().out
    assert "ota qc-auto: ok transfer=12.3s" in out and NEW_ID in out


def test_without_a_done_report_the_banner_is_looked_for_from_ota_start(rig):
    fake = FakeOta(ok_result(), reports_done=False)
    device, _, _, tap = rig.build(ok_result(), [NEW_ID])
    device._ota = fake
    device.ota(rig.image, noise_psk=KEY)
    assert tap.marks.count("ota_end_qc-auto") == 1
    assert tap.asked == ["ota_start_qc-auto"]


def test_ota_survives_a_rebooting_dut_that_refuses_connections(rig):
    errors = [OSError("refused"), RigError("attempt timed out"), NEW_ID]
    device, *_ = rig.build(ok_result(), errors)
    device.ota(rig.image, noise_psk=KEY)


def test_old_image_until_the_deadline_is_a_firmware_failure_naming_both_ids(rig, monkeypatch):
    monkeypatch.setattr(dut_module, "OTA_BOOT_S", 0)
    device, *_ = rig.build(ok_result(), [OLD_ID])
    with pytest.raises(FirmwareFailure) as caught:
        device.ota(rig.image, noise_psk=KEY)
    assert OLD_ID in str(caught.value) and NEW_ID in str(caught.value)
    assert isinstance(caught.value, AssertionError)
    assert read_report(rig)[0]["ok"] is False


def test_failed_upload_is_a_firmware_failure_with_the_output_tail(rig):
    device, *_ = rig.build(fail_result("exit 1"), [OLD_ID])
    with pytest.raises(FirmwareFailure, match=r"OTA to qc-auto failed \(exit 1\)") as caught:
        device.ota(rig.image, noise_psk=KEY)
    assert "tail line" in str(caught.value) and KEY not in str(caught.value)
    assert read_report(rig)[0]["reason"] == "exit 1"


def test_upload_deadline_is_a_firmware_failure(rig):
    device, *_ = rig.build(fail_result("deadline"), [OLD_ID])
    with pytest.raises(FirmwareFailure, match="deadline"):
        device.ota(rig.image, noise_psk=KEY)


def test_worker_setup_failure_is_a_rig_error_not_a_firmware_failure(rig):
    device, *_ = rig.build(fail_result("setup"), [OLD_ID])
    with pytest.raises(RigError, match="could not run") as caught:
        device.ota(rig.image, noise_psk=KEY)
    assert not isinstance(caught.value, AssertionError)


def test_sha256_mismatch_is_a_rig_error_before_any_upload(rig):
    device, fake_ota, supervisor, tap = rig.build(ok_result(), [NEW_ID])
    rig.image.ota_path.write_bytes(b"tampered")
    with pytest.raises(RigError, match="does not match its manifest sha256"):
        device.ota(rig.image, noise_psk=KEY)
    assert fake_ota.uploads == [] and tap.marks == []


def test_image_without_an_ota_file_is_a_rig_error(rig):
    device, fake_ota, *_ = rig.build(ok_result(), [NEW_ID])
    image = SimpleNamespace(**{**vars(rig.image), "ota_path": None})
    with pytest.raises(RigError, match="no OTA file"):
        device.ota(image, noise_psk=KEY)
    assert fake_ota.uploads == []


def test_new_build_id_without_a_reboot_banner_is_a_firmware_failure(rig):
    device, *_ = rig.build(ok_result(), [NEW_ID], tap=FakeTap(window="[I][app:1]: no ROM banner here\r\n"))
    with pytest.raises(FirmwareFailure, match="no reboot seen after OTA to qc-auto"):
        device.ota(rig.image, noise_psk=KEY)


def test_closed_tap_is_a_rig_error_not_a_pass(rig):
    device, *_ = rig.build(ok_result(), [NEW_ID], tap=FakeTap(closed=True))
    with pytest.raises(RigError, match="lost the bridge"):
        device.ota(rig.image, noise_psk=KEY)


# Rollback window ----------------------------------------------------------------------


BOOT_OK = "[I][safe_mode:154]: Boot seems successful; resetting boot loop counter\r\n"


def test_reset_inside_the_window_without_boot_ok_is_refused_and_presses_nothing(rig):
    device, _, supervisor, tap = rig.build(ok_result(), [NEW_ID])
    device.ota(rig.image, noise_psk=KEY)
    assert device.unconfirmed_until > time.monotonic() + dut_module.OTA_CONFIRM_WINDOW_S - 5
    with pytest.raises(RigError, match="EN reset refused: the OTA image was not confirmed"):
        device.reset()
    assert supervisor.pressed == [] and "reset_pressed" not in tap.marks
    assert not any(m.startswith("reset_") for m in tap.marks)
    assert device.budget.report()["used"] == 1  # only the OTA reboot; the refused press is no boot


def test_reset_inside_the_window_waits_for_boot_ok_since_the_ota_end_mark_then_presses_once(rig):
    device, _, supervisor, tap = rig.build(ok_result(), [NEW_ID], tap=FakeTap(window=BANNER + BOOT_OK))
    device.ota(rig.image, noise_psk=KEY)
    mark = device.reset()
    assert supervisor.pressed == [contract.BUTTON["A"]["reset"]]
    assert mark == "reset_1" and mark in tap.marks and "reset_pressed" in tap.marks
    regex, since, deadline = tap.waited[-1]
    assert re.search(regex, BOOT_OK) and since == "ota_end_qc-auto"
    assert deadline <= dut_module.CONFIRM_WAIT_S
    assert device.unconfirmed_until == 0.0  # the window is cleared once confirmed


def test_reset_inside_the_window_with_no_tap_or_a_closed_tap_is_refused(rig):
    device, _, supervisor, _ = rig.build(ok_result(), [NEW_ID])
    device.unconfirmed_until = time.monotonic() + 50
    device.tap = None
    with pytest.raises(RigError, match="EN reset refused"):
        device.reset()
    device.tap = FakeTap(window=BOOT_OK, closed=True)
    device._ota_mark = "ota_end_qc-auto"
    with pytest.raises(RigError, match="EN reset refused"):
        device.reset()
    assert supervisor.pressed == []


def test_reset_after_the_window_presses_reset_and_records_an_en_reset(rig):
    device, _, supervisor, tap = rig.build(ok_result(), [NEW_ID])
    device.unconfirmed_until = time.monotonic() - 1
    device.reset()
    assert supervisor.pressed == [contract.BUTTON["A"]["reset"]] and "reset_pressed" in tap.marks
    assert [b["cause"] for b in device.budget.report()["boots"]] == ["en_reset"]


def test_a_serial_flash_ends_the_window(rig):
    flasher = SimpleNamespace(
        write=lambda regions, deadline_s: SimpleNamespace(ok=True, verified=True, duration_s=1.0, reason="", output_tail="")
    )
    tap = FakeTap(window=BANNER + "ROM: boot:0x0 (DOWNLOAD(USB/UART0))\r\n")
    device, _, supervisor, _ = rig.build(ok_result(), [NEW_ID], tap=tap)
    device._flasher = flasher
    device.unconfirmed_until = time.monotonic() + 100
    device.flash_regions([("0x0", "fw.bin")])
    assert supervisor.pressed[-1] == contract.BUTTON["A"]["reset"]
    assert [b["cause"] for b in device.budget.report()["boots"]] == ["flash_reset"]


def test_timing_constants_cover_boot_is_good_after():
    assert dut_module.OTA_CONFIRM_WINDOW_S >= 60 + 15
