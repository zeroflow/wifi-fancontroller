"""One persistent API session to a DUT: states, per-entity message counts, commands.

A daemon thread owns an asyncio loop (same structure as Supervisor). The maintenance
task connects, subscribes to every state and, when the link drops (reboot, OTA),
waits one second and connects again with a fresh client: a poll with a deadline, no
ReconnectLogic (it is mDNS-driven and mDNS does not cross the VLAN). The client is
always disconnected in a finally block: a leaked API slot is the failure mode.

Every method is a blocking call with a deadline, so pytest-timeout in signal mode can
interrupt a plain call and fixture finalizers still run. Entity names come from
entities.py only.

With a `log_path` the link also records the DUT's runtime log (HARN-08): every session
subscribes to the device log at DEBUG level and each message is appended as
"<seconds since start()> <message>" (ANSI codes stripped). boundary() writes the test
boundary lines into the same file under the same lock. The file exists from start() on,
also when no connection is ever made.

With a `tap` (the UART0 capture) and a `chip`, a wait that ends with the link down tells a crash from
a rig fault (D-46, WR-01): when the owner has set `crash_mark` (a tap mark taken at the test's start)
and UART0 shows a ROM normal-boot banner since it, the DUT rebooted during the test and the wait
raises FirmwareFailure; without a banner the link is down for a rig reason and it stays a RigError.

The key follows the image (HARN-08 for release images): use_key(None) while DUT A runs the release
baseline, which answers without encryption, and use_key(<HIL key>) for the commit-derived images. A
changed key ends the current session, so the next one connects with the new key and the release's
runtime log reaches the API log too.
"""

import asyncio
import threading
import time
from collections import deque

from pathlib import Path

from aioesphomeapi import (
    APIClient,
    APIConnectionError,
    BinarySensorInfo,
    ButtonInfo,
    FanInfo,
    LogLevel,
    SensorInfo,
    TextSensorInfo,
)

