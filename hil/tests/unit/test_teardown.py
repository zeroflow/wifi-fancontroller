"""Teardown state machine with a fake supervisor, a fake esptool script and a scripted API (no hardware)."""

import collections
import hashlib
import json
import signal
import subprocess
import sys
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
QC_ID = "3.2+qc." + "a" * 12
CANARY_ID = "3.2+canary." + "a" * 12
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


def _entry(role, build_id, final, ota_file, ota_bytes, **extra):
    entry = {
        "role": role,
        "rev": "3.2",
        "chip": "esp32s2",
        "offset": "0x0",
        "framework": "arduino",
        "build_id": build_id,
        "final": final,
        "esphome_name": "fancontroller-%s-r3-2" % role,
        "ota_file": ota_file,
        "ota_sha256": hashlib.sha256(ota_bytes).hexdigest(),
    }
    entry.update(extra)
    return entry


def write_firmware_dir(fw, commit_final=True):
    """A schema-2 firmware directory: the commit image plus a qc-auto and a canary entry."""
    files = {
        "firmware.factory.bin": b"commit image",
        "firmware.ota.bin": b"commit ota image",
        "qc-auto-3.2.ota.bin": b"qc-auto ota image",
        "canary-3.2.ota.bin": b"canary ota image",
    }
    for name, data in files.items():
        (fw / name).write_bytes(data)
    images = [
        _entry("commit", BUILD_ID, commit_final, "firmware.ota.bin", files["firmware.ota.bin"],
               file="firmware.factory.bin", sha256=hashlib.sha256(files["firmware.factory.bin"]).hexdigest()),
        _entry("qc-auto", QC_ID, False, "qc-auto-3.2.ota.bin", files["qc-auto-3.2.ota.bin"], fan_hz=25000),
        _entry("canary", CANARY_ID, False, "canary-3.2.ota.bin", files["canary-3.2.ota.bin"], fan_hz=25000),
    ]
    (fw / "manifest.json").write_text(
        json.dumps({"schema": 2, "commit": COMMIT, "build_id": BUILD_ID, "esphome_version": "2026.10.1", "images": images}),
        encoding="utf-8",
    )


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
    write_firmware_dir(fw)
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
        nvs_release_tag="v1.6.0",
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
    verdict(rig, "PASS")  # a red job status makes it not green; a recorded FAIL is covered below (D-46)
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


def test_a_v160_image_that_does_not_verify_falls_back_to_the_commit_image(rig, capsys):
    """WR-03: an unverifiable known-good image no longer stops teardown; D-09's commit fallback runs."""
    rig.dutcfg.known_good_sha256 = "0" * 64
    out = go(rig, [BUILD_ID], job_status="failure")
    assert out.code == 3
    assert [regions(c) for c in out.calls] == [[("0x0", str(rig.fw / "firmware.factory.bin"))]]
    assert any(step.startswith("known-good image does not verify") for step in out.final["steps"])
    assert (out.final["image"], out.final["version"], out.final["confirmed"]) == ("commit", BUILD_ID, True)
    assert "known-good image does not verify" in capsys.readouterr().out
    assert json.loads((rig.tmp / "reports" / "verdict.json").read_text())["verdict"] == "RIG ERROR"


def test_the_known_good_image_is_verified_before_any_known_good_press(rig):
    rig.dutcfg.known_good_sha256 = "0" * 64
    out = go(rig, [BUILD_ID], job_status="failure")
    assert all(str(rig.kg) not in call for call in out.calls)


def test_a_wrong_size_nvs_backup_falls_back_to_the_commit_image(rig):
    rig.nvs.write_bytes(b"\x01" * 10)
    out = go(rig, [BUILD_ID], job_status="failure")
    assert out.code == 3
    assert [regions(c) for c in out.calls] == [[("0x0", str(rig.fw / "firmware.factory.bin"))]]
    assert any("nvs_backup" in step for step in out.final["steps"])


