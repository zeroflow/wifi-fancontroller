"""Preflight: the rig checks itself before any test and fixes what it can (HARN-05, D-43).

Order (D-43): supervisor reachable, contract conformant, every line released, each bridge's
Serial Clients 0, watchdog counters recorded, DUT A booting after an EN reset (ROM `boot:0x8`
on UART0, then an API answer with the HIL key or without encryption). The first check that
stays broken is the cause and nothing after it runs; every fix made on the way (a line found
ON and released, a stray bridge client evicted, DUT A healed) is a warning, never absorbed
silently.

Heal (HARN-10, D-44): a DUT A that fails the boot check is healed exactly once from the
runner-local known-good chain (known_good.select, shared with teardown: last-green when the
store verifies, else v1.6.0 plus NVS replay; never a download, never a broken, qc-auto or
canary image), with region writes only, and checked again. A heal that cannot start is
"heal impossible", one that does not bring DUT A back is "heal failed"; both are the cause.
Preflight is a rig check: a FirmwareFailure or SafeModeError on the way is a failed heal step,
never a FAIL verdict. The heal leaves DUT A on the known-good image; the run starts with its own
baseline flash, so a heal never changes what the run tests.

run_preflight never raises for a rig condition: it returns (ok, cause, record). The UART tap
and the supervisor connection are closed on every path, so the run starts with both bridge
slots free. Messages name checks and entity names, never values of keys or credentials.
"""

import json
import re
import time
from pathlib import Path

from . import FirmwareFailure, RigError, bootlog, config, contract, known_good
from .dut import API_WAIT_S
from .supervisor import Supervisor

EVICT_WAIT_S = 40  # D-48 keepalive evicts a vanished client in about 25 s
BOOT_BANNER_S = 5  # EN reset -> the ROM normal-boot banner on UART0
POLL_S = 0.5  # Serial Clients poll while a stray client is being evicted
API_POLL_S = 1
REPORT = "preflight.json"
HEAL_FLASH_REPORT = "heal-flash-dut-a.json"
TAP_LOG = Path("raw") / "uart-preflight-dut-a.log"
DUT_B_BOOT = "not checked (DUT B joins the suite in Phase 4)"


class Stop(Exception):
    """A check stayed broken: the message is the preflight cause."""


class BootFailed(Exception):
    """DUT A did not pass the boot check; the message says which step."""


def _label(dut_id):
    return "DUT %s" % dut_id


def _first(exc):
    text = str(exc).strip()
    return text.splitlines()[0] if text else type(exc).__name__


def _class_in(exc):
    """The exception class a Supervisor RigError names in its trailing parentheses, else the class of exc."""
    found = re.search(r"\(([A-Za-z_][A-Za-z0-9_]*)\)\s*$", str(exc))
    return found.group(1) if found else type(exc).__name__


