"""Synchronous facade over the supervisor's encrypted native API.

One daemon thread owns an asyncio loop; every public method is a blocking call
with a timeout, so pytest-timeout (signal mode) can interrupt a plain call and
fixture finalizers still run. Supervisor names come from contract.py only.

Watchdog record (D-47, 03-08): the facade subscribes to the supervisor's log at WARN and records
every `<line> held for more than <n> ms, released` of the line watchdog (tag watchdog, 03-01) with
its receipt time, and records every line it drives itself (a Reset or Bootloader press drives that
DUT's EN and BOOT, set_switch(name, True) drives that line). The rig conftest's watchdog_guard
compares the two after each test: a release of a line the test drove is RIG ERROR, any other
release a warning, a counter rise no release line explains RIG ERROR (fail-closed).
"""

import asyncio
import math
import re
import threading
import time

from aioesphomeapi import (
    APIClient,
    APIConnectionError,
    BinarySensorInfo,
    BinarySensorState,
    ButtonInfo,
    LogLevel,
    SensorInfo,
    SensorState,
    SwitchInfo,
    SwitchState,
)

from . import RigError, contract

SUPERVISOR_CONNECT_S = 10
PRESS_S = 5
STATE_WAIT = 5
RELEASE_WAIT_S = 2  # after a test: how long the guard waits for release lines and counters to agree

LINES = tuple(n for lines in contract.SWITCH.values() for n in lines.values())
# The line watchdog's ESP_LOGW text (hil-rig supervisor/hil-supervisor.yaml, 03-01). The name must be
# a whole contract line followed by " held", so a look-alike such as "<line>0" never matches.
WATCHDOG_RE = re.compile(
    r"(?<!\w)(%s) held for more than \d+ ms, released"
    % "|".join(re.escape(n) for n in sorted(LINES, key=len, reverse=True))
)
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
# The lines a button press drives, from the supervisor's scripts: dut_x_reset_seq sets BOOT off and
# pulses EN; dut_x_bootloader_seq holds BOOT and pulses EN. Both only turn the USR lines off, and the
# watchdog only releases a line that is held on, so a press never drives a USR line.
BUTTON_LINES = {
    contract.BUTTON[d][kind]: (contract.SWITCH[d]["en"], contract.SWITCH[d]["boot"])
    for d in contract.BUTTON
    for kind in ("reset", "bootloader")
}


def release_line(text):
    """The contract line a watchdog release log message names, or None for any other message."""
    found = WATCHDOG_RE.search(ANSI_RE.sub("", text))
    return found.group(1) if found else None


def watchdog_verdict(released, driven, counter_rose=False):
    """D-47 (clarified 2026-11-04): what the watchdog releases during one test mean for that test.

    ("rig_error", lines): the test drove a released line (directly, or through Reset/Bootloader).
    ("unknown", []): a counter rose by more than the release lines explain (fail-closed).
    ("warning", lines): lines were released that the test never drove; the test result stands.
    ("none", []): nothing was released and no counter rose.
    """
    released = list(dict.fromkeys(released))
    driven = set(driven)
    hit = [line for line in released if line in driven]
    if hit:
        return "rig_error", hit
    if counter_rose:
        return "unknown", []
    if released:
        return "warning", released
    return "none", []


def watchdog_delta(start, end):
    """{dut: end - start} per DUT of contract.WATCHDOG_RELEASES; None for a DUT without both values."""
    start = start if isinstance(start, dict) else {}
    end = end if isinstance(end, dict) else {}
    delta = {}
    for dut_id in contract.WATCHDOG_RELEASES:
        a, b = start.get(dut_id), end.get(dut_id)
        delta[dut_id] = None if a is None or b is None else int(b) - int(a)
    return delta


