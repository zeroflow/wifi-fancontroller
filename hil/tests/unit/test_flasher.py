"""Flash retry-once and deadline behaviour, with a fake esptool script (no hardware)."""

import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from hil import RigError, contract, dut as dut_module
from hil.dut import Dut
from hil.flasher import FLASH_ATTEMPT_S, Flasher

# "DUT A" label, taken from the contract so no supervisor name literal sits in a test.
LABEL = contract.SERIAL_CONNECTED["A"].removesuffix(" Serial Connected")

FAKE = r'''
import json, os, subprocess, sys, time
state = os.environ["FAKE_STATE"]
n = 1 + (int(open(state + ".n").read()) if os.path.exists(state + ".n") else 0)
open(state + ".n", "w").write(str(n))
json.dump({"argv": sys.argv[1:], "env": dict(os.environ)}, open(state + ".call%d" % n, "w"))
plan = json.loads(os.environ["FAKE_PLAN"])
step = plan[min(n, len(plan)) - 1]
if step == "ok":
    print("Writing at 0x00000000... (100 %)")
    print("Hash of data verified.")
    sys.exit(0)
if step == "exit2":
    print("A fatal error occurred: synthetic")
    sys.exit(2)
if step == "unverified":
    print("Wrote 1 byte")
    sys.exit(0)
if step == "hang":
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    open(state + ".child", "w").write(str(child.pid))
    time.sleep(60)
'''


class FakeSupervisor:
    def __init__(self):
        self.pressed = []

    def press(self, name):
        self.pressed.append(name)


@pytest.fixture
def env(tmp_path, monkeypatch):
    script = tmp_path / "fake_esptool.py"
    script.write_text(FAKE, encoding="utf-8")
    image = tmp_path / "image.bin"
    image.write_bytes(b"\x00" * 16)
    monkeypatch.setenv("FAKE_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("HIL_REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.setattr(dut_module, "BOOTLOADER_SETTLE_S", 0)
    return SimpleNamespace(script=script, image=image, tmp=tmp_path, monkeypatch=monkeypatch)


def plan(env, *steps):
    env.monkeypatch.setenv("FAKE_PLAN", json.dumps(list(steps)))


def make_dut(env, attempt_s=None):
    flasher = Flasher("127.0.0.1", 1, "esp32s2", esptool_cmd=[sys.executable, str(env.script)])
    sv = FakeSupervisor()
    cfg = SimpleNamespace(id="A", chip="esp32s2")
    d = Dut("A", cfg, sv, flasher)
    if attempt_s is not None:
        d.flash_attempt_s = attempt_s
    image = SimpleNamespace(offset="0x0", path=env.image)
    return d, sv, image


def test_first_call_fails_second_succeeds_is_one_visible_retry(env):
    plan(env, "exit2", "ok")
    d, sv, image = make_dut(env)
    report = d.flash(image)
    assert report.attempts == 2 and report.ok is True
    assert report.retry_reason == "exit 2"
    boot = contract.BUTTON["A"]["bootloader"]
    assert sv.pressed.count(boot) == 2
    assert sv.pressed[-1] == contract.BUTTON["A"]["reset"]
    saved = json.loads((env.tmp / "reports" / "flash-dut-a.json").read_text(encoding="utf-8"))
    assert saved["attempts"] == 2 and saved["ok"] is True and saved["retry_reason"] == "exit 2"
    assert len(saved["durations_s"]) == 2


def test_exit_zero_without_verified_line_counts_as_failed_attempt(env):
    plan(env, "unverified", "ok")
    d, _sv, image = make_dut(env)
    assert d.flash(image).retry_reason == "not verified"


def test_attempt_over_its_deadline_is_killed_as_process_group(env):
    flasher = Flasher("127.0.0.1", 1, "esp32s2", esptool_cmd=[sys.executable, str(env.script)])
    plan(env, "hang")
    result = flasher.write("0x0", env.image, deadline_s=1)
    assert result.ok is False and result.reason == "deadline"
    child = int((env.tmp / "state.child").read_text())
    end = time.monotonic() + 3
    gone = False
    while time.monotonic() < end and not gone:
        try:
            os.kill(child, 0)
            with open("/proc/%d/stat" % child, encoding="utf-8") as stat:
                gone = stat.read().split(")")[-1].split()[0] == "Z"
        except (ProcessLookupError, FileNotFoundError):
            gone = True
        if not gone:
            time.sleep(0.05)
    assert gone, "orphan child of the killed esptool is still running"


def test_deadline_reason_is_what_the_retry_reports(env):
    plan(env, "hang", "ok")
    d, _sv, image = make_dut(env, attempt_s=1)
    assert d.flash(image).retry_reason == "deadline"


def test_two_failed_attempts_raise_rig_error_and_still_reset(env):
    plan(env, "exit2", "exit2")
    d, sv, image = make_dut(env)
    with pytest.raises(RigError, match="flash failed after 2 attempts"):
        d.flash(image)
    assert sv.pressed[-1] == contract.BUTTON["A"]["reset"]
    saved = json.loads((env.tmp / "reports" / "flash-dut-a.json").read_text(encoding="utf-8"))
    assert saved["ok"] is False and saved["attempts"] == 2


def test_no_retry_when_first_attempt_succeeds(env):
    plan(env, "ok", "exit2")
    d, sv, image = make_dut(env)
    report = d.flash(image)
    assert report.attempts == 1 and report.retry_reason is None
    assert sv.pressed.count(contract.BUTTON["A"]["bootloader"]) == 1


def test_same_image_twice_ends_in_the_same_verified_state(env):
    plan(env, "ok", "ok")
    d, _sv, image = make_dut(env)
    first, second = d.flash(image), d.flash(image)
    assert (first.ok, first.attempts) == (second.ok, second.attempts) == (True, 1)


def test_child_has_no_baud_option_and_no_esptool_baud(env):
    env.monkeypatch.setenv("ESPTOOL_BAUD", "460800")
    plan(env, "ok")
    d, _sv, image = make_dut(env)
    d.flash(image)
    call = json.loads((env.tmp / "state.call1").read_text(encoding="utf-8"))
    assert "ESPTOOL_BAUD" not in call["env"]
    assert not [a for a in call["argv"] if a in ("--baud", "-b") or a.startswith("--baud")]
    assert "--chip" in call["argv"] and "no-reset" in call["argv"] and "write-flash" in call["argv"]


def test_github_actions_retry_prints_warning_and_summary_line(env, capsys):
    summary = env.tmp / "summary.md"
    env.monkeypatch.setenv("GITHUB_ACTIONS", "true")
    env.monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    plan(env, "exit2", "ok")
    d, _sv, image = make_dut(env)
    d.flash(image)
    out = capsys.readouterr().out
    assert "::warning title=HIL flash retry::%s flash needed a retry (exit 2)" % LABEL in out
    assert summary.read_text(encoding="utf-8").count("%s flash: ok after 2 attempts (exit 2)" % LABEL) == 1


def test_outside_github_actions_retry_prints_plain_warning(env, capsys):
    plan(env, "exit2", "ok")
    d, _sv, image = make_dut(env)
    d.flash(image)
    out = capsys.readouterr().out
    assert "WARNING: %s flash needed a retry (exit 2)" % LABEL in out and "::warning" not in out


def test_default_attempt_deadline_is_named_constant():
    assert FLASH_ATTEMPT_S == 120
