"""D-39: the rollback state of every OTA boot, each read from its own window, and the broken row of D-41."""

import hashlib
import json
from types import SimpleNamespace

import pytest

from hil import dut as dut_module
from hil import rollback
from hil.dut import Dut
from hil.ota import OtaResult

ESC = "\x1b"
SUPPORTED = ESC + "[0;35m[C][safe_mode:079]:   Bootloader rollback: supported" + ESC + "[0m\r\n"
UNKNOWN = "[C][safe_mode:079]:   Bootloader rollback: support unknown\r\n"
NOT_SUPPORTED = "[C][safe_mode:079]:   Bootloader rollback: not supported\r\n"
DETECTED = "[W][safe_mode:088]: OTA rollback detected! Rolled back from partition 'app1'\r\n"
BANNER = "rst:0xc (RTC_SW_CPU_RST),boot:0x8 (SPI_FAST_FLASH_BOOT)\r\n"
DOWNLOAD = "rst:0x1 (POWERON),boot:0x0 (DOWNLOAD(USB/UART0/1/SPI))\r\n"
VALID = "[I][hil:050]: HIL broken image OTA state: valid\r\n"
KEY = "KEY"


# state_in / rolled_back -----------------------------------------------------------------


@pytest.mark.parametrize(
    "text, state",
    [
        (SUPPORTED, "supported"),
        (UNKNOWN, "support unknown"),
        (NOT_SUPPORTED, "not supported"),
        ("Bootloader rollback: supported", "supported"),
    ],
)
def test_state_in_reads_the_three_states_with_or_without_ansi_and_prefix(text, state):
    assert rollback.state_in(BANNER + text) == state


def test_state_in_takes_the_first_line_of_the_window():
    assert rollback.state_in(SUPPORTED + UNKNOWN) == "supported"


@pytest.mark.parametrize("text", ["", None, BANNER, "[C][safe_mode:079]:   Bootloader rollback: maybe\r\n"])
def test_state_in_is_none_without_a_state_line(text):
    assert rollback.state_in(text) is None


def test_rolled_back_needs_the_detected_line():
    assert rollback.rolled_back(BANNER + DETECTED) is True
    assert rollback.rolled_back(BANNER + SUPPORTED) is False
    assert rollback.rolled_back(None) is False


# rows -----------------------------------------------------------------------------------


def window(label, role, end_mark, until_mark, uptime, proof="uart0 banner", end_at=1.0, until_at=None):
    return {
        "label": label, "role": role, "ok": True, "reboot_proof": proof, "end_mark": end_mark,
        "until_mark": until_mark, "old_uptime_s": uptime, "end_at": end_at, "until_at": until_at,
    }


def test_each_row_is_parsed_from_its_own_window_with_label_role_and_old_uptime():
    texts = {"ota_end_qc-auto": UNKNOWN, "ota_end_canary": UNKNOWN, "ota_end_commit": SUPPORTED}
    windows = [
        window("qc-auto", "qc-auto", "ota_end_qc-auto", "ota_start_canary", 120.4),
        window("canary", "canary", "ota_end_canary", "ota_start_commit", 75.0),
        window("commit", "commit", "ota_end_commit", None, 50.2),
    ]
    found = rollback.rows(windows, lambda e: texts[e["end_mark"]])
    assert [(r["label"], r["role"], r["state"], r["source"], r["old_uptime_s"]) for r in found] == [
        ("qc-auto", "qc-auto", "support unknown", "uart0", 120.4),
        ("canary", "canary", "support unknown", "uart0", 75.0),
        ("commit", "commit", "supported", "uart0", 50.2),
    ]
    assert all(r["image_state"] is None and r["rolled_back"] is False for r in found)


def test_the_broken_row_carries_its_image_state_and_no_rollback_state():
    """D-41: the broken image prints its OTA state and no rollback line; the commit boot after the flash is outside."""
    log = {"broken": BANNER + VALID, "after": BANNER + UNKNOWN}

    def uart(entry):
        # The window ends at the Bootloader press; the commit boot of the recovery flash lies beyond it.
        return log["broken"] if entry["until_mark"] == "bootloader_6" else log["broken"] + log["after"]

    (row,) = rollback.rows([window("broken", "broken", "ota_end_broken", "bootloader_6", 40.0)], uart)
    assert row["state"] is None and row["image_state"] == "valid" and row["source"] == "uart0"


def test_the_upgrade_is_read_from_the_api_window_when_uart0_is_dark():
    entry = window("baseline_commit", "commit", "ota_end_baseline_commit", "bootloader_3", 80.0, proof="build id")
    (row,) = rollback.rows([entry], lambda e: "", lambda e: SUPPORTED)
    assert (row["state"], row["source"], row["old_uptime_s"]) == ("supported", "api", 80.0)