def watchdog_guard_outcome(sv, t0, start, nodeid, wait_s=RELEASE_WAIT_S, clock=time.monotonic, sleep=time.sleep):
    """(warnings, error) for one test that started at t0 with the counters `start` (D-47).

    When something happened (a release line since t0 or a counter rise), waits up to wait_s for the
    release lines of each DUT and its counter rise to agree (the line arrives at once, the counter
    sensor publishes every second). A release line received after this returns counts for the next
    test. `error` is the RigError message, or None; every release of a line the test did not drive
    is one warning naming the line and the test.
    """
    deadline = clock() + wait_s
    while True:
        released = sv.releases_since(t0)
        end = sv.watchdog_counts()
        rise = {d: end[d] - start[d] for d in contract.WATCHDOG_RELEASES}
        named = {d: sum(1 for n in released if n in contract.SWITCH[d].values()) for d in contract.WATCHDOG_RELEASES}
        if not released and not any(rise.values()):
            return [], None
        if rise == named or clock() >= deadline:
            break
        sleep(0.1)
    unexplained = [d for d in contract.WATCHDOG_RELEASES if rise[d] > named[d] or rise[d] < 0]
    kind, lines = watchdog_verdict(released, sv.driven_since(t0), counter_rose=bool(unexplained))
    # Every released line the test did not drive is a warning, whatever else the verdict says.
    others = [n for n in dict.fromkeys(released) if not (kind == "rig_error" and n in lines)]
    warnings = [
        "supervisor watchdog released %s during %s; the test did not drive that line" % (n, nodeid) for n in others
    ]
    if kind == "rig_error":
        return warnings, "supervisor watchdog released %s during this test, and the test drove that line" % ", ".join(lines)
    if kind == "unknown":
        parts = []
        for d in unexplained:
            name = contract.WATCHDOG_RELEASES[d]
            if rise[d] < 0:
                parts.append(
                    "supervisor watchdog counter %s fell during this test (%d -> %d); the supervisor restarted "
                    "and a release cannot be ruled out" % (name, start[d], end[d])
                )
            else:
                parts.append(
                    "supervisor watchdog counter %s rose during this test (%d -> %d) without a release line; "
                    "the released line cannot be ruled out" % (name, start[d], end[d])
                )
        return warnings, "; ".join(parts)
    return warnings, None


