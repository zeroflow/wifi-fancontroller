"""test_11 (upgrade proven over the API) and test_12 (serial restore of the commit image), driven with fakes.

03-11 maintainer decision serial-restore-after-upgrade (2026-11-09): while the release's bootloader is in
flash UART0 shows no app line and the upgrade reboot's ROM banner goes to USB. test_11 therefore proves the
upgrade by the new build ID, `Boot seems successful` in the API log, an API session that never drops and 0 ROM
banners on UART0 during the soak, with the D-14 gate on the API log; test_12 writes the commit factory image
over serial so every later leg runs under the commit's own bootloader again, with the UART0 D-14 gate.
"""

import importlib.util
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from hil import FirmwareFailure, RigError

RIG = Path(__file__).resolve().parents[1] / "rig"
BUILD_ID = "3.2+hil." + "a" * 12
BANNER = "rst:0xc (RTC_SW_CPU_RST),boot:0x8 (SPI_FAST_FLASH_BOOT)\r\n"
API_OK = "[I][safe_mode:154]: Boot seems successful; resetting boot loop counter"
WDT = "E (4321) task_wdt: esp_task_wdt_reset(707): task not found"
END = "ota_end_baseline_commit"


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace(".py", "_under_test"), RIG / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def reports(tmp_path, monkeypatch):
    monkeypatch.setenv("HIL_REPORTS_DIR", str(tmp_path))
    return tmp_path


def read(reports, name):
    return json.loads((reports / name).read_text(encoding="utf-8"))


# ---- test_11 ----------------------------------------------------------------------------------------


class SoakTap:
    def __init__(self, window="", closed=False):
        self.window = window
        self.closed = closed
        self.marks = []
        self.asked = []

    def mark(self, name):
        self.marks.append(name)

    def text(self, since, until=None):
        self.asked.append((since, until))
        return self.window


class UpgradeDut:
    id = "A"

    def __init__(self, events, reported=BUILD_ID, mark_s=60.8):
        self.events = events
        self.reported = reported
        self.mark_s = mark_s
        self.ota_end_at = None
        self.last_ota = None

    def ota(self, image, noise_psk, allow_plaintext=False, label=None, uart_banner=True):
        self.events.append(("ota", allow_plaintext, label, noise_psk, uart_banner))
        self.ota_end_at = time.monotonic() - 80  # the soak's end has passed: no real waiting in a unit test
        self.last_ota = {"label": label, "transfer_s": 39.3, "boot_s": 4.7, "window_start": END}

    def wait_confirmed(self, deadline_s=None, link=None):
        self.events.append(("wait_confirmed", link))
        return self.mark_s

    def probe(self, key):
        self.events.append(("probe", key))
        return SimpleNamespace(project_version=self.reported, compilation_time="synthetic")

    def reset(self):  # never called by test_11
        self.events.append(("reset",))


class UpgradeLink:
    def __init__(self, events, lines, sessions=(3, 3), connected=True):
        self.events = events
        self.lines = lines
        self._sessions = list(sessions)
        self._connected = connected
        self.since = []

    def use_key(self, key):
        self.events.append(("use_key", key))

    def wait_connected(self, deadline_s, project_version=None):
        self.events.append(("wait_connected", project_version))
        return SimpleNamespace(project_version=project_version)

    def sessions(self):
        return self._sessions.pop(0) if len(self._sessions) > 1 else self._sessions[0]

    def connected(self):
        return self._connected

    def log_since(self, since):
        self.since.append(since)
        return list(self.lines)


def run_upgrade(reports, tap, lines=(API_OK,), reported=BUILD_ID, sessions=(3, 3), connected=True):
    upgrade = load("test_11_upgrade_from_release.py")
    events = []
    dut = UpgradeDut(events, reported=reported)
    link = UpgradeLink(events, list(lines), sessions=sessions, connected=connected)
    manifest = SimpleNamespace(image=lambda role: SimpleNamespace(role=role, build_id=BUILD_ID))
    baseline = SimpleNamespace(tag="v2026.11.0", version="2026.11.0")
    rig = SimpleNamespace(duts={"A": SimpleNamespace(chip="esp32s2")}, dut_api_key="hil-key")
    try:
        upgrade.test_ota_from_the_release_to_the_commit(dut, link, tap, manifest, baseline, rig)
    finally:
        path = reports / "upgrade-dut-a.json"
        data = json.loads(path.read_text()) if path.exists() else None
    return events, data, link