def test_the_upgrade_without_the_line_in_the_api_log_is_unobservable():
    entry = window("baseline_commit", "commit", "ota_end_baseline_commit", "bootloader_3", 80.0, proof="build id")
    (row,) = rollback.rows([entry], lambda e: "", lambda e: "[I][safe_mode:154]: Boot seems successful")
    assert row["state"] is None and row["source"] == rollback.SOURCE_UNOBSERVABLE
    (row,) = rollback.rows([entry], lambda e: None)  # no API log at all
    assert row["state"] is None and row["source"] == rollback.SOURCE_UNOBSERVABLE


def test_write_states_writes_the_rows(tmp_path, monkeypatch):
    monkeypatch.setenv("HIL_REPORTS_DIR", str(tmp_path / "reports"))
    rollback.write_states([{"label": "commit", "state": "supported"}])
    data = json.loads((tmp_path / "reports" / rollback.STATES_REPORT).read_text(encoding="utf-8"))
    assert data == [{"label": "commit", "state": "supported"}]


# Dut windows ----------------------------------------------------------------------------


class Tap:
    """A UART0 stand-in with real mark offsets: text(since, until) is the stream between two marks."""

    def __init__(self):
        self.buf = ""
        self.marks = {}
        self.closed = False

    def feed(self, text):
        self.buf += text

    def mark(self, name):
        self.marks[name] = len(self.buf)

    def has_mark(self, name):
        return name in self.marks

    def text(self, since, until=None):
        return self.buf[self.marks[since]:self.marks[until] if until is not None else len(self.buf)]

    def wait_for(self, regex, since, deadline_s):
        import re

        found = re.search(regex, self.text(since))
        if not found:
            raise dut_module.RigError("no match")
        return found


class Ota:
    """Each upload 'reboots' the DUT: the boot text of the next image lands after the end mark."""

    def __init__(self, tap, boots):
        self.tap = tap
        self.boots = list(boots)

    def upload(self, path, key, deadline_s=None, on_done=None, **kwargs):
        on_done()
        self.tap.feed(self.boots.pop(0))
        return OtaResult(ok=True, duration_s=10.0, reason="", output_tail="")


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.setenv("HIL_REPORTS_DIR", str(tmp_path / "reports"))
    clock = Clock()
    monkeypatch.setattr(dut_module.time, "monotonic", clock)
    monkeypatch.setattr(dut_module.time, "sleep", lambda s: None)

    def image(role, build_id):
        path = tmp_path / ("%s.ota.bin" % role)
        path.write_bytes(role.encode())
        return SimpleNamespace(role=role, build_id=build_id, ota_path=path, ota_sha256=hashlib.sha256(role.encode()).hexdigest())

    def build(boots):
        tap = Tap()
        # A press of Bootloader puts the ROM download banner on UART0 (enter_bootloader waits for it).
        supervisor = SimpleNamespace(press=lambda name: tap.feed(DOWNLOAD) if "Bootloader" in name else None)
        device = Dut("A", SimpleNamespace(host="203.0.113.9", chip="esp32s2"), supervisor, None, tap=tap, ota=Ota(tap, boots))
        state = {"version": None}
        device.probe = lambda psk: SimpleNamespace(project_version=state["version"])
        return device, tap, state

    return SimpleNamespace(clock=clock, image=image, build=build)


def test_three_otas_give_three_windows_each_ending_at_the_next_upload(rig):
    qc, canary, commit = rig.image("qc-auto", "3.2+qc.x"), rig.image("canary", "3.2+canary.x"), rig.image("commit", "3.2+hil.x")
    device, tap, state = rig.build([BANNER + UNKNOWN, BANNER + "A" + UNKNOWN, BANNER + SUPPORTED])
    device._api_ready()  # the commit image answered after its serial flash
    for image, up in ((qc, 120.0), (canary, 80.0), (commit, 50.0)):
        rig.clock.now += up
        state["version"] = image.build_id
        device.ota(image, KEY)
        device.unconfirmed_until = 0.0  # the test does not wait out the window; the guard is not under test here
    windows = device.ota_windows()
    assert [(w["label"], w["end_mark"], w["until_mark"], w["old_uptime_s"]) for w in windows] == [
        ("qc-auto", "ota_end_qc-auto", "ota_start_canary", 120.0),
        ("canary", "ota_end_canary", "ota_start_commit", 80.0),
        ("commit", "ota_end_commit", None, 50.0),
    ]
    found = rollback.rows(windows, lambda e: tap.text(e["end_mark"], e["until_mark"]))
    assert [r["state"] for r in found] == ["support unknown", "support unknown", "supported"]
    report = json.loads((dut_module.config.reports_dir() / "ota-dut-a.json").read_text(encoding="utf-8"))
    assert report[0]["until_mark"] == "ota_start_canary" and "end_at" not in report[0]