def test_teardown_chooses_through_the_shared_selector(rig, monkeypatch):
    from hil import known_good

    calls = []
    real = known_good.select

    def spy(*args, **kwargs):
        calls.append(args)
        return real(*args, **kwargs)

    monkeypatch.setattr(known_good, "select", spy)
    go(rig, ["3.2"], job_status="failure")
    assert len(calls) == 1


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
    verdict(rig, "PASS")  # red job status; a recorded FAIL keeps FAIL (D-46)
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


class BrokenSupervisor(FakeSupervisor):
    """release_all fails the way a dropped API connection does: a non-RigError exception."""

    def release_all(self):
        raise ConnectionResetError("link down")


def test_a_non_rig_error_from_release_all_still_writes_final_image_and_exits_3(rig, capsys):
    verdict(rig, "FAIL")
    sv = BrokenSupervisor([])
    flasher = Flasher("192.0.2.10", 6638, "esp32s2", esptool_cmd=[sys.executable, str(rig.script)])
    dut = ScriptedDut("A", rig.dutcfg, sv, flasher, answers=["3.2"])
    code = teardown.run_teardown(
        rig.cfg, str(rig.fw), "failure", rig.tmp / "reports", supervisor=sv, dut=dut, dut_key="hil-key"
    )
    assert code == 3
    assert "lines not released" in final(rig)["steps"]
    assert esptool_calls(rig) == []  # no flash while lines may still be asserted
    assert "ConnectionResetError" in capsys.readouterr().out


def test_cmd_teardown_catches_a_late_non_rig_error_and_writes_final_image(rig, monkeypatch):
    from hil import __main__ as entry

    class Boom(Exception):
        pass

    def explode(*_args, **_kwargs):
        raise Boom("secret-looking text must not be printed")

    monkeypatch.setattr(entry, "load_rig", lambda: SimpleNamespace(duts={}, supervisor_host="h", supervisor_key="k", dut_api_key="d"))
    monkeypatch.setattr(entry, "_rig_dut", lambda _rig: (SimpleNamespace(close=lambda: None), None))
    monkeypatch.setattr(entry.teardown, "run_teardown", explode)
    monkeypatch.setattr(entry, "redact_reports", lambda _rig: None)
    assert entry.cmd_teardown() == 3
    state = final(rig)
    assert state["steps"] == ["teardown stopped: Boom"]


def written_verdict(rig):
    return json.loads((rig.tmp / "reports" / "verdict.json").read_text())["verdict"]


def test_green_run_with_an_unconfirmed_commit_image_rewrites_the_verdict(rig, capsys):
    verdict(rig, "PASS")
    out = go(rig, [None], job_status="success")
    assert out.code == 3
    assert written_verdict(rig) == "RIG ERROR"
    assert "RIG ERROR" in capsys.readouterr().out


def test_green_run_with_a_build_id_mismatch_rewrites_the_verdict(rig):
    verdict(rig, "PASS")
    out = go(rig, ["3.2+hil." + "f" * 12], job_status="success")
    assert out.code == 3
    assert written_verdict(rig) == "RIG ERROR"


def test_green_run_whose_manifest_no_longer_verifies_rewrites_the_verdict(rig):
    verdict(rig, "PASS")
    out = go(rig, [BUILD_ID], job_status="success", fw=False)
    assert out.code == 3
    assert written_verdict(rig) == "RIG ERROR"


def test_a_confirmed_green_run_keeps_its_pass_verdict(rig):
    verdict(rig, "PASS")
    out = go(rig, [BUILD_ID], job_status="success")
    assert out.code == 0
    assert written_verdict(rig) == "PASS"


# ---- D-25: a qc-auto or canary image is never a final image --------------------------------


@pytest.mark.parametrize("role,build_id", [("qc-auto", QC_ID), ("canary", CANARY_ID)])
def test_green_run_that_ends_on_a_non_final_image_is_a_rig_error(rig, capsys, role, build_id):
    verdict(rig, "PASS")
    rig.monkeypatch.setenv("GITHUB_REF", MAIN)
    calls = count_promotes(rig)
    out = go(rig, [build_id], job_status="success")
    text = capsys.readouterr().out
    assert out.code == 3
    assert out.final["confirmed"] is False
    assert written_verdict(rig) == "RIG ERROR"
    assert "RIG ERROR: %s runs the %s image (%s), not a final image" % (LABEL, role, build_id) in text
    assert calls == []
    assert not Path(rig.dutcfg.last_green_dir).exists()