def test_a_quiet_uart0_a_steady_session_and_a_clean_api_log_pass(reports, capsys):
    tap = SoakTap(window="")  # UART0 is dark under the release bootloader
    events, data, link = run_upgrade(reports, tap, lines=("[I][app:1]: up", API_OK))
    assert events[0] == ("use_key", "hil-key")
    assert events[1] == ("ota", True, "baseline_commit", "hil-key", False)
    assert events[2] == ("wait_connected", BUILD_ID)
    assert events[3] == ("wait_confirmed", link)
    assert ("reset",) not in events
    assert tap.marks == ["soak_end"] and (END, "soak_end") in tap.asked
    assert data["tag"] == "v2026.11.0" and data["from_version"] == "2026.11.0" and data["build_id"] == BUILD_ID
    assert data["banners"] == 0 and data["api_session_dropped"] is False and data["mark_source"] == "api"
    assert data["errors"] == [] and data["allowed"] == [] and data["gate"] == "pass" and data["gate_source"] == "api"
    assert data["transfer_s"] == 39.3 and data["boot_s"] == 4.7 and data["mark_s"] == 60.8 and data["soak_s"] >= 70
    assert data["reported_build_id"] == BUILD_ID and data["reboot_proof"] == "build id"
    assert read(reports, "timings.json")["soak_mark"] == 60.8
    assert read(reports, "dut-a.json")["project_version"] == BUILD_ID
    out = capsys.readouterr().out
    assert "DUT %s upgraded from v2026.11.0 to %s by OTA" % ("A", BUILD_ID) in out


def test_the_api_log_is_read_from_the_ota_end_on(reports):
    _events, _data, link = run_upgrade(reports, SoakTap())
    assert len(link.since) == 1 and link.since[0] is not None


def test_a_rom_banner_on_uart0_during_the_soak_fails_naming_the_count(reports):
    with pytest.raises(AssertionError, match="1 ROM boot banner\\(s\\) on UART0 during the soak, expected 0"):
        run_upgrade(reports, SoakTap(window=BANNER))
    assert read(reports, "upgrade-dut-a.json")["banners"] == 1


def test_a_session_drop_during_the_soak_fails(reports):
    with pytest.raises(AssertionError, match="API session dropped during the soak"):
        run_upgrade(reports, SoakTap(), sessions=(3, 4))
    assert read(reports, "upgrade-dut-a.json")["api_session_dropped"] is True


def test_a_link_down_at_the_end_of_the_soak_fails(reports):
    with pytest.raises(AssertionError, match="API session dropped during the soak"):
        run_upgrade(reports, SoakTap(), connected=False)


def test_banner_drop_and_gate_errors_are_reported_together(reports):
    with pytest.raises(AssertionError) as caught:
        run_upgrade(reports, SoakTap(window=BANNER + BANNER), lines=("[E][synthetic:9]: first", API_OK), sessions=(3, 5))
    message = str(caught.value)
    assert "2 ROM boot banner(s)" in message and "[E][synthetic:9]: first" in message and "dropped" in message
    data = read(reports, "upgrade-dut-a.json")
    assert data["gate"] == "fail" and data["errors"] == ["[E][synthetic:9]: first"]


def test_one_task_wdt_line_in_the_api_log_is_allowed_with_the_upgrade_label(reports):
    with pytest.warns(UserWarning, match="ALLOWLISTED boot-log line"):
        _events, data, _link = run_upgrade(reports, SoakTap(), lines=(WDT, API_OK))
    assert data["allowed"] == [WDT] and data["gate"] == "pass"
    assert read(reports, "allowlisted-errors.json") == {"lines": ["upgrade: " + WDT]}


def test_a_wrong_build_id_at_the_end_of_the_soak_fails(reports):
    with pytest.raises(AssertionError, match="after the upgrade"):
        run_upgrade(reports, SoakTap(), reported="3.2+hil." + "b" * 12)


def test_a_tap_lost_during_the_soak_is_a_rig_error_not_a_pass(reports):
    with pytest.raises(RigError, match="lost the bridge"):
        run_upgrade(reports, SoakTap(closed=True))


def test_an_api_log_without_the_mark_is_a_rig_error(reports):
    with pytest.raises(RigError, match="vacuous"):
        run_upgrade(reports, SoakTap(), lines=("[I][app:1]: up",))


# ---- test_12 ----------------------------------------------------------------------------------------


class RestoreTap:
    def __init__(self, window, closed=False):
        self.window = window
        self.closed = closed
        self.marks = []
        self.asked = []

    def mark(self, name):
        self.marks.append(name)

    def text(self, since, until=None):
        self.asked.append((since, until))
        return self.window


