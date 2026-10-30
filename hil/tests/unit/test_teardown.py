"""Teardown state machine with a fake supervisor, a fake esptool script and a scripted API (no hardware)."""

import collections
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from hil import RigError, config, contract, dut as dut_module, manifest as manifest_module, teardown
from hil.__main__ import build_parser
from hil.dut import Dut
from hil.flasher import Flasher

# "DUT A" label, taken from the contract so no supervisor name literal sits in a test.
LABEL = contract.SERIAL_CONNECTED["A"].removesuffix(" Serial Connected")
COMMIT = "a" * 40
BUILD_ID = "3.2+hil." + "a" * 12
NVS_SIZE = 0x60000

# Records every esptool argv; prints one hash line per written region.
FAKE_ESPTOOL = r'''
import json, os, sys
state = os.environ["FAKE_STATE"]
n = 1 + (int(open(state + ".n").read()) if os.path.exists(state + ".n") else 0)
open(state + ".n", "w").write(str(n))
json.dump(sys.argv[1:], open(state + ".call%d" % n, "w"))
if "write-flash" in sys.argv:
    pairs = (len(sys.argv) - sys.argv.index("write-flash") - 1) // 2
    for _ in range(pairs):
        print("Hash of data verified.")
'''


class FakeSupervisor:
    def __init__(self, events):
        self.events = events
        self.bridge_busy = 0

    def release_all(self):
        self.events.append("release_all")

    def press(self, name):
        self.events.append(("press", name))

    def serial_connected(self, dut_id):
        if self.bridge_busy:
            self.bridge_busy -= 1
            return True
        return False


class ScriptedDut(Dut):
    """Real flash path (Dut.flash_regions), scripted API answers: a version string or None for no answer."""

    def __init__(self, *args, answers, **kwargs):
        super().__init__(*args, **kwargs)
        self.answers = collections.deque(answers)
        self.api_calls = []

    def wait_api(self, noise_psk, deadline_s=90):
        self.api_calls.append(noise_psk)
        answer = self.answers.popleft() if self.answers else None
        if answer is None:
            raise RigError("%s API did not answer within %ss" % (LABEL, deadline_s))
        return SimpleNamespace(project_version=answer)


