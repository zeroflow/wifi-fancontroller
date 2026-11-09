"""DUT state (HARN-03) and safe-mode detection (HARN-12) with fakes only: no hardware, no sleeping.

The Dut under test gets a fake tap with scripted UART0 text, a fake supervisor that records presses,
a fake DutLink and injected probe and port-probe functions. Time is a fake clock that sleep() advances.
"""

import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from hil import FirmwareFailure, RigError, bootlog, contract, entities
from hil import dut as dut_module
from hil.budget import ResetBudget, ResetBudgetExhausted, SafeModeError
from hil.dut import STATE_EXEMPT, Dut, state_roles

HIL_ROOT = Path(__file__).resolve().parents[2]
LABEL = contract.SERIAL_CONNECTED["A"].removesuffix(" Serial Connected")  # supervisor-name guard: no literal
DOWNLOAD = "rst:0x1 (POWERON),boot:0x0 (DOWNLOAD(USB/UART0))\r\nwaiting for download\r\n"
BOOT = "rst:0x1 (POWERON),boot:0x8 (SPI_FAST_FLASH_BOOT)\r\n[I][app:1]: up\r\n"
ACTIVE = "\x1b[0;33m[W][safe_mode:248]: SAFE MODE IS ACTIVE\x1b[0m\r\n"
BUILD = "3.2+qc." + "a" * 12


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(dut_module, "time", fake)
    return fake


class ScriptedTap:
    """UART0 text that grows; marks are offsets, windows are cut like SerialTap."""

    def __init__(self):
        self.buf = ""
        self.marks = {}
        self.order = []
        self.closed = False
        self.waits = []

    def feed(self, text):
        self.buf += text

    def mark(self, name):
        self.marks[name] = len(self.buf)
        self.order.append(name)

    def text(self, since, until=None):
        return self.buf[self.marks[since] :]

    def wait_for(self, regex, since, deadline_s):
        self.waits.append((regex, since, deadline_s))
        found = re.search(regex, self.text(since))
        if not found:
            raise RigError("serial bridge: no match for /%s/ within %ss" % (regex, deadline_s))
        return found


class FakeSupervisor:
    def __init__(self, tap=None):
        self.pressed = []
        self.tap = tap
        self.on_press = {}  # button name -> text the DUT prints at once
        self.switches = {contract.SWITCH["A"]["usr%d" % n]: False for n in (1, 2, 3)}

    def press(self, name):
        self.pressed.append(name)
        if self.tap is not None and name in self.on_press:
            self.tap.feed(self.on_press[name])

    def switch_is_on(self, name):
        return self.switches.get(name)


def make_dut(tap="default", supervisor=None, chip="esp32s2"):
    tap = ScriptedTap() if tap == "default" else tap
    supervisor = supervisor or FakeSupervisor(tap)
    cfg = SimpleNamespace(host="192.0.2.20", chip=chip)
    return Dut("A", cfg, supervisor, flasher=None, tap=tap), tap, supervisor


# ---- enter_bootloader -------------------------------------------------------------------------


def test_bootloader_entry_is_confirmed_by_the_download_banner_after_a_fresh_mark(clock):
    device, tap, sv = make_dut()
    sv.on_press[contract.BUTTON["A"]["bootloader"]] = DOWNLOAD
    tap.feed(DOWNLOAD)  # an older download banner must not count
    device.enter_bootloader()
    assert sv.pressed == [contract.BUTTON["A"]["bootloader"]]
    assert tap.order == ["bootloader_1"]
    regex, since, deadline = tap.waits[0]
    assert since == "bootloader_1" and deadline == dut_module.BOOTLOADER_BANNER_S == 3
    assert re.search(regex, "boot:0x0 (DOWNLOAD") and not re.search(regex, "boot:0x8")


def test_without_the_download_banner_entry_is_a_rig_error_naming_the_code_and_the_deadline(clock):
    device, tap, _ = make_dut()
    tap.feed(DOWNLOAD)  # old text only
    with pytest.raises(RigError, match=LABEL + r" did not enter download mode \(no boot:0x0 within 3 s\)"):
        device.enter_bootloader()


def test_c6_waits_for_its_own_download_code(clock):
    device, _, sv = make_dut(chip="esp32c6")
    sv.on_press[contract.BUTTON["A"]["bootloader"]] = "boot:0x67 (DOWNLOAD(USB/UART0))\r\n"
    device.enter_bootloader()


def test_each_bootloader_entry_gets_its_own_mark(clock):
    device, tap, sv = make_dut()
    sv.on_press[contract.BUTTON["A"]["bootloader"]] = DOWNLOAD
    device.enter_bootloader()
    device.enter_bootloader()
    assert tap.order == ["bootloader_1", "bootloader_2"]