class RestoreDut:
    id = "A"

    def __init__(self, events, reported=BUILD_ID, ok=True, verified=True, running=None):
        self.events = events
        self.reported = reported
        self.ok = ok
        self.verified = verified
        self.running = running
        self.last_reset_mark = None
        self.ota_count = 4

    def flash(self, image):
        self.events.append(("flash", image.offset, image.path))
        self.last_reset_mark = "reset_7"
        return SimpleNamespace(ok=self.ok, verified=self.verified, durations_s=[73.9], attempts=1)

    def wait_running(self, key, since_mark):
        self.events.append(("wait_running", key, since_mark))
        if self.running is not None:
            raise self.running
        return SimpleNamespace(project_version=self.reported)

    def ota(self, *args, **kwargs):  # never called by test_12
        self.events.append(("ota",))


def project_line(build_id=BUILD_ID):
    return "[I][app:029]: Project zeroflow.fancontroller version %s\r\n" % build_id


def run_restore(reports, monkeypatch, tap, offset="0x0", **dut_kwargs):
    restore = load("test_12_serial_restore.py")
    monkeypatch.setattr(restore.time, "sleep", lambda seconds: None)
    events = []
    dut = RestoreDut(events, **dut_kwargs)
    image = SimpleNamespace(role="commit", build_id=BUILD_ID, offset=offset, path="fw.factory.bin")
    manifest = SimpleNamespace(image=lambda role: image)
    rig = SimpleNamespace(duts={"A": SimpleNamespace(chip="esp32s2")}, dut_api_key="hil-key")
    restore.test_commit_image_is_written_over_serial_after_the_upgrade(dut, tap, manifest, rig)
    return events


def test_the_restore_writes_the_full_factory_image_at_0x0_and_gates_the_uart0_boot(reports, monkeypatch, capsys):
    tap = RestoreTap(BANNER + project_line() + API_OK + "\r\n")
    events = run_restore(reports, monkeypatch, tap)
    assert events == [("flash", "0x0", "fw.factory.bin"), ("wait_running", "hil-key", "reset_7")]
    assert tap.marks == ["restore_scan_end"] and ("reset_7", "restore_scan_end") in tap.asked
    timings = read(reports, "timings.json")
    assert timings["restore_flash"] == 73.9 and timings["restore_boot"] >= 0
    assert "DUT %s restored over serial: %s" % ("A", BUILD_ID) in capsys.readouterr().out


def test_a_factory_image_not_at_0x0_is_a_rig_error_before_any_flash(reports, monkeypatch):
    with pytest.raises(RigError, match="0x0"):
        run_restore(reports, monkeypatch, RestoreTap(BANNER + project_line()), offset="0x10000")


def test_no_project_line_on_uart0_after_the_restore_fails(reports, monkeypatch):
    with pytest.raises(AssertionError, match="no Project line of %s on UART0" % BUILD_ID.replace("+", "\\+")):
        run_restore(reports, monkeypatch, RestoreTap(BANNER + "[I][app:1]: up\r\n"))


def test_an_error_line_in_the_uart0_boot_log_of_the_restore_fails(reports, monkeypatch):
    with pytest.raises(AssertionError, match="\\[E\\]\\[synthetic:1\\]: x"):
        run_restore(reports, monkeypatch, RestoreTap(BANNER + project_line() + "[E][synthetic:1]: x\r\n"))


def test_a_wrong_build_id_after_the_restore_fails(reports, monkeypatch):
    with pytest.raises(AssertionError, match="expected %s" % BUILD_ID.replace("+", "\\+")):
        run_restore(reports, monkeypatch, RestoreTap(BANNER + project_line()), reported="3.2+hil." + "c" * 12)


def test_an_unverified_flash_fails(reports, monkeypatch):
    with pytest.raises(AssertionError, match="not verified"):
        run_restore(reports, monkeypatch, RestoreTap(BANNER + project_line()), verified=False)


def test_no_rom_banner_after_the_restore_is_a_rig_error(reports, monkeypatch):
    with pytest.raises(RigError, match="vacuous"):
        run_restore(reports, monkeypatch, RestoreTap(project_line()))


def test_a_restored_dut_that_never_answers_is_a_firmware_failure(reports, monkeypatch):
    with pytest.raises(FirmwareFailure):
        run_restore(reports, monkeypatch, RestoreTap(BANNER), running=FirmwareFailure("booted, no API"))
