"""Supervisor.release_all is best effort: every line is commanded off, failures are raised once (CR-01).

Also the sensors (RIG-06) and the watchdog record of 03-08 (D-47): release log lines, driven lines, the guard."""

import time
from types import SimpleNamespace

import pytest
from aioesphomeapi import APIConnectionError, ButtonInfo, LogLevel, SensorInfo, SensorState, SwitchInfo, SwitchState

from hil import RigError, contract
from hil import supervisor as supervisor_module
from hil.supervisor import Supervisor, watchdog_delta, watchdog_guard_outcome, watchdog_verdict

SWITCHES = [n for lines in contract.SWITCH.values() for n in lines.values()]


class FakeClient:
    """Records every switch command; commands for keys in `broken` raise like a dropped connection."""

    def __init__(self, broken=()):
        self.broken = set(broken)
        self.commands = []

    def switch_command(self, key, state):
        if key in self.broken:
            raise APIConnectionError("link down")
        self.commands.append((key, state))


@pytest.fixture
def sv():
    supervisor = Supervisor("192.0.2.10", None)
    for key, name in enumerate(SWITCHES, start=1):
        supervisor._entities[name] = (SwitchInfo, key)
        supervisor._names[key] = name
        supervisor._states[name] = False
    yield supervisor
    supervisor.close()


def key_of(name):
    return SWITCHES.index(name) + 1


def test_release_all_commands_every_switch_off(sv):
    sv._client = FakeClient()
    sv.release_all()
    assert sorted(sv._client.commands) == [(k, False) for k in range(1, len(SWITCHES) + 1)]


def test_a_failing_first_switch_does_not_stop_the_others(sv):
    first = SWITCHES[0]
    sv._client = FakeClient(broken=[key_of(first)])
    with pytest.raises(RigError) as raised:
        sv.release_all()
    assert first in str(raised.value)
    commanded = {key for key, _state in sv._client.commands}
    assert commanded == {key_of(n) for n in SWITCHES} - {key_of(first)}


def test_connection_errors_become_rig_errors_and_all_failures_are_named(sv):
    sv._client = FakeClient(broken=[key_of(n) for n in SWITCHES])
    with pytest.raises(RigError) as raised:
        sv.release_all()
    for name in SWITCHES:
        assert name in str(raised.value)


def test_set_switch_converts_api_connection_error(sv):
    sv._client = FakeClient(broken=[key_of(SWITCHES[0])])
    with pytest.raises(RigError, match="APIConnectionError"):
        sv.set_switch(SWITCHES[0], False)


def test_a_missing_entity_is_reported_after_the_rest_are_released(sv):
    gone = SWITCHES[2]
    del sv._entities[gone]
    sv._client = FakeClient()
    with pytest.raises(RigError) as raised:
        sv.release_all()
    assert gone in str(raised.value)
    assert len(sv._client.commands) == len(SWITCHES) - 1


def test_a_switch_that_never_reports_off_is_named(sv, monkeypatch):
    monkeypatch.setattr("hil.supervisor.STATE_WAIT", 0.2)
    stuck = SWITCHES[4]
    sv._states[stuck] = True
    sv._client = FakeClient()
    with pytest.raises(RigError) as raised:
        sv.release_all()
    assert stuck in str(raised.value)


# ------------------------------------------------------------------ sensors (RIG-06)

CLIENTS_A = contract.SERIAL_CLIENTS["A"]
RELEASES_B = contract.WATCHDOG_RELEASES["B"]
SENSOR_KEYS = {CLIENTS_A: 101, RELEASES_B: 102}


@pytest.fixture
def sensors(sv):
    for name, key in SENSOR_KEYS.items():
        sv._entities[name] = (SensorInfo, key)
        sv._names[key] = name
    return sv