from . import FirmwareFailure, RigError, bootlog, contract, entities
from .redact import ANSI

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
    def __init__(self, host, noise_psk, log_path=None, tap=None, chip=None):
        self._host = host
        self._key = noise_psk
        self._tap = tap
        self._chip = chip
        self.crash_mark = None  # tap mark of the current test's start; set by the rig fixtures
        self._log_path = None if log_path is None else Path(log_path)
        self._log = None
        self._log_lock = threading.Lock()
        self._t0 = time.monotonic()
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
        self._lost = None  # the current session's "connection lost" event (set on the link's loop only)
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

    # ----------------------------------------------------------- API log

    def _open_log(self):
        """Create (truncate) the API log file; no-op without a log_path."""
        if self._log_path is None:
            return
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        with self._log_lock:
            if self._log is None:
                self._log = self._log_path.open("w", encoding="utf-8", newline="\n")

    def _close_log(self):
        with self._log_lock:
            log, self._log = self._log, None
        if log is not None:
            log.close()

    def _write_log(self, text):
        """One line, stamped with the seconds since start(); a closed or absent log ignores it."""
        with self._log_lock:
            if self._log is None:
                return
            self._log.write("%.3f %s\n" % (time.monotonic() - self._t0, text))
            self._log.flush()

    def _on_log(self, response):
        """subscribe_logs callback: one stamped, ANSI-stripped line per message."""
        message = response.message
        text = message.decode("utf-8", "replace") if isinstance(message, (bytes, bytearray)) else str(message)
        self._write_log(ANSI.sub("", text).rstrip("\r\n").replace("\r", " ").replace("\n", " "))

    def boundary(self, text):
        """Write a `[HIL] ===== text =====` test boundary line into the API log (HARN-08)."""
        self._write_log("[HIL] ===== %s =====" % str(text).replace("\n", " "))

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
            self._latest = {}  # WR-05: a value of the ended session must not satisfy a later wait; the _seq counters stay
            self._entities = {}
            self._names = {}
            self._cond.notify_all()

    async def _session(self):
        """One connection: connect, subscribe, hold until it drops. Always disconnects."""
        client = APIClient(self._host, contract.API_PORT, None, noise_psk=self._key)
        lost = asyncio.Event()
        self._lost = lost
        unsubscribe = None

        async def on_stop(_expected):
            lost.set()

        try:
            async with asyncio.timeout(API_CONNECT_S):
                await client.connect(on_stop=on_stop, login=True)
                info = await client.device_info()
                infos, _services = await client.list_entities_services()
            self._set_connected(client, info, infos)
            client.subscribe_states(self._on_state)
            unsubscribe = client.subscribe_logs(self._on_log, log_level=LogLevel.LOG_LEVEL_DEBUG)
            await lost.wait()
        finally:
            if self._lost is lost:
                self._lost = None
            self._set_disconnected()
            if unsubscribe is not None:
                try:
                    unsubscribe()
                except Exception:  # noqa: BLE001 - the callback only stops; a dead link must not mask its cause
                    pass
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
            except Exception as exc:  # noqa: BLE001 - WR-06: keep polling; name the class only, never the message
                self._write_log("[HIL] link task error: %s" % type(exc).__name__)
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

    def _crashed(self):
        """True when UART0 shows a ROM normal-boot banner since crash_mark (the DUT rebooted during the test)."""
        mark = self.crash_mark
        if self._tap is None or self._chip is None or mark is None:
            return False
        try:
            return bootlog.has_boot_banner(self._tap.text(mark), self._chip)
        except (KeyError, OSError, RigError):
            return False  # no such mark or an unreadable tap: no evidence of a crash

    def _link_down_error(self, message):
        """FirmwareFailure when the DUT rebooted during the test, else a RigError, for a wait that ended with the link down."""
        if self._crashed():
            return FirmwareFailure(
                "DUT A rebooted during the test (ROM boot banner since its START) and the API session did not come back: %s"
                % message
            )
        return RigError(message)

    # -------------------------------------------------------------- public

    def start(self):
        self._t0 = time.monotonic()
        self._open_log()
        self._run(self._start(), COMMAND_S)

    def connected(self):
        with self._cond:
            return self._connected

    async def _switch_key(self, noise_psk):
        """On the link's loop: store the key, end the current session; _maintain reconnects with the new key."""
        if noise_psk == self._key:
            return False
        self._key = noise_psk
        if self._lost is not None:
            self._lost.set()
        return True

    def use_key(self, noise_psk):
        """Connect with `noise_psk` from the next session on (None: no encryption, for the release baseline).

        A different key ends the current session at once; the same key changes nothing. Returns True when
        the key changed. HARN-08 for release images: the release's runtime log reaches the API log.
        """
        if self._thread is None or self._closed:
            changed = noise_psk != self._key
            self._key = noise_psk
            return changed
        return self._run(self._switch_key(noise_psk), COMMAND_S)

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
            down = not self._connected
            seen = info.project_version if (self._connected and info is not None) else "no session"
        message = "DUT API session not ready within %ss (last: %s)" % (deadline_s, seen)
        raise (self._link_down_error(message) if down else RigError(message))

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
        (FirmwareFailure when the DUT rebooted during the test, see the module docstring) when the
        link is down at the deadline; returns the shorter list when the link is up but
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
            down = not self._connected
            if not down:
                return fresh
        raise self._link_down_error("DUT API link is down; waiting for '%s' ended after %ss" % (name, deadline_s))

    def wait_value(self, name, predicate, deadline_s):
        """The current value of `name` as soon as `predicate(value)` holds, else None at the deadline.

        Judges the last reported value, so an older value that once matched cannot satisfy it, and
        wakes on each state message (no sleeping poll). A missing reading (NaN) is never offered to
        the predicate: NaN is truthy and must not count as a value. Raises RigError (FirmwareFailure
        when the DUT rebooted during the test) when the link is down at the deadline; returns None when it is up but the predicate never held.
        """
        end = time.monotonic() + max(0.0, deadline_s)
        with self._cond:
            while True:
                value = self._latest.get(name)
                if value is not None and value == value and predicate(value):
                    return value
                left = end - time.monotonic()
                if left <= 0:
                    break
                self._cond.wait(left)
            down = not self._connected
            if not down:
                return None
        raise self._link_down_error("DUT API link is down; waiting for '%s' ended after %ss" % (name, deadline_s))

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
            self._close_log()
