"""OTA failure classes, deadlines and the key hygiene, with fakes only (no hardware, no esphome import)."""

import hashlib
import json
import logging
import os
import re
import sys
import time
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from hil import FirmwareFailure, RigError, contract, ota
from hil import dut as dut_module
from hil.dut import Dut
from hil.ota import Ota

KEY = "KEY-VALUE-THAT-MUST-NOT-LEAK"
ASK_PLAINTEXT = {"allow_plaintext": True}  # spelled as a dict: the literal keyword belongs to test_11 alone
BANNER = "rst:0x1 (POWERON),boot:0x8 (SPI_FAST_FLASH_BOOT)\r\n"
OLD_ID = "3.2+hil." + "a" * 12
NEW_ID = "3.2+qc." + "a" * 12

# The worker sees a minimal environment (IN-04), so the fake takes its mode and state path as the first
# two arguments of its command; the launcher appends host, port and path after them.
FAKE_WORKER = r'''
import json, os, subprocess, sys, time
mode, state = sys.argv[1], sys.argv[2]
json.dump(
    {"argv": sys.argv[3:], "key_set": bool(os.environ.get("HIL_OTA_KEY")), "env": dict(os.environ)},
    open(state + ".call", "w"),
)
print("worker argv count", len(sys.argv) - 3)
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

    def make(mode):
        return Ota("203.0.113.9", worker_cmd=[sys.executable, str(script), mode, str(tmp_path / "state")])

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


def read_call(tmp_path):
    return json.loads((tmp_path / "state.call").read_text(encoding="utf-8"))


def test_the_plaintext_flag_reaches_the_worker_only_when_asked(worker, tmp_path, monkeypatch):
    """T-03-25: the default refuses plaintext; a flag set in the parent never leaks into the worker."""
    monkeypatch.setenv(ota.ALLOW_PLAINTEXT_ENV, "1")  # a stray flag in the harness's own environment
    worker("ok").upload(tmp_path / "fw.bin", KEY)
    assert ota.ALLOW_PLAINTEXT_ENV not in read_call(tmp_path)["env"]
    worker("ok").upload(tmp_path / "fw.bin", KEY, **ASK_PLAINTEXT)
    call = read_call(tmp_path)
    assert call["env"][ota.ALLOW_PLAINTEXT_ENV] == "1" and call["env"][ota.KEY_ENV] == KEY
    assert call["argv"][:2] == ["203.0.113.9", str(ota.OTA_PORT)] and len(call["argv"]) == 3  # nothing added to argv


@pytest.mark.parametrize("truthy", ["yes", 1, "1"])
def test_only_the_literal_true_sets_the_flag(truthy):
    assert ota.ALLOW_PLAINTEXT_ENV not in ota.worker_env(KEY, truthy)
    assert ota.worker_env(KEY, True)[ota.ALLOW_PLAINTEXT_ENV] == "1"


def test_the_worker_environment_is_minimal(worker, tmp_path, monkeypatch):
    """IN-04, T-03-26: the supervisor key, GITHUB_* and anything else inherited never reach the worker."""
    monkeypatch.setenv("HIL_SUPERVISOR_KEY", "SUPERVISOR-KEY-THAT-MUST-NOT-LEAK")
    monkeypatch.setenv("GITHUB_TOKEN", "ghs_must_not_leak")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("SOME_OTHER_VARIABLE", "x")
    monkeypatch.setenv("LANG", "C.UTF-8")
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.delenv("LC_ALL", raising=False)
    worker("ok").upload(tmp_path / "fw.bin", KEY)
    env = read_call(tmp_path)["env"]
    assert set(env) - {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", ota.KEY_ENV} <= {"LC_CTYPE", "PWD", "SHLVL", "_"}
    assert env["LANG"] == "C.UTF-8" and env["TMPDIR"] == str(tmp_path) and env[ota.KEY_ENV] == KEY
    assert "LC_ALL" not in env and "HIL_SUPERVISOR_KEY" not in env
    assert not any(name.startswith("GITHUB_") for name in env)
    assert "SUPERVISOR-KEY-THAT-MUST-NOT-LEAK" not in json.dumps(env)


def test_worker_env_passes_only_the_listed_variables(monkeypatch):
    monkeypatch.setenv("HIL_SUPERVISOR_KEY", "x")
    monkeypatch.setenv("GITHUB_SHA", "y")
    monkeypatch.setenv("PATH", "/usr/bin")
    env = ota.worker_env(KEY)
    assert set(env) <= set(ota.PASSED_ENV) | {ota.KEY_ENV}
    assert env["PATH"] == "/usr/bin" and env[ota.KEY_ENV] == KEY


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


@pytest.mark.parametrize("value", [None, "0", "true", "yes", ""])
def test_main_refuses_plaintext_unless_the_flag_is_exactly_1(monkeypatch, tmp_path, value):
    calls = stub_espota2(monkeypatch)
    monkeypatch.setenv(ota.KEY_ENV, KEY)
    if value is None:
        monkeypatch.delenv(ota.ALLOW_PLAINTEXT_ENV, raising=False)
    else:
        monkeypatch.setenv(ota.ALLOW_PLAINTEXT_ENV, value)
    assert ota.main(["203.0.113.9", "3232", str(tmp_path / "fw.bin")]) == ota.EXIT_OK
    (_args, kwargs), = calls
    assert kwargs["allow_plaintext_upload"] is False and kwargs["plaintext_fallback"] is False


def test_main_with_the_flag_allows_a_plaintext_upload_and_still_offers_the_key(monkeypatch, tmp_path):
    calls = stub_espota2(monkeypatch)
    monkeypatch.setenv(ota.KEY_ENV, KEY)
    monkeypatch.setenv(ota.ALLOW_PLAINTEXT_ENV, "1")
    assert ota.main(["203.0.113.9", "3232", str(tmp_path / "fw.bin")]) == ota.EXIT_OK
    (_args, kwargs), = calls
    assert kwargs == {"noise_psk": KEY, "plaintext_fallback": False, "allow_plaintext_upload": True}


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
    # PYTHONPATH does not reach the worker (minimal environment), so the stub path goes into the command.
    boot = "import runpy, sys; sys.path.insert(0, %r); runpy.run_module('hil.ota', run_name='__main__')" % str(
        tmp_path / "stubs"
    )
    seen = []
    result = Ota("203.0.113.9", worker_cmd=[sys.executable, "-c", boot]).upload(
        tmp_path / "fw.bin", KEY, on_done=lambda: seen.append(time.monotonic())
    )
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
        self.kwargs = []

    def upload(self, path, key, deadline_s=ota.OTA_ATTEMPT_S, on_done=None, **kwargs):
        self.uploads.append((path, key))
        self.kwargs.append(kwargs)
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


def read_timings(rig_):
    return json.loads((rig_.reports / "timings.json").read_text(encoding="utf-8"))


def test_a_successful_ota_records_its_transfer_and_its_boot_time(rig):
    device, *_ = rig.build(ok_result(), [NEW_ID])
    device.ota(rig.image, noise_psk=KEY)
    timings = read_timings(rig)
    assert timings["ota_qc-auto"] == 12.3
    assert set(timings) == {"ota_qc-auto", "ota_qc-auto_boot"} and timings["ota_qc-auto_boot"] >= 0


def test_a_failed_ota_records_no_timing(rig):
    device, *_ = rig.build(fail_result("deadline"), [OLD_ID])
    with pytest.raises(FirmwareFailure):
        device.ota(rig.image, noise_psk=KEY)
    assert not (rig.reports / "timings.json").exists()


# Labels and the plaintext flag of Dut.ota ----------------------------------------------


def test_dut_ota_never_asks_for_plaintext_by_default(rig):
    device, fake_ota, *_ = rig.build(ok_result(), [NEW_ID])
    device.ota(rig.image, noise_psk=KEY)
    assert fake_ota.kwargs == [{}]


def test_dut_ota_passes_allow_plaintext_and_the_key_when_asked(rig):
    device, fake_ota, *_ = rig.build(ok_result(), [NEW_ID])
    device.ota(rig.image, noise_psk=KEY, **ASK_PLAINTEXT)
    assert fake_ota.kwargs == [{"allow_plaintext": True}] and fake_ota.uploads == [(rig.image.ota_path, KEY)]


def test_a_label_names_the_marks_the_timings_and_the_report_entry(rig, capsys):
    device, _, _, tap = rig.build(ok_result(), [NEW_ID], tap=FakeTap(window=BANNER + BOOT_OK))
    device.ota(rig.image, noise_psk=KEY, label="baseline_commit")
    assert tap.marks[0] == "ota_start_baseline_commit" and "ota_end_baseline_commit" in tap.marks
    assert tap.asked == ["ota_end_baseline_commit"]
    (entry,) = read_report(rig)
    assert entry["label"] == "baseline_commit" and entry["role"] == "qc-auto" and entry["build_id"] == NEW_ID
    timings = read_timings(rig)
    assert set(timings) == {"ota_baseline_commit", "ota_baseline_commit_boot"}
    assert device.last_ota["label"] == "baseline_commit"
    assert "ota qc-auto (baseline_commit): ok" in capsys.readouterr().out
    device.reset()  # the window guard waits for Boot seems successful since the labelled end mark
    assert tap.waited[-1][1] == "ota_end_baseline_commit"


def test_two_otas_to_one_role_with_different_labels_stay_apart(rig):
    device, *_ = rig.build(ok_result(), [NEW_ID])
    device.ota(rig.image, noise_psk=KEY, label="baseline_commit")
    device.ota(rig.image, noise_psk=KEY)
    assert [e["label"] for e in read_report(rig)] == ["baseline_commit", "qc-auto"]
    assert {"ota_baseline_commit", "ota_qc-auto"} <= set(read_timings(rig))


def test_without_a_label_the_report_entry_is_labelled_with_the_role(rig):
    device, *_ = rig.build(ok_result(), [NEW_ID])
    device.ota(rig.image, noise_psk=KEY)
    assert read_report(rig)[0]["label"] == "qc-auto"


def test_only_test_11_asks_for_a_plaintext_upload():
    """T-03-24: the keyword with a literal True appears in exactly one rig test, in no harness module and no other test."""
    root = Path(__file__).resolve().parents[2]
    needle = "allow_plaintext" + "=True"
    found = sorted(
        str(path.relative_to(root))
        for folder in ("hil", "tests")
        for path in (root / folder).rglob("*.py")
        if needle in path.read_text(encoding="utf-8")
    )
    assert found == ["tests/rig/test_11_upgrade_from_release.py"]


# wait_confirmed: no press before the new image is marked valid (REG-02) ----------------


def test_wait_confirmed_without_a_window_returns_zero_at_once(rig):
    device, _, supervisor, tap = rig.build(ok_result(), [NEW_ID])
    assert device.wait_confirmed() == 0.0
    assert tap.waited == [] and supervisor.pressed == []


def test_wait_confirmed_returns_the_seconds_from_the_ota_end_to_boot_ok_and_clears_the_window(rig):
    device, _, supervisor, tap = rig.build(ok_result(), [NEW_ID], tap=FakeTap(window=BANNER + BOOT_OK))
    device.ota(rig.image, noise_psk=KEY)
    assert device.ota_end_at is not None and device.ota_end_at <= time.monotonic()
    device.ota_end_at = time.monotonic() - 61.0  # the upload ended 61 s ago
    seconds = device.wait_confirmed()
    assert 61.0 <= seconds < 70.0
    assert device.unconfirmed_until == 0.0 and supervisor.pressed == []
    regex, since, deadline = tap.waited[-1]
    assert re.search(regex, BOOT_OK) and since == "ota_end_qc-auto" and deadline <= dut_module.CONFIRM_WAIT_S
    assert device.wait_confirmed() == 0.0  # confirmed once: nothing left to wait for


def test_wait_confirmed_without_boot_ok_refuses_and_presses_nothing(rig):
    device, _, supervisor, _ = rig.build(ok_result(), [NEW_ID])
    device.ota(rig.image, noise_psk=KEY)
    with pytest.raises(RigError, match="the OTA image was not confirmed"):
        device.wait_confirmed(deadline_s=1)
    assert supervisor.pressed == [] and device.unconfirmed_until > 0


def test_wait_confirmed_takes_the_shorter_of_its_deadline_and_the_window(rig):
    device, _, _, tap = rig.build(ok_result(), [NEW_ID], tap=FakeTap(window=BANNER + BOOT_OK))
    device.ota(rig.image, noise_psk=KEY)
    device.wait_confirmed(deadline_s=5)
    assert tap.waited[-1][2] == 5


def test_the_ota_end_time_is_taken_at_the_done_report_and_without_it_at_the_end_mark(rig):
    device, *_ = rig.build(ok_result(), [NEW_ID])
    before = time.monotonic()
    device.ota(rig.image, noise_psk=KEY)
    assert before <= device.ota_end_at <= time.monotonic()
    device._ota = FakeOta(ok_result(), reports_done=False)
    device.ota_end_at = None
    device.ota(rig.image, noise_psk=KEY)
    assert device.ota_end_at is not None


def test_the_window_start_of_the_last_ota_is_kept_for_the_soak(rig):
    device, *_ = rig.build(ok_result(), [NEW_ID])
    device.ota(rig.image, noise_psk=KEY, label="baseline_commit")
    assert device.last_ota["window_start"] == "ota_end_baseline_commit"


def test_the_soak_is_seventy_seconds_and_outlasts_boot_is_good_after():
    assert dut_module.SOAK_S == 70 and dut_module.SOAK_S > 60


# The release-to-commit upgrade under the release bootloader: UART0 is dark, the API is the proof ------
# (03-11 maintainer decision serial-restore-after-upgrade, 2026-11-09)

NO_UART_BANNER = {"uart_banner": False}  # spelled as a dict: the literal keyword belongs to test_11 alone


class FakeLink:
    def __init__(self, at=None):
        self.at = at  # monotonic time of the 'Boot seems successful' line, or None: never comes
        self.waited = []

    def wait_log(self, regex, since, deadline_s):
        self.waited.append((regex, since, deadline_s))
        if self.at is None:
            raise RigError("DUT API log: no match for /%s/ within %ss" % (regex, deadline_s))
        return self.at


def test_the_upgrade_ota_skips_the_uart0_banner_check_and_proves_the_reboot_by_the_build_id(rig, capsys):
    device, _, _, tap = rig.build(ok_result(), [OLD_ID, NEW_ID], tap=FakeTap(window=""))
    device.ota(rig.image, noise_psk=KEY, label="baseline_commit", **ASK_PLAINTEXT, **NO_UART_BANNER)
    (entry,) = read_report(rig)
    assert entry["ok"] is True and entry["reboot_proof"] == "build id"
    assert tap.asked == []  # UART0 is not read for a banner
    assert "ota qc-auto (baseline_commit): ok" in capsys.readouterr().out


def test_every_other_ota_keeps_the_uart0_banner_check(rig):
    device, *_ = rig.build(ok_result(), [NEW_ID], tap=FakeTap(window=""))
    with pytest.raises(FirmwareFailure, match="no reboot seen"):
        device.ota(rig.image, noise_psk=KEY)
    device, *_ = rig.build(ok_result(), [NEW_ID])
    device.ota(rig.image, noise_psk=KEY)
    assert read_report(rig)[-1]["reboot_proof"] == "uart0 banner"


def test_skipping_the_banner_check_without_the_plaintext_upgrade_is_refused_before_any_upload(rig):
    device, fake_ota, *_ = rig.build(ok_result(), [NEW_ID], tap=FakeTap(window=""))
    with pytest.raises(RigError, match="only for the release-to-commit upgrade"):
        device.ota(rig.image, noise_psk=KEY, **NO_UART_BANNER)
    assert fake_ota.uploads == []


def test_the_upgrade_still_needs_the_tap_for_its_soak(rig):
    device, *_ = rig.build(ok_result(), [NEW_ID], tap=FakeTap(window="", closed=True))
    with pytest.raises(RigError, match="serial tap lost"):
        device.ota(rig.image, noise_psk=KEY, **ASK_PLAINTEXT, **NO_UART_BANNER)


def test_wait_confirmed_after_the_upgrade_reads_the_api_log_since_the_ota_end(rig):
    device, _, supervisor, tap = rig.build(ok_result(), [NEW_ID], tap=FakeTap(window=BANNER + BOOT_OK))
    device.ota(rig.image, noise_psk=KEY, **ASK_PLAINTEXT, **NO_UART_BANNER)
    end = device.ota_end_at
    link = FakeLink(at=end + 60.8)
    assert device.wait_confirmed(link=link) == pytest.approx(60.8)
    regex, since, deadline = link.waited[-1]
    assert re.search(regex, BOOT_OK) and since == end and deadline <= dut_module.CONFIRM_WAIT_S
    assert tap.waited == []  # UART0 is never asked: it is dark under the release bootloader
    assert device.unconfirmed_until == 0.0 and supervisor.pressed == []
    device.reset()  # confirmed over the API: the guard lets the press through
    assert supervisor.pressed == [contract.BUTTON["A"]["reset"]]


def test_a_reset_after_the_upgrade_before_the_api_confirmation_is_refused_explicitly(rig):
    device, _, supervisor, tap = rig.build(ok_result(), [NEW_ID], tap=FakeTap(window=BANNER + BOOT_OK))
    device.ota(rig.image, noise_psk=KEY, **ASK_PLAINTEXT, **NO_UART_BANNER)
    with pytest.raises(RigError, match="EN reset refused: the upgraded image is confirmed over the API log only"):
        device.reset()  # a Boot OK on UART0 does not count here, and reset() has no API log
    assert supervisor.pressed == [] and tap.waited == []


def test_no_boot_ok_in_the_api_log_refuses_and_keeps_the_window(rig):
    device, _, supervisor, _ = rig.build(ok_result(), [NEW_ID], tap=FakeTap(window=""))
    device.ota(rig.image, noise_psk=KEY, **ASK_PLAINTEXT, **NO_UART_BANNER)
    with pytest.raises(RigError, match="no 'Boot seems successful' in the API log"):
        device.wait_confirmed(link=FakeLink(at=None))
    assert device.unconfirmed_until > 0 and supervisor.pressed == []


def test_the_next_uart_confirmed_ota_reads_uart0_again(rig):
    device, _, _, tap = rig.build(ok_result(), [NEW_ID], tap=FakeTap(window=BANNER + BOOT_OK))
    device.ota(rig.image, noise_psk=KEY, **ASK_PLAINTEXT, **NO_UART_BANNER)
    device.wait_confirmed(link=FakeLink(at=device.ota_end_at + 1))
    device.ota(rig.image, noise_psk=KEY)
    link = FakeLink(at=None)
    device.wait_confirmed(link=link)
    assert link.waited == [] and tap.waited[-1][1] == "ota_end_qc-auto"


def test_only_test_11_skips_the_uart0_banner_check():
    root = Path(__file__).resolve().parents[2]
    needle = "uart_banner" + "=False"
    found = sorted(
        str(path.relative_to(root))
        for folder in ("hil", "tests")
        for path in (root / folder).rglob("*.py")
        if needle in path.read_text(encoding="utf-8")
    )
    assert found == ["tests/rig/test_11_upgrade_from_release.py"]


def test_reset_records_the_time_of_its_press_for_the_stale_session_check(rig):
    device, *_ = rig.build(ok_result(), [NEW_ID])
    assert device.last_reset_at is None
    before = time.monotonic()
    device.reset()
    assert before <= device.last_reset_at <= time.monotonic()