def test_without_a_tap_the_settle_delay_stays_and_nothing_is_waited_for(clock):
    device, _, sv = make_dut(tap=None, supervisor=FakeSupervisor())
    device.enter_bootloader()
    assert sv.pressed == [contract.BUTTON["A"]["bootloader"]]
    assert clock.now == pytest.approx(100.0 + dut_module.BOOTLOADER_SETTLE_S)


def test_a_missing_banner_stops_flash_before_esptool_starts_and_still_resets_the_board(clock):
    tap = ScriptedTap()
    calls = []
    device, _, sv = make_dut(tap=tap)
    device._flasher = SimpleNamespace(write=lambda *args, **kwargs: calls.append(args))
    with pytest.raises(RigError, match="did not enter download mode"):
        device.flash_regions([("0x0", "fw.bin")])
    assert calls == []
    assert sv.pressed == [contract.BUTTON["A"]["bootloader"], contract.BUTTON["A"]["reset"]]
    assert [b["cause"] for b in device.budget.report()["boots"]] == ["flash_reset"]


# ---- budgeted reset ---------------------------------------------------------------------------


def test_reset_marks_are_unique_and_reset_pressed_follows_the_latest(clock):
    device, tap, sv = make_dut()
    assert device.reset() == "reset_1"
    assert device.reset() == "reset_2"
    assert tap.order == ["reset_1", "reset_pressed", "reset_2", "reset_pressed"]
    assert tap.marks["reset_pressed"] == tap.marks["reset_2"]
    assert sv.pressed == [contract.BUTTON["A"]["reset"]] * 2


def test_reset_with_an_exhausted_budget_raises_before_pressing_anything(clock):
    device, tap, sv = make_dut()
    device.budget = ResetBudget(limit=2, clock=clock.monotonic)
    device.reset()
    device.reset()
    with pytest.raises(ResetBudgetExhausted, match="2/2"):
        device.reset()
    assert len(sv.pressed) == 2 and tap.order.count("reset_pressed") == 2


def test_leaving_the_bootloader_is_never_refused_by_the_budget(clock):
    device, tap, sv = make_dut()
    sv.on_press[contract.BUTTON["A"]["bootloader"]] = DOWNLOAD
    device.budget = ResetBudget(limit=1, clock=clock.monotonic)
    device.budget.record("en_reset")
    device.enter_bootloader()
    device.reset()  # a board left in the loader is worse than a spent budget
    assert sv.pressed[-1] == contract.BUTTON["A"]["reset"]
    assert [b["cause"] for b in device.budget.report()["boots"]] == ["en_reset", "flash_reset"]
    with pytest.raises(ResetBudgetExhausted):
        device.reset()  # the next press is a plain EN reset again


# ---- wait_running -----------------------------------------------------------------------------


def probing(device, answers):
    """Replace probe: each call takes the next answer (an exception is raised)."""
    sequence = iter(answers)
    seen = []

    def probe(noise_psk):
        item = next(sequence, answers[-1])
        seen.append(item)
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(project_version=item)

    device.probe = probe
    return seen


def test_wait_running_returns_the_device_info_once_booted_and_answering(clock):
    device, tap, _ = make_dut()
    mark = device.reset()
    tap.feed(BOOT)
    probing(device, [OSError("refused"), BUILD])
    info = device.wait_running("key", mark)
    assert info.project_version == BUILD and "api_ready" in tap.order


def test_an_answer_before_the_rom_banner_is_the_old_image_and_does_not_count(clock):
    device, tap, _ = make_dut()
    mark = device.reset()
    seen = probing(device, [BUILD])
    with pytest.raises(RigError, match=r"within 5s \(last: no ROM boot banner since reset_1\)"):
        device.wait_running("key", mark, deadline_s=5)
    assert seen == []  # not even asked: nothing proves the reboot has happened


def test_a_banner_from_before_the_mark_does_not_count_either(clock):
    device, tap, _ = make_dut()
    tap.feed(BOOT)
    mark = device.reset()
    probing(device, [BUILD])
    with pytest.raises(RigError, match="no ROM boot banner since"):
        device.wait_running("key", mark, deadline_s=3)


