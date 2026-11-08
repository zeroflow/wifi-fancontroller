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
        self.on_log = None
        self.log_level = None
        self.unsubscribed = False
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

    def subscribe_logs(self, on_log, log_level=None, dump_config=None):
        self.on_log = on_log
        self.log_level = log_level
        self.unsubscribed = False

        def unsubscribe():
            self.unsubscribed = True

        return unsubscribe

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




def test_wait_value_returns_a_value_that_already_satisfies(link):
    link.wait_connected(5)
    name = entities.FAN_SPEED[1]
    current().publish(name, 4.0)
    assert link.wait_value(name, lambda v: v == 4.0, 1) == 4.0


def test_wait_value_wakes_on_the_message_not_on_a_timer(link):
    link.wait_connected(5)
    name = entities.FAN_SPEED[1]
    current().publish(name, 0.0)
    threading.Timer(0.1, lambda: current().publish(name, 9.0)).start()
    started = time.monotonic()
    assert link.wait_value(name, lambda v: v > 5, 5) == 9.0
    assert time.monotonic() - started < 2


def test_wait_value_judges_the_current_value_not_an_older_one(link):
    link.wait_connected(5)
    name = entities.FAN_SPEED[1]
    current().publish(name, 9.0)
    current().publish(name, 0.0)
    assert link.wait_value(name, lambda v: v > 5, 0.2) is None


def test_wait_value_connected_but_never_satisfied_returns_none_at_the_deadline(link):
    link.wait_connected(5)
    name = entities.FAN_SPEED[1]
    current().publish(name, 1.0)
    started = time.monotonic()
    assert link.wait_value(name, lambda v: v > 5, 0.3) is None
    assert time.monotonic() - started >= 0.25


def test_wait_value_without_any_message_returns_none(link):
    link.wait_connected(5)
    assert link.wait_value(entities.FAN_SPEED[1], lambda v: True, 0.1) is None


def test_wait_value_never_offers_a_missing_reading_to_the_predicate(link):
    link.wait_connected(5)
    name = entities.FAN_SPEED[1]
    current().publish(name, 0.0, missing=True)
    assert link.wait_value(name, bool, 0.1) is None  # NaN is truthy; a missing reading must not satisfy


def test_wait_value_with_the_link_down_at_the_deadline_is_a_rig_error(link):
    link.wait_connected(5)
    FakeClient.refuse = 10**6
    drop_on_loop(link, current())
    with pytest.raises(RigError, match="link is down"):
        link.wait_value(entities.FAN_SPEED[1], lambda v: True, 0.5)


# ------------------------------------------------------------------ API log (HARN-08)


def log_message(text):
    from aioesphomeapi.api_pb2 import SubscribeLogsResponse

    return SubscribeLogsResponse(message=text)


@pytest.fixture
def logged(monkeypatch, tmp_path):
    FakeClient.instances = []
    FakeClient.version = "3.2+qc.aaaaaaaaaaaa"
    FakeClient.refuse = 0
    monkeypatch.setattr(dutlink, "APIClient", FakeClient)
    monkeypatch.setattr(dutlink, "RECONNECT_S", 0.05)
    path = tmp_path / "raw" / "api-dut-a.log"
    made = dutlink.DutLink("192.0.2.1", "key", log_path=path)
    made.log_path = path
    yield made
    made.close()


def lines(link):
    return link.log_path.read_text(encoding="utf-8").splitlines()


def test_the_log_callback_writes_one_stamped_line_per_message_with_ansi_stripped(logged):
    logged.start()
    logged.wait_connected(5)
    current().on_log(log_message(b"\x1b[0;36m[D][sensor:093]: 'Fan 1 Speed': Sending state 0.0\x1b[0m"))
    current().on_log(log_message(b"[I][app:100]: ESPHome version\r\n"))
    first, second = lines(logged)
    stamp, text = first.split(" ", 1)
    assert float(stamp) >= 0 and len(stamp.split(".")[1]) == 3
    assert text == "[D][sensor:093]: 'Fan 1 Speed': Sending state 0.0"
    assert second.split(" ", 1)[1] == "[I][app:100]: ESPHome version"


def test_boundary_lines_land_between_messages_in_arrival_order(logged):
    logged.start()
    logged.wait_connected(5)
    current().on_log(log_message(b"before"))
    logged.boundary("START tests/rig/test_x.py::test_a t=3.0")
    current().on_log(log_message(b"inside"))
    logged.boundary("END tests/rig/test_x.py::test_a passed t=4.0")
    current().on_log(log_message(b"after"))
    texts = [line.split(" ", 1)[1] for line in lines(logged)]
    assert texts == [
        "before",
        "[HIL] ===== START tests/rig/test_x.py::test_a t=3.0 =====",
        "inside",
        "[HIL] ===== END tests/rig/test_x.py::test_a passed t=4.0 =====",
        "after",
    ]
    stamps = [float(line.split(" ", 1)[0]) for line in lines(logged)]
    assert stamps == sorted(stamps)


