"""Synchronous facade over the supervisor's encrypted native API.

One daemon thread owns an asyncio loop; every public method is a blocking call
with a timeout, so pytest-timeout (signal mode) can interrupt a plain call and
fixture finalizers still run. Supervisor names come from contract.py only.
"""

import asyncio
import threading
import time

from aioesphomeapi import (
    APIClient,
    APIConnectionError,
    BinarySensorInfo,
    BinarySensorState,
    ButtonInfo,
    SwitchInfo,
    SwitchState,
)

from . import RigError, contract

SUPERVISOR_CONNECT_S = 10
PRESS_S = 5
STATE_WAIT = 5


class Supervisor:
    def __init__(self, host, key):
        self._host = host
        self._key = key
        self._client = None
        self._entities = {}  # name -> (info class, key)
        self._name_list = []  # every entity name as reported, in order, duplicates kept
        self._names = {}  # key -> name
        self._states = {}  # name -> bool
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
        if name is not None and isinstance(state, (SwitchState, BinarySensorState)):
            self._states[name] = bool(state.state)

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
            if isinstance(entity, (ButtonInfo, SwitchInfo, BinarySensorInfo)):
                self._entities[entity.name] = (type(entity), entity.key)
                self._names[entity.key] = entity.name
        self._client = client
        client.subscribe_states(self._on_state)
        wanted = [n for n in self._entities if n in contract.REQUIRED_ENTITIES and self._entities[n][0] is not ButtonInfo]
        deadline = time.monotonic() + STATE_WAIT
        while time.monotonic() < deadline and any(n not in self._states for n in wanted):
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
        self.run(self._command(self._client.button_command, key), PRESS_S)

    def set_switch(self, name, on):
        key = self._lookup(name, SwitchInfo)
        self.run(self._command(self._client.switch_command, key, bool(on)), PRESS_S)

    def release_all(self):
        """Every contract switch OFF, then every one reported OFF within 5 s."""
        names = [n for lines in contract.SWITCH.values() for n in lines.values()]
        for name in names:
            self.set_switch(name, False)
        deadline = time.monotonic() + STATE_WAIT
        while True:
            pending = [n for n in names if self._states.get(n) is not False]
            if not pending:
                return
            if time.monotonic() >= deadline:
                raise RigError("switch '%s' did not report OFF within %ss" % (pending[0], STATE_WAIT))
            time.sleep(0.1)

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