def test_safe_mode_line_on_uart0_is_a_safe_mode_error_with_the_line_and_the_counts(clock):
    device, tap, _ = make_dut()
    device.budget.record("flash_reset")
    tap.mark("safe_mode_press")
    tap.feed(BOOT + ACTIVE)
    seen = probing(device, [BUILD])
    with pytest.raises(SafeModeError) as caught:
        device.wait_running("key", "safe_mode_press", deadline_s=45)
    assert str(caught.value) == (
        LABEL + " booted into ESPHome safe mode ([W][safe_mode:248]: SAFE MODE IS ACTIVE); boots this run: 2, streak 1/8"
    )
    assert seen == []  # the scan comes first, so an API answer cannot hide safe mode
    assert [b["cause"] for b in device.budget.report()["boots"]] == ["flash_reset", "safe_mode_reboot"]
    assert isinstance(caught.value, RigError) and not isinstance(caught.value, AssertionError)


def test_safe_mode_appearing_while_waiting_is_found_within_the_deadline(clock):
    device, tap, _ = make_dut()
    tap.mark("safe_mode_press")
    tap.feed(BOOT)
    answers = probing(device, [OSError("refused")])
    real_sleep = clock.sleep

    def sleep(seconds):
        real_sleep(seconds)
        if clock.now >= 103:
            tap.feed(ACTIVE)

    clock.sleep = sleep
    with pytest.raises(SafeModeError, match="SAFE MODE IS ACTIVE"):
        device.wait_running("key", "safe_mode_press", deadline_s=45)
    assert len(answers) >= 2 and clock.now < 110


def ports(device, open_ports):
    device._port_open = lambda port: port in open_ports


@pytest.mark.parametrize(
    ("open_ports", "safe"),
    [
        ({3232}, True),  # OTA answers, API refuses: safe mode
        (set(), False),  # it booted and nothing answers: the firmware's outcome (D-46)
        ({3232, 6053}, False),  # the API port is open but the probe failed: not safe mode
        ({6053}, False),
    ],
)
def test_at_the_deadline_the_ports_tell_safe_mode_from_a_dead_dut(clock, open_ports, safe):
    device, tap, _ = make_dut()
    mark = device.reset()
    tap.feed(BOOT)  # booted, but the API never answers and no safe mode line was printed
    probing(device, [OSError("refused")])
    ports(device, open_ports)
    expected = SafeModeError if safe else FirmwareFailure
    with pytest.raises(expected) as caught:
        device.wait_running("key", mark, deadline_s=4)
    if safe:
        assert "port 3232 answers and API port 6053 refuses" in str(caught.value)
    else:
        assert type(caught.value) is FirmwareFailure and "API did not answer within 4s (last: OSError)" in str(caught.value)


def test_the_port_probe_is_not_asked_when_the_dut_never_booted(clock):
    device, _, _ = make_dut()
    mark = device.reset()
    asked = []
    device._port_open = lambda port: asked.append(port) or True
    probing(device, [BUILD])
    with pytest.raises(RigError, match="no ROM boot banner"):
        device.wait_running("key", mark, deadline_s=2)
    assert asked == []


def test_without_a_tap_an_answer_is_accepted_as_it_is(clock):
    device, _, _ = make_dut(tap=None, supervisor=FakeSupervisor())
    probing(device, [BUILD])
    assert device.wait_running("key", "reset_1").project_version == BUILD


def test_check_safe_mode_ports_is_silent_for_a_healthy_dut(clock):
    device, _, _ = make_dut()
    ports(device, {3232, 6053})
    device.check_safe_mode_ports()


def test_the_real_port_probe_connects_to_the_duts_host_and_gives_up_quickly(monkeypatch):
    device, _, _ = make_dut()
    calls = []

    def create_connection(address, timeout):
        calls.append((address, timeout))
        raise OSError("refused")

    monkeypatch.setattr(dut_module.socket, "create_connection", create_connection)
    assert device._port_open(6053) is False
    assert calls == [(("192.0.2.20", 6053), dut_module.PORT_PROBE_S)]


# ---- settle -----------------------------------------------------------------------------------


class FakeLink:
    """Fresh tach values per fan (the last one repeats), button states, and the order of events."""

    def __init__(self, clock, tach=None, buttons=None):
        self.clock = clock
        self.tach = tach or {}
        self.buttons = buttons or {}
        self.events = []
        self.counter = {}

    def count(self, name):
        self.events.append(("count", name))
        self.counter[name] = self.counter.get(name, 0) + 1
        return self.counter[name]

    def fan(self, n, on):
        self.events.append(("fan", n, on))

    def wait_fresh(self, name, after, n, deadline_s):
        self.events.append(("fresh", name, n))
        self.clock.now += min(1, max(0, deadline_s))  # waiting for the next 1 s publish, never past the deadline
        values = self.tach.get(name, [0.0])
        if values == "silent":
            return []
        return [values[min(i, len(values) - 1)] for i in range(n)]

    def wait_value(self, name, predicate, deadline_s):
        value = self.buttons.get(name, False)
        return value if value is not None and predicate(value) else None


