"""One persistent API session to a DUT: states, per-entity message counts, commands.

A daemon thread owns an asyncio loop (same structure as Supervisor). The maintenance
task connects, subscribes to every state and, when the link drops (reboot, OTA),
waits one second and connects again with a fresh client: a poll with a deadline, no
ReconnectLogic (it is mDNS-driven and mDNS does not cross the VLAN). The client is
always disconnected in a finally block: a leaked API slot is the failure mode.

Every method is a blocking call with a deadline, so pytest-timeout in signal mode can
interrupt a plain call and fixture finalizers still run. Entity names come from
entities.py only.
"""

import asyncio
import threading
import time
from collections import deque

from aioesphomeapi import (
    APIClient,
    APIConnectionError,
    BinarySensorInfo,
    ButtonInfo,
    FanInfo,
    SensorInfo,
    TextSensorInfo,
)

from . import RigError, contract, entities

API_CONNECT_S = 10
RECONNECT_S = 1
COMMAND_S = 5
HISTORY = 32  # state messages kept per entity; waits ask for a handful

_KNOWN = (FanInfo, SensorInfo, BinarySensorInfo, TextSensorInfo, ButtonInfo)


def _value(state):
    """The plain value of a state message; a missing sensor reading is NaN, never 0."""
    if getattr(state, "missing_state", False):
        return float("nan")
    return state.state


class DutLink:
    def __init__(self, host, noise_psk):
        self._host = host
        self._key = noise_psk
        self._cond = threading.Condition()
        self._seq = {}  # name -> state messages received so far (not value changes)
        self._history = {}  # name -> deque of (sequence number, value)
        self._latest = {}  # name -> last value
        self._names = {}  # entity key -> name (current connection)
        self._entities = {}  # name -> (info class, key) (current connection)
        self._client = None
        self._info = None
        self._connected = False
        self._closed = False
        self._task = None
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, name="hil-dutlink-loop", daemon=True)
        self._thread.start()

    # ------------------------------------------------------------ plumbing

    def _run(self, coro, timeout):
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout)
        except TimeoutError:
            future.cancel()
            raise RigError("DUT API call timed out after %ss" % timeout) from None

    def _on_state(self, state):
        name = self._names.get(state.key)
        if name is None:
            return
        value = _value(state)
        with self._cond:
            number = self._seq.get(name, 0) + 1
            self._seq[name] = number
            self._history.setdefault(name, deque(maxlen=HISTORY)).append((number, value))
            self._latest[name] = value
            self._cond.notify_all()

    def _set_connected(self, client, info, infos):
        with self._cond:
            self._client = client
            self._info = info
            self._entities = {e.name: (type(e), e.key) for e in infos if isinstance(e, _KNOWN)}
            self._names = {key: name for name, (_cls, key) in self._entities.items()}
            self._connected = True
            self._cond.notify_all()

    def _set_disconnected(self):
        with self._cond:
            self._connected = False
            self._client = None
            self._entities = {}
            self._names = {}
            self._cond.notify_all()

    async def _session(self):
        """One connection: connect, subscribe, hold until it drops. Always disconnects."""
        client = APIClient(self._host, contract.API_PORT, None, noise_psk=self._key)
        lost = asyncio.Event()

        async def on_stop(_expected):
            lost.set()

        try:
            async with asyncio.timeout(API_CONNECT_S):
                await client.connect(on_stop=on_stop, login=True)
                info = await client.device_info()
                infos, _services = await client.list_entities_services()
            self._set_connected(client, info, infos)
            client.subscribe_states(self._on_state)
            await lost.wait()
        finally:
            self._set_disconnected()
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001 - a dead link must not leak the slot, nor mask its cause
                pass

    async def _maintain(self):
        while not self._closed:
            try:
                await self._session()
            except (APIConnectionError, OSError, TimeoutError):
                pass  # the DUT is rebooting or not up yet; poll again
            if not self._closed:
                await asyncio.sleep(RECONNECT_S)

    async def _start(self):
        self._task = asyncio.get_running_loop().create_task(self._maintain())

    async def _stop(self):
        self._closed = True
        task = self._task
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    # -------------------------------------------------------------- public

    def start(self):
        self._run(self._start(), COMMAND_S)

    def connected(self):
        with self._cond:
            return self._connected

    def wait_connected(self, deadline_s, project_version=None):
        """Block until a session is up and return its DeviceInfo.

        After an OTA the old image can keep its session for a moment, so a caller that wants the
        new image names the `project_version` (build ID) it expects.
        """
        end = time.monotonic() + deadline_s
        with self._cond:
            while True:
                info = self._info
                if self._connected and (project_version is None or info.project_version == project_version):
                    return info
                left = end - time.monotonic()
                if left <= 0:
                    break
                self._cond.wait(left)
            seen = info.project_version if (self._connected and info is not None) else "no session"
        raise RigError("DUT API session not ready within %ss (last: %s)" % (deadline_s, seen))

    def device_info(self):
        """DeviceInfo of the last connect, or None before the first one."""
        with self._cond:
            return self._info

    def count(self, name):
        """State messages received for `name` so far (every publish counts, also an unchanged value)."""
        with self._cond:
            return self._seq.get(name, 0)

    def value(self, name):
        """Last reported value, or None when none arrived yet."""
        with self._cond:
            return self._latest.get(name)

    def wait_fresh(self, name, after, n, deadline_s):
        """Values of the next `n` state messages of `name` numbered above `after`.

        `after` is a count() taken before the command that is being waited for. Raises RigError
        when the link is down at the deadline; returns the shorter list when the link is up but
        the entity stayed silent (a missing reading is never turned into 0).
        """
        end = time.monotonic() + max(0.0, deadline_s)
        with self._cond:
            while True:
                fresh = [v for number, v in self._history.get(name, ()) if number > after]
                if len(fresh) >= n:
                    return fresh[:n]
                left = end - time.monotonic()
                if left <= 0:
                    break
                self._cond.wait(left)
            if not self._connected:
                raise RigError("DUT API link is down; waiting for '%s' ended after %ss" % (name, deadline_s))
            return fresh

    def _command_target(self, name, kind):
        with self._cond:
            found = self._entities.get(name)
            client = self._client
        if client is None:
            raise RigError("DUT API link is down; command to '%s' not sent" % name)
        if found is None or found[0] is not kind:
            raise RigError("entity '%s' missing on the DUT" % name)
        return client, found[1]

    async def _send(self, function, *args, **kwargs):
        function(*args, **kwargs)

    def fan(self, n, on, speed_level=None):
        """Command `Fan n` on or off; `speed_level` 1..100 is the duty in percent (speed_count 100)."""
        client, key = self._command_target(entities.FAN[n], FanInfo)
        try:
            self._run(self._send(client.fan_command, key, state=bool(on), speed_level=speed_level), COMMAND_S)
        except APIConnectionError as exc:
            raise RigError("fan command failed (%s)" % type(exc).__name__) from None

    def press(self, name):
        """Press a button entity of the DUT (e.g. the QC safe mode button)."""
        client, key = self._command_target(name, ButtonInfo)
        try:
            self._run(self._send(client.button_command, key), COMMAND_S)
        except APIConnectionError as exc:
            raise RigError("button press failed (%s)" % type(exc).__name__) from None

    def close(self):
        """Cancel the session task (it disconnects in its finally block) and stop the loop."""
        if self._thread is None:
            return
        try:
            if not self._closed:
                self._run(self._stop(), COMMAND_S + API_CONNECT_S)
        except Exception:  # noqa: BLE001 - closing must never mask the real failure
            pass
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(5)
            self._thread = None