@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.setattr(dut_module, "BOOTLOADER_SETTLE_S", 0)
    monkeypatch.setenv("HIL_REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("FAKE_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("HIL_EXPECTED_COMMIT", COMMIT)
    for name in ("GITHUB_ACTIONS", "GITHUB_STEP_SUMMARY", "GITHUB_REF", "GITHUB_RUN_ID", "HIL_JOB_STATUS"):
        monkeypatch.delenv(name, raising=False)
    script = tmp_path / "fake_esptool.py"
    script.write_text(FAKE_ESPTOOL, encoding="utf-8")
    kg = tmp_path / "kg.bin"
    kg.write_bytes(b"v1.6.0 factory image")
    nvs_file = tmp_path / "nvs.bin"
    nvs_file.write_bytes(b"\x01" * NVS_SIZE)
    fw = tmp_path / "fw"
    fw.mkdir()
    (fw / "firmware.factory.bin").write_bytes(b"commit image")
    (fw / "manifest.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "commit": COMMIT,
                "build_id": BUILD_ID,
                "images": [
                    {
                        "role": "commit",
                        "file": "firmware.factory.bin",
                        "sha256": hashlib.sha256(b"commit image").hexdigest(),
                        "chip": "esp32s2",
                        "offset": "0x0",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    dutcfg = SimpleNamespace(
        id="A",
        rev="3.2",
        chip="esp32s2",
        host="192.0.2.20",
        mac="02:00:00:00:00:0a",
        flash_offset="0x0",
        known_good_image=str(kg),
        known_good_sha256=hashlib.sha256(kg.read_bytes()).hexdigest(),
        known_good_api_encryption=False,
        nvs_backup=str(nvs_file),
        nvs_offset="0x3A0000",
        nvs_size="0x60000",
    )
    net = tmp_path / "hil-network.yaml"
    net.write_text('hil_dut_api_key: "dut-key-0123456789"\n', encoding="utf-8")
    monkeypatch.setattr(config, "NETWORK_FILE", net)
    dutcfg.last_green_dir = str(tmp_path / "store")
    cfg = SimpleNamespace(duts={"A": dutcfg}, supervisor_host="192.0.2.10", dut_api_key="hil-key", supervisor_key="sv-key")
    return SimpleNamespace(tmp=tmp_path, cfg=cfg, dutcfg=dutcfg, fw=fw, kg=kg, nvs=nvs_file, script=script, monkeypatch=monkeypatch)


def verdict(rig, value):
    reports = rig.tmp / "reports"
    reports.mkdir(exist_ok=True)
    (reports / "verdict.json").write_text(json.dumps({"schema": 1, "verdict": value, "build_id": BUILD_ID}), encoding="utf-8")


def go(rig, answers, job_status="", fw=True):
    events = []
    sv = FakeSupervisor(events)
    flasher = Flasher("192.0.2.10", 6638, "esp32s2", esptool_cmd=[sys.executable, str(rig.script)])
    dut = ScriptedDut("A", rig.dutcfg, sv, flasher, answers=answers)
    code = teardown.run_teardown(
        rig.cfg, str(rig.fw) if fw else "", job_status, rig.tmp / "reports", supervisor=sv, dut=dut, dut_key="hil-key"
    )
    return SimpleNamespace(code=code, events=events, dut=dut, calls=esptool_calls(rig), final=final(rig))


def esptool_calls(rig):
    calls = []
    n = 1
    while Path("%s.call%d" % (rig.tmp / "state", n)).exists():
        calls.append(json.loads(Path("%s.call%d" % (rig.tmp / "state", n)).read_text()))
        n += 1
    return calls


def final(rig):
    return json.loads((rig.tmp / "reports" / "final-image.json").read_text())


def regions(call):
    args = call[call.index("write-flash") + 1 :]
    return list(zip(args[0::2], args[1::2]))


def test_green_verdict_keeps_the_commit_image_and_flashes_nothing(rig, capsys):
    verdict(rig, "PASS")
    out = go(rig, [BUILD_ID], job_status="success")
    assert out.code == 0
    assert out.calls == []
    assert [e for e in out.events if e != "release_all"] == []
    assert out.dut.api_calls == ["hil-key"]
    assert (out.final["image"], out.final["version"], out.final["confirmed"]) == ("commit", BUILD_ID, True)
    text = capsys.readouterr().out
    assert LABEL + " lines released" in text and "%s final image: commit (%s)" % (LABEL, BUILD_ID) in text


def test_missing_verdict_flashes_known_good_and_nvs_regions(rig):
    out = go(rig, ["3.2"])
    assert out.code == 0
    assert len(out.calls) == 1
    assert regions(out.calls[0]) == [("0x0", str(rig.kg)), ("0x3A0000", str(rig.nvs))]
    assert out.dut.api_calls == [None]  # the release image has no API encryption
    assert (out.final["image"], out.final["version"], out.final["confirmed"]) == ("known-good", "3.2", True)


def test_failed_job_status_overrides_a_pass_verdict(rig):
    verdict(rig, "PASS")
    out = go(rig, ["3.2"], job_status="failure")
    assert out.final["image"] == "known-good"


def test_fail_verdict_goes_to_known_good(rig):
    verdict(rig, "FAIL")
    out = go(rig, ["3.2"], job_status="failure")
    assert out.final["image"] == "known-good"
    assert json.loads((rig.tmp / "reports" / "verdict.json").read_text())["verdict"] == "FAIL"


def test_known_good_with_encryption_confirms_with_the_hil_key(rig):
    rig.dutcfg.known_good_api_encryption = True
    out = go(rig, ["3.2"])
    assert out.dut.api_calls == ["hil-key"]


def test_release_all_precedes_the_first_press(rig):
    out = go(rig, ["3.2"])
    assert out.events[0] == "release_all"
    presses = [e for e in out.events if isinstance(e, tuple)]
    assert presses and out.events.index(presses[0]) > out.events.index("release_all")
    assert out.events.count("release_all") == 1


def test_known_good_confirm_timeout_flashes_the_commit_image_and_marks_rig_error(rig, capsys):
    verdict(rig, "FAIL")
    out = go(rig, [None, BUILD_ID], job_status="failure")
    assert out.code == 3
    assert len(out.calls) == 2
    assert regions(out.calls[0]) == [("0x0", str(rig.kg)), ("0x3A0000", str(rig.nvs))]
    assert regions(out.calls[1]) == [("0x0", str(rig.fw / "firmware.factory.bin"))]
    assert out.dut.api_calls == [None, "hil-key"]
    assert json.loads((rig.tmp / "reports" / "verdict.json").read_text())["verdict"] == "RIG ERROR"
    assert (out.final["image"], out.final["confirmed"]) == ("commit", True)
    assert LABEL + " final image: commit" in capsys.readouterr().out


def test_commit_image_that_does_not_answer_either_ends_unknown(rig):
    out = go(rig, [None, None])
    assert out.code == 3
    assert (out.final["image"], out.final["confirmed"]) == ("commit", False)


def test_no_firmware_directory_after_a_timeout_ends_unknown(rig):
    out = go(rig, [None], fw=False)
    assert out.code == 3
    assert (out.final["image"], out.final["confirmed"]) == ("unknown", False)
    assert len(out.calls) == 1


def test_sha256_mismatch_raises_before_any_press(rig):
    rig.dutcfg.known_good_sha256 = "0" * 64
    events = []
    sv = FakeSupervisor(events)
    flasher = Flasher("192.0.2.10", 6638, "esp32s2", esptool_cmd=[sys.executable, str(rig.script)])
    dut = ScriptedDut("A", rig.dutcfg, sv, flasher, answers=["3.2"])
    with pytest.raises(RigError, match="sha256"):
        teardown.run_teardown(rig.cfg, str(rig.fw), "failure", rig.tmp / "reports", supervisor=sv, dut=dut, dut_key="k")
    assert [e for e in events if isinstance(e, tuple)] == []
    assert esptool_calls(rig) == []
    assert final(rig)["image"] == "unknown"


def test_wrong_size_nvs_backup_raises_before_any_press(rig):
    rig.nvs.write_bytes(b"\x01" * 10)
    with pytest.raises(RigError, match="nvs_backup"):
        go(rig, ["3.2"])
    assert esptool_calls(rig) == []


def test_no_esptool_argv_contains_an_erase_subcommand(rig):
    verdict(rig, "FAIL")
    go(rig, [None, BUILD_ID], job_status="failure")
    flasher = Flasher("192.0.2.10", 6638, "esp32s2")
    argvs = esptool_calls(rig) + [
        flasher._argv([("0x0", "a"), ("0x3A0000", "b")]),
        flasher._argv_read("0x8000", "0x1000", "c"),
    ]
    assert argvs
    for argv in argvs:
        assert not [a for a in argv if "erase" in a], argv
        assert "--baud" not in argv


def test_the_cli_has_no_erase_command():
    parser = build_parser()
    names = set()

    def walk(p):
        for action in p._actions:
            choices = getattr(action, "choices", None)
            if isinstance(choices, dict):
                for name, sub in choices.items():
                    names.add(name)
                    walk(sub)
            for option in getattr(action, "option_strings", []):
                names.add(option)

    walk(parser)
    assert {"run", "teardown", "known-good", "status", "nvs", "capture", "restore"} <= names
    assert not [n for n in names if "erase" in n]


def test_two_consecutive_runs_give_the_same_final_image(rig):
    first = go(rig, ["3.2"]).final
    second = go(rig, ["3.2"])
    assert second.code == 0
    assert (second.final["image"], second.final["version"], second.final["confirmed"]) == (
        first["image"],
        first["version"],
        first["confirmed"],
    )
    assert second.events.count("release_all") == 1


def test_two_consecutive_runs_after_a_green_run_keep_the_commit_image(rig):
    verdict(rig, "PASS")
    a = go(rig, [BUILD_ID], job_status="success").final
    b = go(rig, [BUILD_ID], job_status="success").final
    assert a["image"] == b["image"] == "commit"
    assert esptool_calls(rig) == []


def test_busy_bridge_is_waited_for_and_the_flash_goes_ahead(rig):
    sv = FakeSupervisor([])
    sv.bridge_busy = 2
    teardown.wait_bridge_free(sv, sleep=lambda s: None)
    assert sv.bridge_busy == 0


def test_summary_file_gets_the_released_and_final_image_lines(rig, tmp_path):
    summary = tmp_path / "summary.md"
    rig.monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    go(rig, ["3.2"])
    text = summary.read_text()
    assert LABEL + " lines released" in text and LABEL + " final image: known-good (3.2)" in text


def test_sigterm_handler_turns_into_keyboard_interrupt_and_runs_finally(tmp_path):
    marker = tmp_path / "marker"
    code = (
        "import signal, sys, time\n"
        "from hil.__main__ import _terminate\n"
        "signal.signal(signal.SIGTERM, _terminate)\n"
        "print('ready', flush=True)\n"
        "try:\n"
        "    time.sleep(30)\n"
        "except KeyboardInterrupt:\n"
        "    print('interrupted', flush=True)\n"
        "    sys.exit(2)\n"
        "finally:\n"
        "    open(sys.argv[1], 'w').write('finalized')\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", code, str(marker)],
        stdout=subprocess.PIPE,
        text=True,
        cwd=Path(__file__).resolve().parents[2],
    )
    assert proc.stdout.readline().strip() == "ready"
    proc.send_signal(signal.SIGTERM)
    out, _ = proc.communicate(timeout=10)
    assert proc.returncode == 2 and "interrupted" in out
    assert marker.read_text() == "finalized"


# ---- last-green store (D-15) ------------------------------------------------------------------

MAIN = "refs/heads/main"
CLAUDE_MAIN = "refs/heads/claude/main"


def seed_store(rig, ref=MAIN):
    """A valid store holding the fw/ commit image, made with the real promote()."""
    from hil import last_green

    verified = manifest_module.load_verified(rig.fw, COMMIT, rig.dutcfg)
    ok, detail = last_green.promote(rig.dutcfg, verified, ref, "7", last_green.network_sha256(config.NETWORK_FILE))
    assert ok, detail
    return Path(rig.dutcfg.last_green_dir)


def stored_image(store):
    return sorted(store.glob("*.bin"))[0]


def test_not_green_with_a_valid_store_restores_the_stored_image_without_nvs(rig, capsys):
    store = seed_store(rig)
    out = go(rig, [BUILD_ID], job_status="failure")
    assert out.code == 0
    assert [regions(c) for c in out.calls] == [[("0x0", str(stored_image(store)))]]
    assert out.dut.api_calls == ["hil-key"]
    assert (out.final["image"], out.final["version"], out.final["confirmed"]) == ("last-green", BUILD_ID, True)
    assert out.final["known_good_source"] == "last-green" and out.final["last_green"]["action"] == "used"
    assert "Known-good source: last-green (%s)" % BUILD_ID in capsys.readouterr().out


def test_corrupted_store_falls_back_to_v160_plus_nvs(rig, capsys):
    store = seed_store(rig)
    image = stored_image(store)
    data = bytearray(image.read_bytes())
    data[3] ^= 0xFF
    image.write_bytes(data)
    out = go(rig, ["3.2"], job_status="failure")
    assert [regions(c) for c in out.calls] == [[("0x0", str(rig.kg)), ("0x3A0000", str(rig.nvs))]]
    assert "Known-good source: v1.6.0 (store invalid: sha256 mismatch)" in capsys.readouterr().out
    assert (out.final["image"], out.final["known_good_source"]) == ("known-good", "v1.6.0")
    assert out.final["last_green"]["action"] == "rejected"


def test_missing_store_uses_v160_and_says_why(rig, capsys):
    out = go(rig, ["3.2"], job_status="failure")
    assert "Known-good source: v1.6.0 (store missing)" in capsys.readouterr().out
    assert out.final["image"] == "known-good"


def test_last_green_confirmation_timeout_goes_to_the_commit_image_never_to_v160(rig):
    store = seed_store(rig)
    verdict(rig, "FAIL")
    out = go(rig, [None, BUILD_ID], job_status="failure")
    assert out.code == 3
    assert [regions(c) for c in out.calls] == [
        [("0x0", str(stored_image(store)))],
        [("0x0", str(rig.fw / "firmware.factory.bin"))],
    ]
    assert str(rig.kg) not in json.dumps(out.calls)
    assert json.loads((rig.tmp / "reports" / "verdict.json").read_text())["verdict"] == "RIG ERROR"
    assert (out.final["image"], out.final["confirmed"]) == ("commit", True)


def test_last_green_that_reports_another_build_is_not_confirmed(rig):
    seed_store(rig)
    out = go(rig, ["3.2", BUILD_ID], job_status="failure")
    assert out.code == 3 and len(out.calls) == 2
    assert out.final["image"] == "commit"


def test_two_non_green_teardowns_restore_the_same_stored_image(rig):
    seed_store(rig)
    a = go(rig, [BUILD_ID], job_status="failure")
    b = go(rig, [BUILD_ID], job_status="failure")
    assert a.final["image"] == b.final["image"] == "last-green"
    assert regions(b.calls[-1]) == regions(a.calls[0])


def count_promotes(rig, results=None):
    from hil import last_green

    calls = []
    real = last_green.promote

    def wrapper(*args, **kwargs):
        calls.append(args)
        return real(*args, **kwargs) if results is None else results

    rig.monkeypatch.setattr(teardown.last_green, "promote", wrapper)
    return calls


def test_green_main_promotes_once_after_a_matching_confirmation(rig, capsys):
    verdict(rig, "PASS")
    rig.monkeypatch.setenv("GITHUB_REF", MAIN)
    rig.monkeypatch.setenv("GITHUB_RUN_ID", "99")
    calls = count_promotes(rig)
    out = go(rig, [BUILD_ID], job_status="success")
    assert out.code == 0 and len(calls) == 1
    assert out.dut.api_calls == ["hil-key"]
    assert "Last-green store: updated (%s)" % BUILD_ID in capsys.readouterr().out
    assert out.final["last_green"] == {"action": "updated", "detail": BUILD_ID}
    stored = json.loads((Path(rig.dutcfg.last_green_dir) / "manifest.json").read_text())
    assert (stored["ref"], stored["run_id"], stored["build_id"]) == (MAIN, "99", BUILD_ID)


def test_second_green_main_teardown_reports_already(rig, capsys):
    verdict(rig, "PASS")
    rig.monkeypatch.setenv("GITHUB_REF", MAIN)
    go(rig, [BUILD_ID], job_status="success")
    capsys.readouterr()
    out = go(rig, [BUILD_ID], job_status="success")
    assert "Last-green store: unchanged (already %s)" % BUILD_ID in capsys.readouterr().out
    assert out.final["last_green"]["action"] == "unchanged"


def test_green_on_claude_main_never_stores(rig, capsys):
    verdict(rig, "PASS")
    rig.monkeypatch.setenv("GITHUB_REF", CLAUDE_MAIN)
    out = go(rig, [BUILD_ID], job_status="success")
    assert "Last-green store: unchanged (ref is not refs/heads/main)" in capsys.readouterr().out
    assert not Path(rig.dutcfg.last_green_dir).exists()
    assert out.code == 0


def test_green_without_a_ref_never_stores(rig, capsys):
    verdict(rig, "PASS")
    go(rig, [BUILD_ID], job_status="success")
    assert "Last-green store: unchanged (ref is not refs/heads/main)" in capsys.readouterr().out
    assert not Path(rig.dutcfg.last_green_dir).exists()


def test_green_with_a_build_id_mismatch_never_stores(rig, capsys):
    verdict(rig, "PASS")
    rig.monkeypatch.setenv("GITHUB_REF", MAIN)
    calls = count_promotes(rig)
    out = go(rig, ["3.2+hil." + "f" * 12], job_status="success")
    assert calls == []
    assert "Last-green store: unchanged (build ID not confirmed)" in capsys.readouterr().out
    assert not Path(rig.dutcfg.last_green_dir).exists()
    assert out.code == 3 and out.final["confirmed"] is False


def test_failed_promotion_warns_in_actions_and_changes_no_verdict_or_exit_code(rig, capsys):
    verdict(rig, "PASS")
    rig.monkeypatch.setenv("GITHUB_REF", MAIN)
    rig.monkeypatch.setenv("GITHUB_ACTIONS", "true")
    count_promotes(rig, results=(False, "PermissionError"))
    out = go(rig, [BUILD_ID], job_status="success")
    text = capsys.readouterr().out
    assert "::warning" in text and "Last-green store: unchanged (PermissionError)" in text
    assert out.code == 0
    assert json.loads((rig.tmp / "reports" / "verdict.json").read_text())["verdict"] == "PASS"


def test_a_promote_that_raises_is_contained(rig, capsys):
    verdict(rig, "PASS")
    rig.monkeypatch.setenv("GITHUB_REF", MAIN)

    def boom(*_a, **_k):
        raise ValueError("unexpected")

    rig.monkeypatch.setattr(teardown.last_green, "promote", boom)
    out = go(rig, [BUILD_ID], job_status="success")
    assert out.code == 0
    assert "Last-green store: unchanged (ValueError)" in capsys.readouterr().out