def test_a_clean_dut_has_no_problems_and_the_counts_precede_the_fan_commands(clock):
    device, _, _ = make_dut()
    link = FakeLink(clock)
    assert device.settle(link) == []
    kinds = [e[0] for e in link.events]
    assert kinds[:4] == ["count"] * 4 and kinds[4:8] == ["fan"] * 4
    assert [e[1:] for e in link.events if e[0] == "fan"] == [(n, False) for n in (1, 2, 3, 4)]


def test_a_partial_window_after_the_command_is_waited_out_by_the_next_fresh_reading(clock):
    device, _, _ = make_dut()
    link = FakeLink(clock, tach={entities.FAN_SPEED[2]: [431000.0, 0.0]})
    assert device.settle(link) == []
    assert ("fresh", entities.FAN_SPEED[2], 2) in link.events


def test_a_fan_that_keeps_reading_is_a_problem_at_the_settle_deadline(clock):
    device, _, _ = make_dut()
    link = FakeLink(clock, tach={entities.FAN_SPEED[3]: [750000.0]})
    started = clock.now
    assert device.settle(link) == ["Fan 3 Speed still reads 750000.0"]
    assert clock.now - started <= dut_module.SETTLE_S + 1


def test_a_silent_tach_is_a_problem_and_never_a_zero(clock):
    device, _, _ = make_dut()
    link = FakeLink(clock, tach={entities.FAN_SPEED[1]: "silent"})
    assert device.settle(link) == ["Fan 1 Speed: no fresh reading within 10 s"]


def test_a_nan_tach_is_not_a_zero(clock):
    device, _, _ = make_dut()
    link = FakeLink(clock, tach={entities.FAN_SPEED[4]: [float("nan")]})
    (problem,) = device.settle(link)
    assert problem.startswith("Fan 4 Speed still reads nan")


def test_a_button_that_is_on_or_silent_is_a_problem(clock):
    device, _, _ = make_dut()
    link = FakeLink(clock, buttons={entities.BUTTON_USR[2]: True, entities.BUTTON_USR[3]: None})
    assert device.settle(link) == ["Button USR2 is not OFF", "Button USR3 is not OFF"]


def test_a_supervisor_usr_switch_that_is_on_or_unknown_is_a_problem(clock):
    device, _, sv = make_dut()
    sv.switches[contract.SWITCH["A"]["usr1"]] = True
    sv.switches[contract.SWITCH["A"]["usr3"]] = None
    problems = device.settle(FakeLink(clock))
    assert problems == [
        "supervisor switch '%s' is not OFF" % contract.SWITCH["A"]["usr1"],
        "supervisor switch '%s' is not OFF" % contract.SWITCH["A"]["usr3"],
    ]


def test_problems_come_back_sorted_and_all_signals_share_one_deadline(clock):
    device, _, sv = make_dut()
    sv.switches[contract.SWITCH["A"]["usr2"]] = True
    link = FakeLink(
        clock, tach={entities.FAN_SPEED[4]: [5.0], entities.FAN_SPEED[1]: [5.0]}, buttons={entities.BUTTON_USR[1]: True}
    )
    started = clock.now
    problems = device.settle(link)
    assert problems == sorted(problems) and len(problems) == 4
    assert clock.now - started <= dut_module.SETTLE_S  # two stuck fans did not take 2 x SETTLE_S


# ---- state_roles ------------------------------------------------------------------------------


def marker(*args, **kwargs):
    return SimpleNamespace(args=args, kwargs=kwargs)


def test_the_one_recorded_exemption_is_test_00_contract_with_its_reason():
    assert set(STATE_EXEMPT) == {"test_00_contract.py"}
    assert "supervisor-only" in STATE_EXEMPT["test_00_contract.py"] and "never touches DUT A" in STATE_EXEMPT["test_00_contract.py"]


def test_the_exempt_module_without_a_marker_has_no_state_check():
    assert state_roles(None, "test_00_contract.py") is None


@pytest.mark.parametrize("module", ["test_10_release_baseline.py", "test_new.py", "test_00_contract.pyc", ""])
def test_any_other_module_without_a_marker_is_a_rig_error_naming_it(module):
    with pytest.raises(RigError, match="no image marker and no recorded HARN-03 exemption") as caught:
        state_roles(None, module)
    assert str(caught.value).startswith(module)


def test_one_role_is_the_state_before_and_after():
    assert state_roles(marker("qc-auto"), "test_x.py") == ("qc-auto", "qc-auto")