def test_a_wrong_but_unlisted_build_id_does_not_claim_a_non_final_image(rig, capsys):
    verdict(rig, "PASS")
    out = go(rig, ["3.2+qc." + "f" * 12], job_status="success")
    assert out.code == 3
    assert "not a final image" not in capsys.readouterr().out


def test_load_commit_manifest_returns_none_when_the_commit_entry_is_not_final(rig):
    final_image = manifest_module.load_verified(rig.fw, COMMIT, rig.dutcfg).image("commit")
    not_final = manifest_module.ManifestImage(**{**final_image.__dict__, "final": False})
    bad = manifest_module.Manifest(commit=COMMIT, build_id=BUILD_ID, images={("commit", "3.2"): not_final})
    rig.monkeypatch.setattr(manifest_module, "load_verified", lambda *a, **k: bad)
    assert teardown.load_commit_manifest(str(rig.fw), rig.dutcfg) is None


def test_a_non_final_commit_entry_takes_the_not_confirmed_path_after_a_green_run(rig):
    verdict(rig, "PASS")
    final_image = manifest_module.load_verified(rig.fw, COMMIT, rig.dutcfg).image("commit")
    not_final = manifest_module.ManifestImage(**{**final_image.__dict__, "final": False})
    bad = manifest_module.Manifest(commit=COMMIT, build_id=BUILD_ID, images={("commit", "3.2"): not_final})
    rig.monkeypatch.setattr(manifest_module, "load_verified", lambda *a, **k: bad)
    out = go(rig, [BUILD_ID], job_status="success")
    assert out.code == 3
    assert written_verdict(rig) == "RIG ERROR"


def test_the_flash_commit_image_fallback_refuses_a_non_final_commit_entry(rig):
    verdict(rig, "FAIL")
    final_image = manifest_module.load_verified(rig.fw, COMMIT, rig.dutcfg).image("commit")
    not_final = manifest_module.ManifestImage(**{**final_image.__dict__, "final": False})
    bad = manifest_module.Manifest(commit=COMMIT, build_id=BUILD_ID, images={("commit", "3.2"): not_final})
    rig.monkeypatch.setattr(manifest_module, "load_verified", lambda *a, **k: bad)
    out = go(rig, [None, None], job_status="failure")
    assert out.code == 3
    flashed = [r for call in out.calls for r in regions(call)]
    assert all(str(rig.fw / "firmware.factory.bin") != path for _offset, path in flashed)


def rig_errors(rig):
    return json.loads((rig.tmp / "reports" / "rig-errors.json").read_text())


def test_a_fail_verdict_survives_a_failed_known_good_attempt_and_the_cause_is_recorded(rig, capsys):
    verdict(rig, "FAIL")
    reports = rig.tmp / "reports"
    (reports / "rig-errors.json").write_text(json.dumps([{"nodeid": "t::a", "kind": "RigError", "message": "earlier"}]))
    out = go(rig, [None, BUILD_ID], job_status="failure")
    assert out.code == 3  # the Teardown step is still red
    assert written_verdict(rig) == "FAIL"
    assert rig_errors(rig) == [
        {"nodeid": "t::a", "kind": "RigError", "message": "earlier"},
        {"nodeid": None, "kind": "Teardown", "message": "known-good image did not come back"},
    ]
    assert "WARNING: rig condition after a FAIL run: known-good image did not come back" in capsys.readouterr().out


def test_a_fail_verdict_without_a_rig_errors_file_gets_one_with_the_teardown_entry(rig):
    verdict(rig, "FAIL")
    out = go(rig, [None, None], job_status="failure")
    assert out.code == 3
    assert written_verdict(rig) == "FAIL"
    assert [e["kind"] for e in rig_errors(rig)] == ["Teardown"]


