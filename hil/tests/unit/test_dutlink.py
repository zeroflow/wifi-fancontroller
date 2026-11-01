"""DutLink: one reconnecting API session with per-entity message counts (no hardware)."""

import asyncio
import threading
import time

import pytest
from aioesphomeapi import (
    APIConnectionError,
    ButtonInfo,
    DeviceInfo,
    FanInfo,
    SensorInfo,
    SensorState,
)

from hil import RigError, dutlink, entities

KEYS = {entities.FAN[1]: 1, entities.FAN_SPEED[1]: 2, entities.QC_SAFE_MODE: 3}
INFOS = [
    FanInfo(name=entities.FAN[1], key=1),
    SensorInfo(name=entities.FAN_SPEED[1], key=2),
    ButtonInfo(name=entities.QC_SAFE_MODE, key=3),
]


class FakeClient:
    """Stands in for aioesphomeapi.APIClient; every instance is remembered."""

    instances = []
    version = "3.2+qc.aaaaaaaaaaaa"
    refuse = 0  # next N connects fail

    def __init__(self, host, port, password, noise_psk=None):
        self.args = (host, port, password, noise_psk)
        self.commands = []
        self.disconnected = False
        self.on_stop = None
        self.on_state = None
        FakeClient.instances.append(self)

    async def connect(self, on_stop=None, login=False, log_errors=True):
        if FakeClient.refuse > 0:
            FakeClient.refuse -= 1
            raise APIConnectionError("refused")
        self.on_stop = on_stop

    async def device_info(self):
        return DeviceInfo(project_version=FakeClient.version)

    async def list_entities_services(self):
        return list(INFOS), []

    def subscribe_states(self, on_state):
        self.on_state = on_state

    def fan_command(self, key, state=None, speed=None, speed_level=None, **kwargs):
        self.commands.append(("fan", key, state, speed_level))

    def button_command(self, key, device_id=0):
        self.commands.append(("button", key))

    async def disconnect(self, force=False):
        self.disconnected = True

    # test helpers
    def publish(self, name, value, missing=False):
        self.on_state(SensorState(key=KEYS[name], state=value, missing_state=missing))


@pytest.fixture
def link(monkeypatch):
    FakeClient.instances = []
    FakeClient.version = "3.2+qc.aaaaaaaaaaaa"
    FakeClient.refuse = 0
    monkeypatch.setattr(dutlink, "APIClient", FakeClient)
    monkeypatch.setattr(dutlink, "RECONNECT_S", 0.05)
    made = dutlink.DutLink("192.0.2.1", "key")
    made.start()
    yield made
    made.close()


def current():
    return FakeClient.instances[-1]


def drop_on_loop(link, client):
    asyncio.run_coroutine_threadsafe(client.on_stop(False), link._loop).result(5)


def test_connects_with_the_key_on_the_native_api_port_and_caches_the_device_info(link):
    info = link.wait_connected(5)
    assert info.project_version == "3.2+qc.aaaaaaaaaaaa"
    assert link.connected() and link.device_info() is info
    assert current().args == ("192.0.2.1", 6053, None, "key")


def test_count_increments_on_every_message_also_when_the_value_is_unchanged(link):
    link.wait_connected(5)
    name = entities.FAN_SPEED[1]
    assert link.count(name) == 0 and link.value(name) is None
    for _ in range(3):
        current().publish(name, 0.0)
    assert link.count(name) == 3
    assert link.value(name) == 0.0


def test_wait_fresh_returns_only_messages_after_the_given_count(link):
    link.wait_connected(5)
    name = entities.FAN_SPEED[1]
    current().publish(name, 10.0)
    after = link.count(name)
    threading.Timer(0.1, lambda: [current().publish(name, v) for v in (1.0, 2.0, 3.0)]).start()
    assert link.wait_fresh(name, after, 2, 5) == [1.0, 2.0]