def test_the_broken_window_ends_at_the_bootloader_press_of_the_recovery_flash(rig):
    broken = rig.image("broken", "3.2+broken.x")
    device, tap, _ = rig.build([BANNER + VALID + "[I][app:166]: Project p version 3.2+broken.x\r\n"])
    device._api_ready()
    rig.clock.now += 40.0
    device.ota_dark(broken, KEY)
    device.enter_bootloader()
    tap.feed(BANNER + UNKNOWN)  # the commit boot after the recovery flash prints the rollback line
    (entry,) = device.ota_windows()
    assert entry["until_mark"] == device.last_bootloader_mark and entry["old_uptime_s"] == 40.0
    (row,) = rollback.rows([entry], lambda e: tap.text(e["end_mark"], e["until_mark"]))
    assert row["state"] is None and row["image_state"] == "valid"


def test_without_an_api_answer_before_the_ota_the_old_uptime_is_none(rig):
    qc = rig.image("qc-auto", "3.2+qc.x")
    device, _, state = rig.build([BANNER + UNKNOWN])
    state["version"] = qc.build_id
    device.ota(qc, KEY)
    (entry,) = device.ota_windows()
    assert entry["old_uptime_s"] is None and entry["end_at"] == rig.clock.now


# Task 3: the rollback tests' facts and messages (engineer-arming, 2026-11-09) ----------------


def test_state_line_returns_the_whole_observed_line_without_ansi():
    assert rollback.state_line(BANNER + SUPPORTED) == "Bootloader rollback: supported"
    assert rollback.state_line(BANNER) is None


def test_the_fresh_outcome_is_told_by_the_build_id():
    assert rollback.fresh_outcome("3.2+canary.x", previous="3.2+canary.x", new="3.2+hil.x") == "rolled_back"
    assert rollback.fresh_outcome("3.2+hil.x", previous="3.2+canary.x", new="3.2+hil.x") == "kept"
    assert rollback.fresh_outcome("3.2+qc.x", previous="3.2+canary.x", new="3.2+hil.x") == "failed"
    assert rollback.fresh_outcome(None, previous="3.2+canary.x", new="3.2+hil.x") == "failed"


def test_the_arming_margin_is_the_old_images_mark_minus_its_age():
    facts = rollback.arming_facts(55.2, marked_before=False)
    assert facts == {"old_age_s": 55.2, "margin_s": 4.8, "marked_before": False, "warn": False}
    assert rollback.arming_facts(57.5, marked_before=False)["warn"] is True  # less than 3 s left
    assert rollback.arming_facts(20.0, marked_before=True)["warn"] is True  # marked already: no margin at all


def test_the_arming_warning_names_test_30_the_age_and_the_margin():
    assert rollback.arming_warning(rollback.arming_facts(55.2, marked_before=False)) is None
    text = rollback.arming_warning(rollback.arming_facts(57.5, marked_before=False))
    assert "57.5 s" in text and "2.5 s" in text and "test_30" in text and "D-39" in text
    text = rollback.arming_warning(rollback.arming_facts(20.0, marked_before=True))
    assert "already marked valid" in text and "test_30" in text


def test_the_not_armed_message_names_the_observed_line_and_the_old_images_uptime():
    facts = rollback.arming_facts(56.0, marked_before=False)
    text = rollback.not_armed_message("Bootloader rollback: support unknown", facts)
    assert text.startswith("rollback not armed")
    assert "'Bootloader rollback: support unknown'" in text and "56.0 s" in text and "REG-05" in text
    text = rollback.not_armed_message(None, rollback.arming_facts(61.0, marked_before=True))
    assert "no 'Bootloader rollback:' line within %d s" % rollback.ROLLBACK_LINE_S in text
    assert "already marked valid" in text


def test_write_test_merges_the_sections_of_rollback_dut_a(tmp_path, monkeypatch):
    monkeypatch.setenv("HIL_REPORTS_DIR", str(tmp_path / "reports"))
    rollback.write_test("fresh", {"outcome": "rolled_back"})
    rollback.write_test("marked", {"mark_s": 60.8})
    data = json.loads((tmp_path / "reports" / rollback.TEST_REPORT).read_text(encoding="utf-8"))
    assert data == {"fresh": {"outcome": "rolled_back"}, "marked": {"mark_s": 60.8}}


def test_only_test_36_forces_a_reset():
    """D-39: the rollback-window guard is skipped for exactly one caller, the rollback-before-the-mark test."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    needle = "force" + "=True"
    found = sorted(
        str(path.relative_to(root))
        for folder in ("hil", "tests")
        for path in (root / folder).rglob("*.py")
        if needle in path.read_text(encoding="utf-8")
    )
    assert found == ["tests/rig/test_36_rollback_before_mark.py"]


def test_the_safe_mode_press_waits_for_the_mark_first():
    """WR-02: test_25 confirms the qc-auto image before it presses the safe-mode button."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "rig" / "test_25_qc_safe_mode.py").read_text(encoding="utf-8")
    assert 0 <= source.index("dut_a.wait_confirmed()") < source.index('dut_a.tap.mark("safe_mode_press")')