def test_a_pass_verdict_with_an_unconfirmed_commit_image_still_becomes_rig_error(rig):
    verdict(rig, "PASS")
    out = go(rig, ["wrong-build"], job_status="success")
    assert out.code == 3
    assert written_verdict(rig) == "RIG ERROR"
    assert [e["kind"] for e in rig_errors(rig)] == ["Teardown"]  # 03-15: every rewrite records its cause


# ------------------------------------------------- watchdog counters across the run (03-08, D-47, D-48)

RELEASES = contract.WATCHDOG_RELEASES
LABEL_B = contract.SERIAL_CONNECTED["B"].removesuffix(" Serial Connected")


class CountingSupervisor(FakeSupervisor):
    """FakeSupervisor with the two Watchdog Releases sensors (None: no value; an exception: read fails)."""

    def __init__(self, events, counts):
        super().__init__(events)
        self.counts = counts

    def sensor_value(self, name):
        value = self.counts[name]
        if isinstance(value, Exception):
            raise value
        return value


def preflight_record(rig, start, commit=COMMIT):
    reports = rig.tmp / "reports"
    reports.mkdir(exist_ok=True)
    (reports / "preflight.json").write_text(json.dumps({"schema": 1, "commit": commit, "watchdog_start": start}), encoding="utf-8")


def go_counting(rig, counts, answers=(BUILD_ID,), job_status="success"):
    events = []
    sv = CountingSupervisor(events, counts)
    flasher = Flasher("192.0.2.10", 6638, "esp32s2", esptool_cmd=[sys.executable, str(rig.script)])
    dut = ScriptedDut("A", rig.dutcfg, sv, flasher, answers=list(answers))
    code = teardown.run_teardown(rig.cfg, str(rig.fw), job_status, rig.tmp / "reports", supervisor=sv, dut=dut, dut_key="hil-key")
    return code, json.loads((rig.tmp / "reports" / "watchdog.json").read_text())


def test_bridge_wait_covers_the_keepalive_eviction():
    assert teardown.BRIDGE_FREE_S == 40


def test_teardown_writes_the_counter_comparison_with_the_preflight_start(rig, capsys):
    verdict(rig, "PASS")
    preflight_record(rig, {"A": 6, "B": 0})
    code, data = go_counting(rig, {RELEASES["A"]: 6.0, RELEASES["B"]: 1.0})
    assert code == 0
    assert data == {"start": {"A": 6, "B": 0}, "end": {"A": 6, "B": 1}, "delta": {"A": 0, "B": 1}}
    out = capsys.readouterr().out
    assert "WARNING: supervisor watchdog released %s lines 1 time(s) during this run" % LABEL_B in out


def test_a_rise_is_an_actions_warning_under_github_actions(rig, capsys):
    rig.monkeypatch.setenv("GITHUB_ACTIONS", "true")
    verdict(rig, "PASS")
    preflight_record(rig, {"A": 6, "B": 0})
    go_counting(rig, {RELEASES["A"]: 8.0, RELEASES["B"]: 0.0})
    out = capsys.readouterr().out
    assert "::warning title=HIL watchdog::supervisor watchdog released %s lines 2 time(s) during this run" % LABEL in out
    assert "title=HIL watchdog::supervisor watchdog released %s" % LABEL_B not in out


def test_no_rise_says_nothing_about_the_watchdog(rig, capsys):
    verdict(rig, "PASS")
    preflight_record(rig, {"A": 6, "B": 0})
    _code, data = go_counting(rig, {RELEASES["A"]: 6.0, RELEASES["B"]: 0.0})
    assert data["delta"] == {"A": 0, "B": 0}
    assert "watchdog" not in capsys.readouterr().out


@pytest.mark.parametrize("prepare", ["missing", "other commit"])
def test_without_a_preflight_start_for_this_commit_the_delta_is_not_recorded(rig, prepare):
    verdict(rig, "PASS")
    if prepare == "other commit":
        preflight_record(rig, {"A": 0, "B": 0}, commit="b" * 40)
    code, data = go_counting(rig, {RELEASES["A"]: 6.0, RELEASES["B"]: 1.0})
    assert code == 0
    assert data == {"start": None, "end": {"A": 6, "B": 1}, "delta": {"A": None, "B": None}}


