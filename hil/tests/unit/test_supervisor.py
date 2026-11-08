"""Supervisor.release_all is best effort: every line is commanded off, failures are raised once (CR-01)."""

import pytest
from aioesphomeapi import APIConnectionError, SensorInfo, SensorState, SwitchInfo, SwitchState

from hil import RigError, contract
from hil.supervisor import Supervisor

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