def test_a_sensor_state_is_stored_as_a_float_apart_from_the_booleans(sensors):
    sensors._on_state(SensorState(key=SENSOR_KEYS[CLIENTS_A], state=2.0, missing_state=False))
    assert sensors.sensor_value(CLIENTS_A) == 2.0 and isinstance(sensors.sensor_value(CLIENTS_A), float)
    assert CLIENTS_A not in sensors._states


def test_a_zero_count_is_zero_not_missing(sensors):
    sensors._on_state(SensorState(key=SENSOR_KEYS[CLIENTS_A], state=0.0, missing_state=False))
    assert sensors.sensor_value(CLIENTS_A) == 0.0 and sensors.sensor_value(CLIENTS_A) is not None


def test_a_missing_state_is_none_never_zero(sensors):
    sensors._on_state(SensorState(key=SENSOR_KEYS[CLIENTS_A], state=0.0, missing_state=True))
    assert sensors.sensor_value(CLIENTS_A) is None


def test_a_nan_state_is_none(sensors):
    sensors._on_state(SensorState(key=SENSOR_KEYS[RELEASES_B], state=float("nan"), missing_state=False))
    assert sensors.sensor_value(RELEASES_B) is None


def test_a_sensor_that_never_reported_is_none(sensors):
    assert sensors.sensor_value(RELEASES_B) is None


def test_a_later_value_replaces_a_missing_one(sensors):
    key = SENSOR_KEYS[RELEASES_B]
    sensors._on_state(SensorState(key=key, state=0.0, missing_state=True))
    sensors._on_state(SensorState(key=key, state=4.0, missing_state=False))
    assert sensors.sensor_value(RELEASES_B) == 4.0


def test_sensor_value_of_an_unknown_or_non_sensor_name_is_a_rig_error(sensors):
    with pytest.raises(RigError, match="missing on supervisor"):
        sensors.sensor_value(contract.SERIAL_CLIENTS["B"])
    with pytest.raises(RigError, match="missing on supervisor"):
        sensors.sensor_value(SWITCHES[0])


def test_switch_booleans_are_unchanged_by_sensor_states(sensors):
    sensors._on_state(SwitchState(key=key_of(SWITCHES[1]), state=True))
    sensors._on_state(SensorState(key=SENSOR_KEYS[CLIENTS_A], state=1.0, missing_state=False))
    assert sensors.switch_is_on(SWITCHES[1]) is True
    assert sensors.sensor_value(CLIENTS_A) == 1.0


# --------------------------------------------- watchdog releases across a run (03-08, D-47)


EN_A, BOOT_A = contract.SWITCH["A"]["en"], contract.SWITCH["A"]["boot"]
USR1_A, USR2_A = contract.SWITCH["A"]["usr1"], contract.SWITCH["A"]["usr2"]
EN_B = contract.SWITCH["B"]["en"]
RESET_A, BOOTLOADER_A = contract.BUTTON["A"]["reset"], contract.BUTTON["A"]["bootloader"]
RESET_B = contract.BUTTON["B"]["reset"]
RELEASES = contract.WATCHDOG_RELEASES


def release_log(name, limit=30000, ansi=True):
    """A supervisor log message as aioesphomeapi delivers it: bytes, with the ANSI colour codes of ESP_LOGW."""
    text = "[W][watchdog:473]: %s held for more than %d ms, released" % (name, limit)
    if ansi:
        text = "\x1b[0;33m" + text + "\x1b[0m"
    return SimpleNamespace(level=2, message=text.encode("utf-8"))


class CommandClient(FakeClient):
    def __init__(self):
        super().__init__()
        self.buttons = []

    def button_command(self, key):
        self.buttons.append(key)


@pytest.fixture
def wd(sv):
    """The facade with buttons, both Watchdog Releases sensors and a client that takes commands."""
    for offset, name in enumerate(sorted(n for d in contract.BUTTON.values() for n in d.values()) + [contract.SUPERVISOR_RESTART]):
        sv._entities[name] = (ButtonInfo, 200 + offset)
        sv._names[200 + offset] = name
    for offset, name in enumerate(sorted(RELEASES.values())):
        sv._entities[name] = (SensorInfo, 300 + offset)
        sv._names[300 + offset] = name
        sv._values[name] = 0.0
    sv._client = CommandClient()
    return sv