def test_a_counter_read_failure_is_not_recorded_and_never_changes_the_exit_code(rig):
    verdict(rig, "PASS")
    preflight_record(rig, {"A": 6, "B": 0})
    code, data = go_counting(rig, {RELEASES["A"]: RigError("entity missing"), RELEASES["B"]: None})
    assert code == 0
    assert data == {"start": {"A": 6, "B": 0}, "end": {"A": None, "B": None}, "delta": {"A": None, "B": None}}


def test_the_counters_are_recorded_after_a_not_green_teardown_too(rig):
    verdict(rig, "FAIL")
    preflight_record(rig, {"A": 6, "B": 0})
    _code, data = go_counting(rig, {RELEASES["A"]: 6.0, RELEASES["B"]: 0.0}, answers=["3.2"], job_status="failure")
    assert data["delta"] == {"A": 0, "B": 0}


def test_a_fake_supervisor_without_sensors_still_tears_down(rig):
    verdict(rig, "PASS")
    out = go(rig, [BUILD_ID], job_status="success")
    assert out.code == 0
    data = json.loads((rig.tmp / "reports" / "watchdog.json").read_text())
    assert data["end"] == {"A": None, "B": None}


# ---- 03-15: every teardown exit-3 path ends RIG ERROR with its heading and annotation (WR-06, D-45, D-46) ----

ANNOTATION = "::error title=RIG ERROR::"


class ReleaseRigError(FakeSupervisor):
    """release_all fails with the curated RigError a switch command raises."""

    def release_all(self):
        raise RigError("switch command failed")


def teardown_with(rig, supervisor, job_status="success"):
    flasher = Flasher("192.0.2.10", 6638, "esp32s2", esptool_cmd=[sys.executable, str(rig.script)])
    dut = ScriptedDut("A", rig.dutcfg, supervisor, flasher, answers=[BUILD_ID])
    return teardown.run_teardown(
        rig.cfg, str(rig.fw), job_status, rig.tmp / "reports", supervisor=supervisor, dut=dut, dut_key="hil-key"
    )


def verdict_json(rig):
    return json.loads((rig.tmp / "reports" / "verdict.json").read_text())


def annotations(text):
    return [line for line in text.splitlines() if line.startswith(ANNOTATION)]


def heading(rig):
    from hil import summary

    return summary.write(rig.tmp / "reports", None, []).splitlines()[0]


@pytest.mark.parametrize("supervisor_class", [ReleaseRigError, BrokenSupervisor])
def test_a_pass_run_whose_lines_cannot_be_released_ends_rig_error_with_heading_and_annotation(rig, capsys, supervisor_class):
    rig.monkeypatch.setenv("GITHUB_ACTIONS", "true")
    verdict(rig, "PASS")
    code = teardown_with(rig, supervisor_class([]))
    text = capsys.readouterr().out
    assert code == 3
    assert (verdict_json(rig)["verdict"], verdict_json(rig)["reason"]) == ("RIG ERROR", "teardown: lines not released")
    assert rig_errors(rig) == [{"nodeid": None, "kind": "Teardown", "message": "teardown: lines not released"}]
    assert esptool_calls(rig) == []
    assert annotations(text) == [ANNOTATION + "teardown: lines not released"]
    assert "link down" not in text
    assert heading(rig) == "## HIL run: RIG ERROR"


def test_a_fail_run_whose_lines_cannot_be_released_stays_fail(rig, capsys):
    rig.monkeypatch.setenv("GITHUB_ACTIONS", "true")
    verdict(rig, "FAIL")
    code = teardown_with(rig, BrokenSupervisor([]), job_status="failure")
    assert code == 3
    assert verdict_json(rig)["verdict"] == "FAIL"
    assert [e["kind"] for e in rig_errors(rig)] == ["Teardown"]
    assert annotations(capsys.readouterr().out) == []
    assert heading(rig) == "## HIL run: FAIL"


