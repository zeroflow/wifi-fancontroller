"""The broken-image recovery leg (REC-01, REC-02, D-41, D-42) with fakes only: no hardware, no sleeping.

watch_dark gets a fake clock and a fake connect; Dut.ota_dark gets a fake OTA worker and a fake tap.
"""

import json
import re
from types import SimpleNamespace

import pytest

from hil import FirmwareFailure, RigError, contract, recovery
from hil import dut as dut_module
from hil.dut import Dut
from hil.ota import OtaResult

LABEL = contract.SERIAL_CONNECTED["A"].removesuffix(" Serial Connected")  # supervisor-name guard: no literal
DUT_HOST = "192.0.2.20"
SV_HOST = "192.0.2.30"
BANNER = "rst:0x1 (POWERON),boot:0x8 (SPI_FAST_FLASH_BOOT)\r\n"
DOWNLOAD = "rst:0x1 (POWERON),boot:0x0 (DOWNLOAD(USB/UART0))\r\nwaiting for download\r\n"
BROKEN_ID = "3.2+broken." + "c" * 12
PROJECT = "\x1b[0;32m[I][app:031]: Project zeroflow.fancontroller-brk-r3-2 version %s\x1b[0m\r\n" % BROKEN_ID
STATE_LINE = "\x1b[0;32m[I][hil:012]: HIL broken image OTA state: valid\x1b[0m\r\n"
KEY = "KEY-VALUE-THAT-MUST-NOT-LEAK"


# ---- the constants -------------------------------------------------------------------------


def test_the_window_is_65_seconds_polled_every_5_and_the_state_line_gets_10():
    assert (recovery.DARK_WINDOW_S, recovery.DARK_POLL_S, recovery.OTA_STATE_LINE_S) == (65, 5, 10)


# ---- watch_dark ----------------------------------------------------------------------------


class FakeClock:
    def __init__(self):
        self.now = 1000.0
        self.slept = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


class FakeNet:
    """connect(): accepts the (host, port) pairs `accept(host, port, t)` allows, refuses the rest."""

    def __init__(self, clock, accept=lambda host, port, t: False, cost=0.0):
        self.clock = clock
        self.accept = accept
        self.cost = cost
        self.start = clock.now
        self.asked = []

    def __call__(self, address, timeout=None):
        self.clock.now += self.cost
        t = round(self.clock.now - self.start)
        self.asked.append((address, timeout))
        if self.accept(address[0], address[1], t):
            return SimpleNamespace(close=lambda: None)
        raise ConnectionRefusedError("refused")


def watch(accept=lambda host, port, t: host == SV_HOST and port == contract.API_PORT, cost=0.0):
    clock = FakeClock()
    net = FakeNet(clock, accept, cost)
    polls = recovery.watch_dark(
        DUT_HOST, SV_HOST, clock=clock.monotonic, sleep=clock.sleep, connect=net
    )
    return polls, net


def test_a_dark_dut_gives_14_polls_from_0_to_65_and_no_problem():
    polls, _ = watch()
    assert [p["t"] for p in polls] == list(range(0, 66, 5)) and len(polls) == 14
    assert all(p["supervisor"] and not p["api"] and not p["ota"] for p in polls)
    assert recovery.dark_problems(polls, rebooted=False) == []
    assert recovery.control_lost(polls) is False


def test_each_poll_probes_the_dut_on_6053_and_3232_and_the_supervisor_on_6053_with_the_probe_deadline():
    _, net = watch()
    first = net.asked[:3]
    assert sorted(first) == sorted(
        [
            ((DUT_HOST, contract.API_PORT), dut_module.PORT_PROBE_S),
            ((DUT_HOST, dut_module.OTA_PORT), dut_module.PORT_PROBE_S),
            ((SV_HOST, contract.API_PORT), dut_module.PORT_PROBE_S),
        ]
    )


def test_an_accepted_6053_is_a_named_problem_at_its_first_poll_and_never_an_exception():
    polls, _ = watch(lambda host, port, t: host == SV_HOST or (port == contract.API_PORT and t >= 20))
    assert recovery.dark_problems(polls, rebooted=False) == ["%s answered on port 6053 at t=20 s" % LABEL]


def test_an_accepted_3232_is_a_named_problem():
    polls, _ = watch(lambda host, port, t: host == SV_HOST or (port == dut_module.OTA_PORT and t == 35))
    assert recovery.dark_problems(polls, rebooted=False) == ["%s answered on port 3232 at t=35 s" % LABEL]


def test_both_ports_answering_names_both():
    polls, _ = watch(lambda host, port, t: host == SV_HOST or t == 10)
    problems = recovery.dark_problems(polls, rebooted=False)
    assert len(problems) == 2 and "6053" in problems[0] and "3232" in problems[1]


def test_a_supervisor_that_refused_once_is_a_lost_control():
    polls, _ = watch(lambda host, port, t: host == SV_HOST and not (port == contract.API_PORT and t == 40))
    assert recovery.control_lost(polls) is True