def test_a_watchdog_log_line_is_recorded_as_a_release_of_its_line(wd):
    t0 = time.monotonic()
    wd._on_log(release_log(USR1_A))
    assert wd.releases_since(t0) == [USR1_A]


def test_a_watchdog_line_without_ansi_codes_and_each_contract_line_is_recognised(wd):
    t0 = time.monotonic()
    names = [n for d in "AB" for n in contract.SWITCH[d].values()]
    for name in names:
        wd._on_log(release_log(name, limit=5000, ansi=False))
    assert wd.releases_since(t0) == names


@pytest.mark.parametrize("text", [
    "[D][switch:055]: '%s' Turning ON." % EN_A,
    "[W][api.connection:123]: %s held the API too long" % EN_A,
    "[W][watchdog:473]: %s0 held for more than 5000 ms, released" % contract.SWITCH["A"]["usr3"],
    "[I][app:100]: Supervisor ready",
])
def test_other_log_lines_are_ignored(wd, text):
    wd._on_log(SimpleNamespace(level=2, message=text.encode("utf-8")))
    assert wd.releases_since(0) == []


def test_a_log_message_that_is_not_utf8_is_ignored_without_raising(wd):
    wd._on_log(SimpleNamespace(level=2, message=b"\xff\xfe\x00"))
    assert wd.releases_since(0) == []


def test_releases_since_counts_by_receipt_time(wd):
    wd._on_log(release_log(EN_B))
    t1 = time.monotonic()
    wd._on_log(release_log(USR1_A))
    assert wd.releases_since(0) == [EN_B, USR1_A]
    assert wd.releases_since(t1) == [USR1_A]


def test_a_reset_press_drives_en_and_boot_of_its_dut(wd):
    t0 = time.monotonic()
    wd.press(RESET_A)
    assert sorted(wd.driven_since(t0)) == sorted([EN_A, BOOT_A])


def test_a_bootloader_press_drives_en_and_boot_and_never_a_usr_line(wd):
    t0 = time.monotonic()
    wd.press(BOOTLOADER_A)
    driven = wd.driven_since(t0)
    assert sorted(driven) == sorted([EN_A, BOOT_A])
    assert not any(n in driven for n in contract.SWITCH["A"].values() if n not in (EN_A, BOOT_A))


def test_a_press_of_dut_b_reset_drives_dut_b_lines_only(wd):
    t0 = time.monotonic()
    wd.press(RESET_B)
    assert sorted(wd.driven_since(t0)) == sorted([contract.SWITCH["B"]["en"], contract.SWITCH["B"]["boot"]])


def test_the_supervisor_restart_button_drives_no_line(wd):
    t0 = time.monotonic()
    wd.press(contract.SUPERVISOR_RESTART)
    assert wd.driven_since(t0) == []


def test_set_switch_on_drives_that_line_and_off_or_release_all_drive_nothing(wd):
    t0 = time.monotonic()
    wd.set_switch(USR2_A, False)
    wd.release_all()
    assert wd.driven_since(t0) == []
    wd.set_switch(USR2_A, True)
    assert wd.driven_since(t0) == [USR2_A]


def test_driven_since_counts_by_command_time(wd):
    wd.set_switch(USR1_A, True)
    t1 = time.monotonic()
    wd.set_switch(USR2_A, True)
    assert wd.driven_since(t1) == [USR2_A]


def test_watchdog_verdict_rig_error_when_the_test_drove_the_released_line():
    assert watchdog_verdict(released=[USR1_A], driven=[USR1_A]) == ("rig_error", [USR1_A])


def test_watchdog_verdict_warning_when_the_test_did_not_drive_the_released_line():
    assert watchdog_verdict(released=[EN_B], driven=[EN_A]) == ("warning", [EN_B])