def test_an_earlier_rig_error_keeps_its_reason_and_gains_the_teardown_entry_and_annotation(rig, capsys):
    rig.monkeypatch.setenv("GITHUB_ACTIONS", "true")
    reports = rig.tmp / "reports"
    reports.mkdir()
    (reports / "verdict.json").write_text(json.dumps({"schema": 1, "verdict": "RIG ERROR", "reason": "preflight: X"}))
    code = teardown_with(rig, BrokenSupervisor([]), job_status="failure")
    assert code == 3
    assert (verdict_json(rig)["verdict"], verdict_json(rig)["reason"]) == ("RIG ERROR", "preflight: X")
    assert [e["kind"] for e in rig_errors(rig)] == ["Teardown"]
    assert annotations(capsys.readouterr().out) == [ANNOTATION + "teardown: lines not released"]


def test_a_missing_verdict_json_becomes_rig_error_when_the_lines_cannot_be_released(rig):
    code = teardown_with(rig, BrokenSupervisor([]), job_status="")
    assert code == 3
    assert (verdict_json(rig)["verdict"], verdict_json(rig)["reason"]) == ("RIG ERROR", "teardown: lines not released")


def test_no_annotation_is_printed_outside_github_actions(rig, capsys):
    verdict(rig, "PASS")
    assert teardown_with(rig, BrokenSupervisor([])) == 3
    assert ANNOTATION not in capsys.readouterr().out
    assert written_verdict(rig) == "RIG ERROR"


def test_an_unconfirmed_green_run_prints_one_annotation_and_records_a_teardown_entry(rig, capsys):
    rig.monkeypatch.setenv("GITHUB_ACTIONS", "true")
    verdict(rig, "PASS")
    out = go(rig, [None], job_status="success")
    assert out.code == 3
    assert annotations(capsys.readouterr().out) == [ANNOTATION + "teardown: commit image not confirmed after a green run"]
    assert verdict_json(rig)["reason"] == "teardown: commit image not confirmed after a green run"
    assert [e["kind"] for e in rig_errors(rig)] == ["Teardown"]


def test_a_known_good_fallback_prints_one_annotation_and_keeps_its_exit_code_and_image(rig, capsys):
    rig.monkeypatch.setenv("GITHUB_ACTIONS", "true")
    verdict(rig, "PASS")
    out = go(rig, [None, BUILD_ID], job_status="failure")
    assert out.code == 3
    assert (out.final["image"], out.final["confirmed"]) == ("commit", True)
    assert annotations(capsys.readouterr().out) == [ANNOTATION + "teardown: known-good image did not come back"]
    assert [e["kind"] for e in rig_errors(rig)] == ["Teardown"]


def test_an_unverifiable_known_good_image_prints_one_annotation(rig, capsys):
    rig.monkeypatch.setenv("GITHUB_ACTIONS", "true")
    rig.dutcfg.known_good_sha256 = "0" * 64
    verdict(rig, "PASS")
    out = go(rig, [BUILD_ID], job_status="failure")
    assert out.code == 3
    assert annotations(capsys.readouterr().out) == [ANNOTATION + "teardown: known-good image does not verify"]


def test_a_confirmed_green_run_prints_no_rig_error_annotation_and_keeps_pass(rig, capsys):
    rig.monkeypatch.setenv("GITHUB_ACTIONS", "true")
    verdict(rig, "PASS")
    out = go(rig, [BUILD_ID], job_status="success")
    assert out.code == 0
    assert annotations(capsys.readouterr().out) == []
    assert written_verdict(rig) == "PASS"


def test_a_fail_run_with_a_failed_known_good_attempt_prints_no_rig_error_annotation(rig, capsys):
    rig.monkeypatch.setenv("GITHUB_ACTIONS", "true")
    verdict(rig, "FAIL")
    out = go(rig, [None, None], job_status="failure")
    assert out.code == 3
    assert written_verdict(rig) == "FAIL"
    assert annotations(capsys.readouterr().out) == []


# cmd_teardown: the stage causes (WR-06)


class Boom(Exception):
    pass