def test_a_reboot_in_the_window_is_a_problem_even_when_every_port_stayed_closed():
    polls, _ = watch()
    assert recovery.dark_problems(polls, rebooted=True) == ["%s rebooted during the dark window" % LABEL]


def test_slow_refusals_do_not_drop_polls():
    polls, _ = watch(cost=2.0)
    assert len(polls) == 14


# ---- the OTA state line and the Project line --------------------------------------------------


def test_ota_state_in_reads_valid_with_ansi_stripped():
    assert recovery.ota_state_in(BANNER + STATE_LINE) == "valid"


def test_ota_state_in_reads_pending_verify():
    assert recovery.ota_state_in("[I][hil:12]: HIL broken image OTA state: pending verify\r\n") == "pending verify"


def test_ota_state_in_is_none_without_the_line():
    assert recovery.ota_state_in(BANNER + PROJECT) is None


def test_the_state_regex_does_not_take_invalid_for_valid():
    assert recovery.ota_state_in("HIL broken image OTA state: invalid\r\n") == "invalid"


def test_project_line_regex_matches_only_the_given_build_id():
    pattern = recovery.project_line_regex(BROKEN_ID)
    assert re.search(pattern, PROJECT)
    assert not re.search(pattern, PROJECT.replace("c" * 12, "d" * 12))
    assert not re.search(pattern, PROJECT.replace("3.2+broken.", "3x2+broken."))  # '.' and '+' are escaped


# ---- uart_path_problems ---------------------------------------------------------------------

GOOD = {
    "dark_at_start": True,
    "flash_ok": True,
    "verified": True,
    "download_banner": True,
    "ota_uploads_during_test": 0,
    "build_id_after": "3.2+hil." + "a" * 12,
    "expected_build_id": "3.2+hil." + "a" * 12,
    "api_after_flash": True,
}


def test_a_full_fact_set_has_no_problem():
    assert recovery.uart_path_problems(GOOD) == []


@pytest.mark.parametrize(
    "fact, value, word",
    [
        ("dark_at_start", False, "not dark"),
        ("flash_ok", False, "flash"),
        ("verified", False, "verified"),
        ("download_banner", False, "download"),
        ("ota_uploads_during_test", 1, "OTA upload"),
        ("api_after_flash", False, "API"),
        ("build_id_after", "3.2+hil." + "b" * 12, "expected"),
    ],
)
def test_each_missing_fact_is_one_named_problem(fact, value, word):
    problems = recovery.uart_path_problems({**GOOD, fact: value})
    assert len(problems) == 1 and word in problems[0]


def test_several_missing_facts_are_all_reported():
    problems = recovery.uart_path_problems({**GOOD, "dark_at_start": False, "ota_uploads_during_test": 2})
    assert len(problems) == 2


# ---- write_report ---------------------------------------------------------------------------


def test_write_report_merges_sections_into_one_file(tmp_path, monkeypatch):
    monkeypatch.setenv("HIL_REPORTS_DIR", str(tmp_path))
    recovery.write_report("dark", {"ota_state": "valid"})
    path = recovery.write_report("uart", {"flash_ok": True})
    assert json.loads(path.read_text(encoding="utf-8")) == {"dark": {"ota_state": "valid"}, "uart": {"flash_ok": True}}
    assert path.name == "recovery-dut-a.json"


def test_write_report_replaces_a_section_and_survives_a_damaged_file(tmp_path, monkeypatch):
    monkeypatch.setenv("HIL_REPORTS_DIR", str(tmp_path))
    (tmp_path / "recovery-dut-a.json").write_text("{not json", encoding="utf-8")
    recovery.write_report("dark", {"ota_state": None})
    path = recovery.write_report("dark", {"ota_state": "valid"})
    assert json.loads(path.read_text(encoding="utf-8")) == {"dark": {"ota_state": "valid"}}


# ---- Dut.ota_dark ---------------------------------------------------------------------------


class FakeOta:
    def __init__(self, result, reports_done=True):
        self.result = result
        self.reports_done = reports_done
        self.uploads = []

    def upload(self, path, key, deadline_s=None, on_done=None):
        self.uploads.append((path, key))
        if self.result.ok and self.reports_done and on_done is not None:
            on_done()
        return self.result


class FakeTap:
    def __init__(self, window=BANNER + PROJECT, closed=False):
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
    return OtaResult(ok=True, duration_s=9.5, reason="", output_tail="")