def test_wait_fresh_when_connected_but_silent_returns_the_shorter_list(link):
    link.wait_connected(5)
    name = entities.FAN_SPEED[1]
    current().publish(name, 4.0)
    started = time.monotonic()
    assert link.wait_fresh(name, 0, 3, 0.3) == [4.0]
    assert time.monotonic() - started >= 0.25
    assert link.wait_fresh(name, link.count(name), 2, 0.1) == []


def test_a_missing_sensor_reading_is_nan_never_zero(link):
    link.wait_connected(5)
    name = entities.FAN_SPEED[1]
    current().publish(name, 0.0, missing=True)
    (value,) = link.wait_fresh(name, 0, 1, 1)
    assert value != value


def test_wait_fresh_with_the_link_down_at_the_deadline_is_a_rig_error(link):
    link.wait_connected(5)
    FakeClient.refuse = 10**6
    drop_on_loop(link, current())
    with pytest.raises(RigError, match="link is down"):
        link.wait_fresh(entities.FAN_SPEED[1], 0, 1, 0.5)


def test_reconnects_by_polling_after_a_drop_and_keeps_the_counts(link):
    link.wait_connected(5)
    name = entities.FAN_SPEED[1]
    first = current()
    first.publish(name, 1.0)
    FakeClient.version = "3.2+canary.bbbbbbbbbbbb"
    drop_on_loop(link, first)
    info = link.wait_connected(5, project_version="3.2+canary.bbbbbbbbbbbb")
    assert info.project_version == "3.2+canary.bbbbbbbbbbbb"
    assert first.disconnected and current() is not first
    current().publish(name, 2.0)
    assert link.count(name) == 2


def test_connect_failures_are_polled_not_fatal(link):
    link.wait_connected(5)
    FakeClient.refuse = 3
    drop_on_loop(link, current())
    link.wait_connected(5)
    assert len(FakeClient.instances) >= 5  # the first, three refused, one that worked


def test_wait_connected_names_the_deadline_and_what_it_saw(link):
    link.wait_connected(5)
    with pytest.raises(RigError, match=r"not ready within 0\.2s \(last: 3\.2\+qc\.aaaaaaaaaaaa\)"):
        link.wait_connected(0.2, project_version="3.2+canary.bbbbbbbbbbbb")


def test_fan_command_maps_the_name_to_the_key(link):
    link.wait_connected(5)
    link.fan(1, True, 50)
    link.fan(1, False)
    assert current().commands == [("fan", 1, True, 50), ("fan", 1, False, None)]


def test_fan_without_that_entity_is_a_rig_error_naming_it(link):
    link.wait_connected(5)
    with pytest.raises(RigError, match="entity '%s' missing on the DUT" % entities.FAN[2]):
        link.fan(2, True, 50)


def test_commands_with_the_link_down_are_a_rig_error(link):
    link.wait_connected(5)
    FakeClient.refuse = 10**6
    drop_on_loop(link, current())
    deadline = time.monotonic() + 5
    while link.connected() and time.monotonic() < deadline:
        time.sleep(0.01)
    with pytest.raises(RigError, match="link is down"):
        link.fan(1, False)


def test_press_sends_a_button_command(link):
    link.wait_connected(5)
    link.press(entities.QC_SAFE_MODE)
    assert current().commands == [("button", 3)]
    with pytest.raises(RigError, match="missing on the DUT"):
        link.press(entities.FAN[1])  # a fan is not a button


def test_close_disconnects_the_client_and_is_repeatable(link):
    link.wait_connected(5)
    client = current()
    link.close()
    assert client.disconnected
    link.close()


def test_close_while_never_connected_does_not_hang(monkeypatch):
    FakeClient.instances = []
    FakeClient.refuse = 10**6
    monkeypatch.setattr(dutlink, "APIClient", FakeClient)
    monkeypatch.setattr(dutlink, "RECONNECT_S", 0.05)
    made = dutlink.DutLink("192.0.2.1", "key")
    made.start()
    time.sleep(0.2)
    started = time.monotonic()
    made.close()
    assert time.monotonic() - started < 3
    assert all(c.disconnected for c in FakeClient.instances)
    assert not made.connected()