class Preflight:
    def __init__(self, rig, reports_dir, supervisor, make_tap, make_dut, clock, sleep):
        self.rig = rig
        self.reports = Path(reports_dir)
        self.supervisor = supervisor
        self.make_tap = make_tap
        self.make_dut = make_dut
        self.clock = clock
        self.sleep = sleep
        self.tap = None
        self.record = {
            "schema": 1,
            "commit": config.expected_commit() or None,
            "checks": [],
            "warnings": [],
            "heal": None,
            "watchdog_start": {},
        }

    # ------------------------------------------------------------ bookkeeping

    def check(self, name, ok, detail=""):
        self.record["checks"].append({"name": name, "ok": bool(ok), "detail": detail})

    def warn(self, text):
        self.record["warnings"].append(text)

    def fail(self, name, cause):
        self.check(name, False, cause)
        raise Stop(cause)

    # ------------------------------------------------------------------ checks

    def supervisor_reachable(self):
        name = "supervisor reachable"
        try:
            self.supervisor.connect()
        except Exception as exc:  # noqa: BLE001 - any connect fault is the same rig condition
            self.fail(name, "supervisor unreachable (%s)" % _class_in(exc))
        self.check(name, True)

    def contract_conformant(self):
        name = "contract"
        problems = Supervisor.contract_problems(self.supervisor.entity_name_list())
        if problems:
            self.fail(name, "contract mismatch: %s" % problems[0])
        self.check(name, True, "%d names" % len(contract.REQUIRED_ENTITIES))

    def lines_released(self):
        name = "lines released"
        lines = [n for d in "AB" for n in contract.SWITCH[d].values()]
        found_on = [n for n in lines if self.supervisor.switch_is_on(n) is True]
        try:
            self.supervisor.release_all()
        except RigError as exc:
            listed = re.sub(r"^switch (.*) not released$", r"\1", str(exc))
            self.fail(name, "line not released: %s" % listed)
        for line in found_on:
            self.warn("line %s was on at preflight start; released" % line)
        self.check(name, True, "%d lines off" % len(lines))

    def bridge_free(self, dut_id):
        name = "%s bridge clients" % _label(dut_id)
        sensor = contract.SERIAL_CLIENTS[dut_id]
        missing = "%s has no value" % sensor
        value = self.supervisor.sensor_value(sensor)
        if value is None:
            self.fail(name, missing)
        if value == 0:
            self.check(name, True, "0")
            return
        start = self.clock()
        while True:
            waited = self.clock() - start
            if waited >= EVICT_WAIT_S:
                self.fail(name, "%s bridge client not evicted within %d s" % (_label(dut_id), EVICT_WAIT_S))
            self.sleep(POLL_S)
            value = self.supervisor.sensor_value(sensor)
            if value is None:
                self.fail(name, missing)
            if value == 0:
                waited = self.clock() - start
                self.warn("stray bridge client on %s evicted after %d s" % (_label(dut_id), round(waited)))
                self.check(name, True, "0 after %d s" % round(waited))
                return

    def watchdog_recorded(self):
        name = "watchdog counters"
        values = {}
        for dut_id in "AB":
            sensor = contract.WATCHDOG_RELEASES[dut_id]
            value = self.supervisor.sensor_value(sensor)
            if value is None:
                self.fail(name, "%s has no value" % sensor)
            values[dut_id] = int(value)
        self.record["watchdog_start"] = values
        self.check(name, True, ", ".join("%s %d" % (_label(d), v) for d, v in values.items()))

    def start_tap(self):
        name = "%s UART tap" % _label("A")
        path = self.reports / TAP_LOG
        path.parent.mkdir(parents=True, exist_ok=True)
        tap = self.make_tap(contract.BRIDGE_PORT["A"], path)
        try:
            tap.start()
        except RigError as exc:
            tap.stop()
            self.fail(name, "%s UART tap did not start (%s)" % (_label("A"), exc))
        self.tap = tap
        return tap

    def boot_once(self, dut):
        """EN reset, the ROM normal-boot banner within BOOT_BANNER_S, then an API answer. Returns a detail line."""
        chip = self.rig.duts["A"].chip
        try:
            mark = dut.reset()
        except RigError as exc:
            raise BootFailed("EN reset refused (%s)" % exc) from None
        end = self.clock() + BOOT_BANNER_S
        while not bootlog.has_boot_banner(self.tap.text(mark), chip):
            if self.tap.closed:
                raise BootFailed("UART tap lost the bridge after the EN reset")
            if self.clock() >= end:
                raise BootFailed("no %s within %d s after the EN reset" % (bootlog.NORMAL_BOOT[chip], BOOT_BANNER_S))
            self.sleep(0.1)
        end = self.clock() + API_WAIT_S
        while True:
            found = bootlog.safe_mode_lines(self.tap.text(mark))
            if found:
                raise BootFailed("booted into safe mode (%s)" % found[0].strip())
            for psk, mode in ((self.rig.dut_api_key, "HIL key"), (None, "no encryption")):
                try:
                    info = dut.probe(psk)
                except Exception:  # noqa: BLE001 - wrong mode, or not up yet
                    continue
                return "%s seen, API answered (%s), %s" % (bootlog.NORMAL_BOOT[chip], mode, info.project_version)
            if self.clock() >= end:
                raise BootFailed(
                    "%s seen but the API did not answer within %d s with the HIL key or without encryption"
                    % (bootlog.NORMAL_BOOT[chip], API_WAIT_S)
                )
            self.sleep(API_POLL_S)

    def dut_a_boots(self):
        name = "%s boot" % _label("A")
        tap = self.start_tap()
        dut = self.make_dut(tap)
        try:
            detail = self.boot_once(dut)
        except BootFailed as exc:
            detail = self.heal(dut, name, "%s boot check failed: %s" % (_label("A"), exc))
        self.check(name, True, detail)

    def heal(self, dut, name, first_failure):
        """D-44: exactly one heal from the known-good chain, then the boot check once more. Returns its detail."""
        heal = {"source": None, "ok": False, "detail": "", "first_failure": first_failure}
        self.record["heal"] = heal
        started = self.clock()
        try:
            chosen = known_good.select(self.rig, self.rig.dut_api_key)
        except RigError as exc:
            heal["detail"] = "heal impossible: %s" % _first(exc)
            self.fail(name, heal["detail"])
        heal["source"] = chosen.source
        try:
            dut.flash_regions(chosen.regions, report_name=HEAL_FLASH_REPORT)
            info = dut.wait_api(chosen.psk)
            if chosen.expected_build_id is not None and info.project_version != chosen.expected_build_id:
                raise BootFailed(
                    "%s reports %s, not the last-green %s"
                    % (_label("A"), info.project_version, chosen.expected_build_id)
                )
            detail = self.boot_once(dut)
        except (BootFailed, RigError, FirmwareFailure) as exc:  # SafeModeError is a RigError
            heal["detail"] = "heal failed: %s" % _first(exc)
            heal["duration_s"] = round(self.clock() - started, 1)
            self.fail(name, heal["detail"])
        heal.update(
            ok=True,
            version=info.project_version,
            duration_s=round(self.clock() - started, 1),
            detail="%s (%s) written and confirmed" % (chosen.source, info.project_version),
        )
        self.warn("%s healed with %s (%s)" % (_label("A"), chosen.source, info.project_version))
        return "%s, after a heal with %s" % (detail, chosen.source)

    def run(self):
        self.supervisor_reachable()
        self.contract_conformant()
        self.lines_released()
        for dut_id in "AB":
            self.bridge_free(dut_id)
        self.watchdog_recorded()
        self.dut_a_boots()
        self.check("%s boot" % _label("B"), False, DUT_B_BOOT)

    def close(self):
        if self.tap is not None:
            try:
                self.tap.stop()
            except Exception:  # noqa: BLE001 - closing must never hide the cause
                pass
        try:
            self.supervisor.close()
        except Exception:  # noqa: BLE001
            pass

    def write(self):
        self.reports.mkdir(parents=True, exist_ok=True)
        text = json.dumps(self.record, indent=2, sort_keys=True) + "\n"
        (self.reports / REPORT).write_text(text, encoding="utf-8")


def run_preflight(rig, reports_dir, *, supervisor, make_tap, make_dut, clock=time.monotonic, sleep=time.sleep):
    """(ok, cause, record). Never raises (an unexpected exception is a cause naming its class); writes reports/preflight.json on every path."""
    pre = Preflight(rig, reports_dir, supervisor, make_tap, make_dut, clock, sleep)
    cause = None
    try:
        pre.run()
    except Stop as stop:
        cause = str(stop)
    except RigError as exc:
        # A rig fault outside the named steps (a sensor entity gone between list and read).
        cause = "preflight stopped: %s" % exc
        pre.check("preflight", False, cause)
    except Exception as exc:  # noqa: BLE001 - IN-06: an unexpected fault is a failed check naming its class, never a raise
        cause = "preflight stopped unexpectedly (%s)" % type(exc).__name__
        pre.check("preflight", False, cause)
    finally:
        pre.close()
        pre.write()
    return cause is None, cause, pre.record
