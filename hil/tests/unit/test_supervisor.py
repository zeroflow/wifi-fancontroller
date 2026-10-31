"""Supervisor.release_all is best effort: every line is commanded off, failures are raised once (CR-01)."""

import pytest
from aioesphomeapi import APIConnectionError, SwitchInfo

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