def test_the_log_file_exists_after_start_even_when_no_connection_was_made(logged):
    FakeClient.refuse = 10_000
    logged.start()
    assert logged.log_path.is_file() and logged.log_path.read_text(encoding="utf-8") == ""
    logged.boundary("START tests/rig/test_00_contract.py::test_a t=0.0")
    assert lines(logged)[0].endswith("[HIL] ===== START tests/rig/test_00_contract.py::test_a t=0.0 =====")
    assert not logged.connected()


def test_every_session_subscribes_at_debug_level_and_stops_the_callback_when_it_drops(logged):
    from aioesphomeapi import LogLevel

    logged.start()
    logged.wait_connected(5)
    first = current()
    assert first.log_level == LogLevel.LOG_LEVEL_DEBUG
    drop_on_loop(logged, first)
    end = time.monotonic() + 5
    while len(FakeClient.instances) < 2 or not logged.connected():
        assert time.monotonic() < end
        time.sleep(0.02)
    assert first.unsubscribed and first.disconnected
    assert current().log_level == LogLevel.LOG_LEVEL_DEBUG and current() is not first


def test_the_log_callback_survives_a_message_that_is_not_valid_utf8(logged):
    logged.start()
    logged.wait_connected(5)
    current().on_log(log_message(b"bad \xff byte"))
    assert lines(logged)[0].split(" ", 1)[1].startswith("bad ")


def test_a_link_without_a_log_path_records_nothing_and_boundary_is_harmless(link, tmp_path):
    link.wait_connected(5)
    link.boundary("START x t=0.0")
    current().on_log(log_message(b"ignored"))
    assert list(tmp_path.iterdir()) == []


# ---- WR-05: no stale values after a session ends; WR-06: an unexpected error does not end polling ----


def wait_until(predicate, deadline_s=5):
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition not reached within %ss" % deadline_s)


def test_a_session_end_clears_the_latest_values_but_keeps_the_counts(link):
    link.wait_connected(5)
    name = entities.FAN_SPEED[1]
    current().publish(name, 1200.0)
    assert link.value(name) == 1200.0 and link.count(name) == 1
    FakeClient.refuse = 10**6
    drop_on_loop(link, current())
    wait_until(lambda: not link.connected())
    assert link.value(name) is None  # the old image's reading must not satisfy a later wait
    assert link.count(name) == 1  # sequence numbers go on, so wait_fresh(after=...) stays valid


def test_wait_value_does_not_accept_a_value_from_before_the_session_ended(link):
    link.wait_connected(5)
    name = entities.FAN_SPEED[1]
    current().publish(name, 1200.0)
    FakeClient.refuse = 10**6
    drop_on_loop(link, current())
    wait_until(lambda: not link.connected())
    with pytest.raises(RigError, match="link is down"):
        link.wait_value(name, lambda v: v == 1200.0, 0.2)


def test_an_unexpected_exception_in_a_session_is_logged_and_polling_goes_on(monkeypatch, tmp_path):
    FakeClient.instances = []
    FakeClient.version = "3.2+qc.aaaaaaaaaaaa"
    FakeClient.refuse = 0
    monkeypatch.setattr(dutlink, "APIClient", FakeClient)
    monkeypatch.setattr(dutlink, "RECONNECT_S", 0.05)
    real_connect = FakeClient.connect
    calls = {"n": 0}

    async def connect(self, on_stop=None, login=False, log_errors=True):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("secret detail that must not reach the log")
        return await real_connect(self, on_stop=on_stop, login=login, log_errors=log_errors)

    monkeypatch.setattr(FakeClient, "connect", connect)
    log_path = tmp_path / "api.log"
    made = dutlink.DutLink("192.0.2.1", "key", log_path=log_path)
    made.start()
    try:
        made.wait_connected(5)
    finally:
        made.close()
    text = log_path.read_text(encoding="utf-8")
    assert "[HIL] link task error: ValueError" in text
    assert "secret detail" not in text
    assert calls["n"] >= 2


# ---- use_key: the key follows the image (HARN-08 for release images) -------------------------------


def wait_for_client(count, deadline_s=5):
    end = time.monotonic() + deadline_s
    while len(FakeClient.instances) < count and time.monotonic() < end:
        time.sleep(0.01)
    assert len(FakeClient.instances) >= count


def test_use_key_ends_the_session_and_the_next_one_connects_with_the_new_key(link):
    link.wait_connected(5)
    first = current()
    assert link.use_key(None) is True
    wait_for_client(2)
    link.wait_connected(5)
    assert first.disconnected and current() is not first
    assert current().args == ("192.0.2.1", 6053, None, None)
    assert link.use_key("key") is True
    wait_for_client(3)
    link.wait_connected(5)
    assert current().args[3] == "key"


def test_use_key_with_the_same_key_keeps_the_session(link):
    link.wait_connected(5)
    first = current()
    assert link.use_key("key") is False
    time.sleep(0.2)
    assert current() is first and not first.disconnected and link.connected()


def test_use_key_before_the_first_connect_is_used_by_the_first_session(monkeypatch):
    FakeClient.instances = []
    FakeClient.refuse = 0
    monkeypatch.setattr(dutlink, "APIClient", FakeClient)
    made = dutlink.DutLink("192.0.2.1", "key")
    try:
        assert made.use_key(None) is True
        made.start()
        made.wait_connected(5)
        assert current().args[3] is None
    finally:
        made.close()