@pytest.fixture
def cmd(rig, monkeypatch):
    """cmd_teardown in-process: a PASS verdict.json, Actions on, summary writing real but unmasked."""
    from hil import __main__ as entry

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("HIL_JOB_STATUS", "success")
    verdict(rig, "PASS")
    monkeypatch.setattr(entry.config, "mask_literals", lambda _rig: [])
    monkeypatch.setattr(entry, "redact_reports", lambda _rig: None)
    fake_rig = SimpleNamespace(duts={}, supervisor_host="h", supervisor_key="k", dut_api_key="d")
    monkeypatch.setattr(entry, "load_rig", lambda: fake_rig)
    monkeypatch.setattr(entry, "_rig_dut", lambda _rig: (SimpleNamespace(close=lambda: None), None))
    return entry


def summary_head(rig):
    return (rig.tmp / "reports" / "raw" / "summary.md").read_text().splitlines()[0]


def raise_(exc):
    def raiser(*_args, **_kwargs):
        raise exc

    return raiser


def test_cmd_teardown_that_cannot_reach_the_supervisor_ends_rig_error(rig, cmd, monkeypatch, capsys):
    monkeypatch.setattr(cmd, "_rig_dut", raise_(RigError("supervisor connection failed (ConnectionRefusedError)")))
    assert cmd.cmd_teardown() == 3
    assert (verdict_json(rig)["verdict"], verdict_json(rig)["reason"]) == ("RIG ERROR", "teardown: supervisor unreachable")
    assert annotations(capsys.readouterr().out) == [ANNOTATION + "teardown: supervisor unreachable"]
    assert summary_head(rig) == "## HIL run: RIG ERROR"
    assert final(rig)["steps"]


def test_cmd_teardown_without_a_rig_configuration_ends_rig_error_without_a_summary(rig, cmd, monkeypatch, capsys):
    monkeypatch.setattr(cmd, "load_rig", raise_(RigError("HIL_RIG_CONFIG is not set")))
    assert cmd.cmd_teardown() == 3
    assert (verdict_json(rig)["verdict"], verdict_json(rig)["reason"]) == ("RIG ERROR", "teardown: rig configuration not loaded")
    assert annotations(capsys.readouterr().out) == [ANNOTATION + "teardown: rig configuration not loaded"]
    assert not (rig.tmp / "reports" / "raw" / "summary.md").exists()


def test_cmd_teardown_with_a_rig_error_out_of_run_teardown_names_the_class(rig, cmd, monkeypatch, capsys):
    monkeypatch.setattr(cmd.teardown, "run_teardown", raise_(RigError("flash failed")))
    assert cmd.cmd_teardown() == 3
    assert verdict_json(rig)["reason"] == "teardown: stopped (RigError)"
    assert annotations(capsys.readouterr().out) == [ANNOTATION + "teardown: stopped (RigError)"]
    assert summary_head(rig) == "## HIL run: RIG ERROR"


def test_cmd_teardown_with_an_unexpected_exception_prints_the_class_never_the_text(rig, cmd, monkeypatch, capsys):
    monkeypatch.setattr(cmd.teardown, "run_teardown", raise_(Boom("secret-looking text must not be printed")))
    assert cmd.cmd_teardown() == 3
    text = capsys.readouterr().out
    assert verdict_json(rig)["reason"] == "teardown: stopped unexpectedly (Boom)"
    assert annotations(text) == [ANNOTATION + "teardown: stopped unexpectedly (Boom)"]
    assert "secret-looking" not in text
    assert "secret-looking" not in (rig.tmp / "reports" / "verdict.json").read_text()
    assert summary_head(rig) == "## HIL run: RIG ERROR"


def test_cmd_teardown_keeps_a_recorded_fail_when_it_cannot_reach_the_supervisor(rig, cmd, monkeypatch, capsys):
    verdict(rig, "FAIL")
    monkeypatch.setattr(cmd, "_rig_dut", raise_(RigError("supervisor connection failed (TimeoutError)")))
    assert cmd.cmd_teardown() == 3
    assert verdict_json(rig)["verdict"] == "FAIL"
    assert [e["kind"] for e in rig_errors(rig)] == ["Teardown"]
    assert annotations(capsys.readouterr().out) == []
    assert summary_head(rig) == "## HIL run: FAIL"