def test_watchdog_verdict_unknown_when_a_counter_rose_without_a_release_line():
    assert watchdog_verdict(released=[], driven=[EN_A], counter_rose=True) == ("unknown", [])


def test_watchdog_verdict_none_when_nothing_was_released_and_no_counter_rose():
    assert watchdog_verdict(released=[], driven=[EN_A, BOOT_A]) == ("none", [])


def test_watchdog_verdict_names_only_the_driven_lines_when_a_driven_and_another_line_were_released():
    assert watchdog_verdict(released=[EN_B, USR1_A, USR1_A], driven=[USR1_A]) == ("rig_error", [USR1_A])


def test_watchdog_verdict_an_unattributed_rise_beats_a_warning():
    assert watchdog_verdict(released=[EN_B], driven=[], counter_rose=True) == ("unknown", [])


def test_watchdog_delta_per_dut():
    assert watchdog_delta({"A": 2, "B": 0}, {"A": 3, "B": 0}) == {"A": 1, "B": 0}


@pytest.mark.parametrize("start, end, expected", [
    ({"A": 2}, {"A": 3, "B": 0}, {"A": 1, "B": None}),
    ({"A": 2, "B": None}, {"A": 2, "B": 1}, {"A": 0, "B": None}),
    (None, {"A": 2, "B": 1}, {"A": None, "B": None}),
    ({"A": 2, "B": 0}, None, {"A": None, "B": None}),
])
def test_watchdog_delta_is_none_for_a_dut_with_a_missing_value(start, end, expected):
    assert watchdog_delta(start, end) == expected


def test_watchdog_counts_reads_both_counters_as_ints(wd):
    wd._values[RELEASES["A"]] = 6.0
    wd._values[RELEASES["B"]] = 1.0
    assert wd.watchdog_counts() == {"A": 6, "B": 1}


def test_watchdog_counts_without_a_value_is_a_rig_error_naming_the_counter(wd):
    wd._values[RELEASES["B"]] = None
    with pytest.raises(RigError, match=RELEASES["B"]):
        wd.watchdog_counts()


# The guard's decision after a test (conftest.watchdog_guard calls watchdog_guard_outcome).

NODE = "tests/rig/test_10_smoke_dut_a.py::test_commit_image_boots_and_reports_build_id"


def no_sleep(_seconds):
    pass


def test_guard_quiet_test_gives_no_warning_and_no_error(wd):
    t0 = time.monotonic()
    start = wd.watchdog_counts()
    wd.press(RESET_A)
    assert watchdog_guard_outcome(wd, t0, start, NODE, sleep=no_sleep) == ([], None)


def test_guard_a_release_of_a_line_the_test_did_not_drive_is_a_warning_naming_line_and_test(wd):
    t0 = time.monotonic()
    start = wd.watchdog_counts()
    wd.press(RESET_A)
    wd._on_log(release_log(EN_B, limit=5000))
    wd._values[RELEASES["B"]] = 1.0
    warns, error = watchdog_guard_outcome(wd, t0, start, NODE, sleep=no_sleep)
    assert error is None
    assert warns == ["supervisor watchdog released %s during %s; the test did not drive that line" % (EN_B, NODE)]


def test_guard_a_release_of_a_line_the_test_drove_is_a_rig_error(wd):
    t0 = time.monotonic()
    start = wd.watchdog_counts()
    wd.set_switch(USR1_A, True)
    wd._on_log(release_log(USR1_A))
    wd._values[RELEASES["A"]] = 1.0
    warns, error = watchdog_guard_outcome(wd, t0, start, NODE, sleep=no_sleep)
    assert warns == []
    assert error == "supervisor watchdog released %s during this test, and the test drove that line" % USR1_A