class Supervisor:
    def __init__(self, host, key):
        self._host = host
        self._key = key
        self._client = None
        self._entities = {}  # name -> (info class, key)
        self._name_list = []  # every entity name as reported, in order, duplicates kept
        self._names = {}  # key -> name
        self._states = {}  # name -> bool (switches and binary sensors)
        self._values = {}  # name -> float, or None when the sensor reported no value (sensors, RIG-06)
        self._releases = []  # (receipt time, line) of every watchdog release log line (D-47)
        self._driven = []  # (command time, line) of every line this facade drove (D-47)
        self._record_lock = threading.Lock()
        self._closed = False
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, name="hil-supervisor-loop", daemon=True)
        self._thread.start()

    # ------------------------------------------------------------ plumbing

    def run(self, coro, timeout):
        """Run a coroutine on the facade's loop and wait for it (public: Dut uses it too)."""
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout)
        except TimeoutError:
            future.cancel()
            raise RigError("supervisor call timed out after %ss" % timeout) from None

    def _on_state(self, state):
        name = self._names.get(state.key)
        if name is None:
            return
        if isinstance(state, (SwitchState, BinarySensorState)):
            self._states[name] = bool(state.state)
        elif isinstance(state, SensorState):
            # A sensor without a value is None, never 0: a missing client count must not pass (RIG-06).
            value = None if state.missing_state else float(state.state)
            self._values[name] = None if value is None or math.isnan(value) else value

    def _on_log(self, msg):
        """A supervisor log message: a watchdog release is recorded with its receipt time, all else ignored."""
        try:
            text = bytes(msg.message).decode("utf-8")
        except (UnicodeDecodeError, TypeError, AttributeError):
            return
        line = release_line(text)
        if line is not None:
            with self._record_lock:
                self._releases.append((time.monotonic(), line))

    def _drove(self, lines):
        now = time.monotonic()
        with self._record_lock:
            self._driven.extend((now, line) for line in lines)

    def _has_state(self, name):
        return name in self._states or name in self._values

    async def _connect(self):
        client = APIClient(self._host, contract.API_PORT, None, noise_psk=self._key)
        try:
            async with asyncio.timeout(SUPERVISOR_CONNECT_S):
                await client.connect(login=True)
                entities, _services = await client.list_entities_services()
        except (APIConnectionError, OSError, TimeoutError) as exc:
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001 - best effort while failing anyway
                pass
            raise RigError("supervisor connection failed (%s)" % type(exc).__name__) from None
        self._name_list = [entity.name for entity in entities]
        for entity in entities:
            if isinstance(entity, (ButtonInfo, SwitchInfo, BinarySensorInfo, SensorInfo)):
                self._entities[entity.name] = (type(entity), entity.key)
                self._names[entity.key] = entity.name
        self._client = client
        client.subscribe_states(self._on_state)
        client.subscribe_logs(self._on_log, log_level=LogLevel.LOG_LEVEL_WARN)
        wanted = [n for n in self._entities if n in contract.REQUIRED_ENTITIES and self._entities[n][0] is not ButtonInfo]
        deadline = time.monotonic() + STATE_WAIT
        while time.monotonic() < deadline and any(not self._has_state(n) for n in wanted):
            await asyncio.sleep(0.1)

    def _lookup(self, name, kind):
        found = self._entities.get(name)
        if found is None or found[0] is not kind:
            raise RigError("entity '%s' missing on supervisor" % name)
        return found[1]

    async def _command(self, function, *args):
        function(*args)

    # -------------------------------------------------------------- public

    def connect(self):
        self.run(self._connect(), SUPERVISOR_CONNECT_S + STATE_WAIT + 5)

    def entity_names(self):
        return set(self._entities)

    def entity_name_list(self):
        """Every entity name from the one list_entities_services() call, as reported."""
        return list(self._name_list)

    @staticmethod
    def contract_problems(names):
        """Contract violations in a reported name list; empty when conformant (RIG-03).

        Names compare with exact str equality: case, whitespace and prefixes all count.
        """
        problems = ["entity '%s' missing on supervisor" % n for n in sorted(contract.REQUIRED_ENTITIES - set(names))]
        for name in sorted(contract.REQUIRED_ENTITIES):
            count = list(names).count(name)
            if count > 1:
                problems.append("entity '%s' reported %d times" % (name, count))
        return problems

    def switch_is_on(self, name):
        """Last reported state of a contract switch: True, False, or None when never reported."""
        return self._states.get(name)

    def press(self, name):
        key = self._lookup(name, ButtonInfo)
        self._drove(BUTTON_LINES.get(name, ()))  # recorded before the command: a press that fails may still have driven
        self.run(self._command(self._client.button_command, key), PRESS_S)

    def set_switch(self, name, on):
        key = self._lookup(name, SwitchInfo)
        if on:
            self._drove((name,))  # an OFF command never holds a line, so it is never recorded
        try:
            self.run(self._command(self._client.switch_command, key, bool(on)), PRESS_S)
        except APIConnectionError as exc:
            raise RigError("switch '%s' command failed (%s)" % (name, type(exc).__name__)) from None

    def release_all(self):
        """Best effort on every contract switch: command each one OFF, whatever happens to the others.

        A switch that cannot be commanded (renamed entity, dropped connection, press timeout)
        never stops the loop; the failures are collected and raised once, as a RigError, after
        every line has been tried and given STATE_WAIT seconds to report OFF.
        """
        names = [n for lines in contract.SWITCH.values() for n in lines.values()]
        failed = []
        for name in names:
            try:
                self.set_switch(name, False)
            except RigError:
                failed.append(name)
        deadline = time.monotonic() + STATE_WAIT
        while True:
            pending = [n for n in names if n not in failed and self._states.get(n) is not False]
            if not pending:
                break
            if time.monotonic() >= deadline:
                failed.extend(pending)
                break
            time.sleep(0.1)
        if failed:
            raise RigError("switch '%s' not released" % "', '".join(sorted(failed)))

    def sensor_value(self, name):
        """Last reported value of a contract sensor as a float, or None when it has no value (RIG-06).

        RigError when the supervisor has no sensor of that name.
        """
        self._lookup(name, SensorInfo)
        return self._values.get(name)

    def watchdog_counts(self):
        """{dut: int} of both Watchdog Releases counters; RigError naming a counter without a value."""
        counts = {}
        for dut_id, name in contract.WATCHDOG_RELEASES.items():
            value = self.sensor_value(name)
            if value is None:
                raise RigError("%s has no value" % name)
            counts[dut_id] = int(value)
        return counts

    def releases_since(self, t):
        """The lines the supervisor's watchdog released, received at or after monotonic time t, in order."""
        with self._record_lock:
            return [line for at, line in self._releases if at >= t]

    def driven_since(self, t):
        """The lines this facade drove at or after monotonic time t, in order (duplicates kept)."""
        with self._record_lock:
            return [line for at, line in self._driven if at >= t]

    def serial_connected(self, dut_id):
        name = contract.SERIAL_CONNECTED[dut_id]
        self._lookup(name, BinarySensorInfo)
        return bool(self._states.get(name, False))

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self._client is not None:
                self.run(self._client.disconnect(), PRESS_S)
        except Exception:  # noqa: BLE001 - closing must never mask the real failure
            pass
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(5)