def test_before_and_after_keywords_give_the_pair():
    assert state_roles(marker(before="qc-auto", after="canary"), "test_x.py") == ("qc-auto", "canary")
    assert state_roles(marker(before="commit", after="qc-auto"), "test_x.py") == ("commit", "qc-auto")


def test_after_alone_leaves_the_start_state_to_the_test_itself():
    assert state_roles(marker(after="commit"), "test_x.py") == (None, "commit")


def test_a_keyword_overrides_one_side_of_the_positional_role():
    assert state_roles(marker("qc-auto", after="canary"), "test_x.py") == ("qc-auto", "canary")


@pytest.mark.parametrize(
    "bad",
    [marker(), marker(after=None), marker("a", "b"), marker(when="x"), marker("qc_auto"), marker(before=3), marker(after="Commit")],
)
def test_a_malformed_marker_or_an_unknown_role_name_is_a_rig_error(bad):
    with pytest.raises(RigError):
        state_roles(bad, "test_x.py")


def test_the_baseline_pseudo_role_is_known_with_and_without_the_manifest_roles():
    """D-36: `baseline` is the release from the hil-baseline directory, never a manifest role."""
    assert dut_module.BASELINE_ROLE == "baseline"
    assert state_roles(marker(after="baseline"), "test_x.py") == (None, "baseline")
    assert state_roles(marker(before="baseline", after="commit"), "test_x.py", roles={"commit"}) == ("baseline", "commit")
    with pytest.raises(RigError):
        state_roles(marker("Baseline"), "test_x.py")


def test_a_role_the_manifest_lacks_is_a_rig_error_when_the_roles_are_given():
    assert state_roles(marker(before="commit", after="canary"), "test_x.py", roles={"commit", "canary"}) == ("commit", "canary")
    with pytest.raises(RigError, match="'canary' is not in the manifest"):
        state_roles(marker("canary"), "test_x.py", roles={"commit", "qc-auto"})
    with pytest.raises(RigError, match="'qc-auto' is not in the manifest"):
        state_roles(marker(after="commit", before="qc-auto"), "test_x.py", roles={"commit"})


# ---- the real rig tests: HARN-03 traceability --------------------------------------------------

LIST_ROLES = textwrap.dedent(
    """
    import json, sys
    import pytest
    from hil.dut import state_roles

    class Plugin:
        def __init__(self):
            self.found = {}
        def pytest_collection_finish(self, session):
            for item in session.items:
                self.found[item.path.name] = state_roles(item.get_closest_marker("image"), item.path.name)

    plugin = Plugin()
    code = pytest.main(["--collect-only", "-q", "-p", "no:cacheprovider", "tests/rig"], plugins=[plugin])
    print(json.dumps({"code": int(code), "found": plugin.found}))
    """
)


def test_every_rig_test_module_has_the_roles_of_the_traceability_table():
    env = {k: v for k, v in os.environ.items() if not k.startswith(("HIL_", "GITHUB_"))}
    proc = subprocess.run(
        [sys.executable, "-c", LIST_ROLES],
        cwd=HIL_ROOT, env={**env, "PYTHONPATH": str(HIL_ROOT)}, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    result = json.loads(proc.stdout.strip().splitlines()[-1])
    assert result["code"] == 0
    assert result["found"] == {
        "test_00_contract.py": None,
        "test_10_release_baseline.py": [None, "baseline"],
        "test_11_upgrade_from_release.py": ["baseline", "commit"],
        "test_12_golden_entities.py": ["commit", "commit"],
        "test_12_serial_restore.py": ["commit", "commit"],
        "test_20_ota_qc_auto.py": ["commit", "qc-auto"],
        "test_21_qc_framework.py": ["qc-auto", "qc-auto"],
        "test_22_qc_fans.py": ["qc-auto", "qc-auto"],
        "test_23_qc_hdc1080.py": ["qc-auto", "qc-auto"],
        "test_24_qc_buttons.py": ["qc-auto", "qc-auto"],
        "test_25_qc_safe_mode.py": ["qc-auto", "qc-auto"],
        "test_30_canary.py": ["qc-auto", "canary"],
        "test_35_restore_commit.py": [None, "commit"],
        "test_40_broken_image_is_dark.py": ["commit", None],
        "test_41_uart_recovery.py": [None, "commit"],
    }


def test_the_download_code_used_by_the_bootloader_wait_is_the_readme_one():
    assert bootlog.DOWNLOAD_BOOT == {"esp32s2": "boot:0x0", "esp32c6": "boot:0x67"}