@pytest.fixture
def rig(tmp_path, monkeypatch):
    import hashlib

    monkeypatch.setenv("HIL_REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(dut_module.time, "sleep", lambda seconds: None)
    firmware = tmp_path / "broken.ota.bin"
    firmware.write_bytes(b"synthetic broken firmware")
    image = SimpleNamespace(
        role="broken",
        build_id=BROKEN_ID,
        ota_path=firmware,
        ota_sha256=hashlib.sha256(b"synthetic broken firmware").hexdigest(),
    )

    def build(result=None, tap=None, reports_done=True):
        fake_ota = FakeOta(result or ok_result(), reports_done)
        supervisor = FakeSupervisor()
        tap = tap if tap is not None else FakeTap()
        device = Dut("A", SimpleNamespace(host=DUT_HOST, chip="esp32s2"), supervisor, None, tap=tap, ota=fake_ota)

        def probe(noise_psk):
            raise AssertionError("ota_dark must never probe the API: the broken image has none")

        device.probe = probe
        return device, fake_ota, supervisor, tap

    return SimpleNamespace(build=build, image=image, reports=tmp_path / "reports")


def test_ota_dark_succeeds_when_the_project_line_of_the_build_id_follows_the_end_mark(rig, capsys):
    device, fake_ota, _, tap = rig.build()
    device.ota_dark(rig.image, noise_psk=KEY)
    assert fake_ota.uploads == [(rig.image.ota_path, KEY)]
    assert tap.marks[0] == "ota_start_broken" and tap.marks.count("ota_end_broken") == 1
    regex, since, deadline = tap.waited[0]
    assert re.search(regex, PROJECT) and since == "ota_end_broken" and deadline == dut_module.OTA_BOOT_S
    assert "broken_up" in tap.marks
    (entry,) = json.loads((rig.reports / "ota-dut-a.json").read_text(encoding="utf-8"))
    assert entry["role"] == "broken" and entry["ok"] is True and entry["dark"] is True
    assert "ota broken: ok" in capsys.readouterr().out


def test_without_a_done_report_the_project_line_is_looked_for_from_ota_start(rig):
    device, _, _, tap = rig.build(reports_done=False)
    device.ota_dark(rig.image, noise_psk=KEY)
    assert tap.waited[0][1] == "ota_start_broken"


def test_no_project_line_within_the_deadline_is_a_firmware_failure(rig, monkeypatch):
    monkeypatch.setattr(dut_module, "OTA_BOOT_S", 0)
    device, *_ = rig.build(tap=FakeTap(window=BANNER))
    with pytest.raises(FirmwareFailure, match=r"broken image did not boot \(no Project line on UART0\)"):
        device.ota_dark(rig.image, noise_psk=KEY)
    entry = json.loads((rig.reports / "ota-dut-a.json").read_text(encoding="utf-8"))[0]
    assert entry["ok"] is False and entry["dark"] is True


def test_a_project_line_without_a_rom_banner_is_a_firmware_failure(rig):
    device, *_ = rig.build(tap=FakeTap(window=PROJECT))
    with pytest.raises(FirmwareFailure, match="no reboot seen"):
        device.ota_dark(rig.image, noise_psk=KEY)


def test_a_failed_upload_is_a_firmware_failure_and_still_counted(rig):
    device, *_ = rig.build(OtaResult(ok=False, duration_s=4.0, reason="exit 1", output_tail="tail line"))
    with pytest.raises(FirmwareFailure, match="OTA to broken failed"):
        device.ota_dark(rig.image, noise_psk=KEY)
    assert device.ota_count == 1


def test_a_closed_tap_is_a_rig_error_not_a_firmware_verdict(rig):
    device, *_ = rig.build(tap=FakeTap(closed=True))
    with pytest.raises(RigError, match="serial tap lost"):
        device.ota_dark(rig.image, noise_psk=KEY)


def test_a_tampered_file_is_refused_before_any_upload_and_not_counted(rig):
    rig.image.ota_path.write_bytes(b"something else")
    device, fake_ota, *_ = rig.build()
    with pytest.raises(RigError, match="does not match its manifest sha256"):
        device.ota_dark(rig.image, noise_psk=KEY)
    assert fake_ota.uploads == [] and device.ota_count == 0


def test_ota_dark_never_calls_probe(rig):
    device, *_ = rig.build()
    device.ota_dark(rig.image, noise_psk=KEY)  # probe() raises AssertionError if called


def test_ota_dark_closes_the_rollback_window_and_a_following_reset_does_not_wait(rig):
    import time

    device, _, supervisor, tap = rig.build()
    device.unconfirmed_until = time.monotonic() + 100  # an earlier OTA's open window
    device.ota_dark(rig.image, noise_psk=KEY)
    assert device.unconfirmed_until == 0.0
    waits_before = len(tap.waited)
    device.reset()
    assert supervisor.pressed == [contract.BUTTON["A"]["reset"]]
    assert len(tap.waited) == waits_before  # no wait for 'Boot seems successful'


def test_ota_count_counts_every_upload_attempt_of_the_run(rig):
    device, *_ = rig.build()
    assert device.ota_count == 0
    device.ota_dark(rig.image, noise_psk=KEY)
    device.ota_dark(rig.image, noise_psk=KEY)
    assert device.ota_count == 2


def test_reset_and_bootloader_entry_remember_their_marks(rig):
    device, _, _, _ = rig.build(tap=FakeTap(window=DOWNLOAD + BANNER))
    assert device.last_reset_mark is None and device.last_bootloader_mark is None
    device.enter_bootloader()
    assert device.last_bootloader_mark == "bootloader_1"
    assert device.reset() == device.last_reset_mark == "reset_2"