def test_guard_a_counter_rise_without_a_release_line_is_a_rig_error_naming_the_counter(wd):
    t0 = time.monotonic()
    start = wd.watchdog_counts()
    wd._values[RELEASES["B"]] = 2.0
    slept = []
    warns, error = watchdog_guard_outcome(wd, t0, start, NODE, sleep=slept.append, wait_s=0.3)
    assert warns == []
    assert error == (
        "supervisor watchdog counter %s rose during this test (0 -> 2) without a release line; "
        "the released line cannot be ruled out" % RELEASES["B"]
    )
    assert slept, "the guard waits for the release line before it decides"


def test_guard_two_releases_but_one_line_is_unattributed(wd):
    t0 = time.monotonic()
    start = wd.watchdog_counts()
    wd._on_log(release_log(EN_B, limit=5000))
    wd._values[RELEASES["B"]] = 2.0
    warns, error = watchdog_guard_outcome(wd, t0, start, NODE, sleep=no_sleep, wait_s=0.2)
    assert RELEASES["B"] in error and "(0 -> 2)" in error
    assert warns == ["supervisor watchdog released %s during %s; the test did not drive that line" % (EN_B, NODE)]


def test_guard_waits_for_a_late_counter_update_before_it_decides(wd):
    t0 = time.monotonic()
    start = wd.watchdog_counts()
    wd._on_log(release_log(EN_B, limit=5000))

    def late_update(_seconds):
        wd._values[RELEASES["B"]] = 1.0

    warns, error = watchdog_guard_outcome(wd, t0, start, NODE, sleep=late_update)
    assert error is None and len(warns) == 1


def test_guard_waits_for_a_late_release_line_before_it_calls_a_rise_unattributed(wd):
    t0 = time.monotonic()
    start = wd.watchdog_counts()
    wd._values[RELEASES["B"]] = 1.0

    def late_line(_seconds):
        if not wd.releases_since(t0):
            wd._on_log(release_log(EN_B, limit=5000))

    warns, error = watchdog_guard_outcome(wd, t0, start, NODE, sleep=late_line)
    assert error is None and EN_B in warns[0]


def test_guard_a_release_before_the_test_started_counts_for_the_earlier_test(wd):
    wd._on_log(release_log(EN_B, limit=5000))
    wd._values[RELEASES["B"]] = 1.0
    t0 = time.monotonic()
    start = wd.watchdog_counts()
    assert watchdog_guard_outcome(wd, t0, start, NODE, sleep=no_sleep) == ([], None)


def test_guard_a_counter_that_fell_is_a_rig_error(wd):
    wd._values[RELEASES["A"]] = 6.0
    t0 = time.monotonic()
    start = wd.watchdog_counts()
    wd._values[RELEASES["A"]] = 0.0
    _warns, error = watchdog_guard_outcome(wd, t0, start, NODE, sleep=no_sleep, wait_s=0.1)
    assert RELEASES["A"] in error and "(6 -> 0)" in error


class LogClient:
    """Stands in for APIClient in _connect: no entities, records the log subscription."""

    instances = []

    def __init__(self, *args, **kwargs):
        self.subscribed = None
        LogClient.instances.append(self)

    async def connect(self, login=True):
        return None

    async def list_entities_services(self):
        return [], []

    def subscribe_states(self, callback):
        pass

    def subscribe_logs(self, on_log, log_level=None, dump_config=None):
        self.subscribed = (on_log, log_level)
        return lambda: None

    async def disconnect(self):
        pass


def test_connect_subscribes_to_the_supervisor_log_at_warning_level(monkeypatch):
    monkeypatch.setattr(supervisor_module, "APIClient", LogClient)
    LogClient.instances.clear()
    sv = Supervisor("192.0.2.10", None)
    try:
        sv.connect()
        on_log, level = LogClient.instances[-1].subscribed
        assert level == LogLevel.LOG_LEVEL_WARN
        on_log(release_log(EN_B, limit=5000))
        assert sv.releases_since(0) == [EN_B]
    finally:
        sv.close()
