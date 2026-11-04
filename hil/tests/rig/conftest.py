"""Session fixtures. `supervisor` is the safety fixture: autouse, so every rig
session switches every contract line off before the first test and again in its
finalizer, also when a test is killed by its timeout.

Log boundaries (HARN-08): `tap_a` and `dut_link` are autouse session fixtures that register
themselves in LOG_SINKS. The autouse `log_boundaries` fixture writes `START <nodeid> t=<s>` to every
sink before a test and `END <nodeid> <outcome> t=<s>` after it, and the capability skip hook writes
`SKIP <nodeid>: <reason>`; `dut_state` depends on `log_boundaries`, so the order is START,
before-check, test, after-check, END.
"""

import json
import time
from pathlib import Path

import pytest
from aioesphomeapi import APIConnectionError

from hil import RigError, caps, config, contract, manifest
from hil.dut import API_WAIT_S, Dut, state_roles
from hil.dutlink import DutLink
from hil.flasher import Flasher
from hil.serial_tap import SerialTap
from hil.supervisor import Supervisor


_RIG = []
RIG_DIR = Path(__file__).resolve().parent
T0 = time.monotonic()  # session start: the `t=` of every boundary line counts from here
LOG_SINKS = []  # objects with boundary(text): the UART0 tap and the API log of DUT A
_PENDING = []  # boundary lines written before the first sink existed (a skip of the first test)


def add_log_sink(sink):
    """Register a log sink; it first receives the lines that were written before any sink existed."""
    LOG_SINKS.append(sink)
    for text in _PENDING:
        sink.boundary(text)


def remove_log_sink(sink):
    if sink in LOG_SINKS:
        LOG_SINKS.remove(sink)


def log_boundary(text):
    """One `[HIL] ===== text =====` line in every registered log (HARN-08)."""
    if not LOG_SINKS:
        _PENDING.append(text)
        return
    for sink in list(LOG_SINKS):
        sink.boundary(text)


def _elapsed():
    return time.monotonic() - T0


def _rig():
    """rig.toml, loaded once and only when a test asks for a capability (the setup hook runs before any fixture)."""
    if not _RIG:
        _RIG.append(config.load())
    return _RIG[0]


def pytest_collection_modifyitems(config, items):
    """An unknown capability name or an unmarked, unexempted rig test fails collection.

    A typo can never skip a test forever (HARN-02, T-02-37), and a new rig test cannot start or
    end in an unconfirmed state by omission (HARN-03): it needs an `image` marker or an entry in
    dut.STATE_EXEMPT. No manifest and no rig.toml is read here: the hosted collect-only job runs
    this hook too.
    """
    for item in items:
        if Path(str(item.path)).is_relative_to(RIG_DIR):
            try:
                state_roles(item.get_closest_marker("image"), item.path.name)
            except RigError as exc:
                raise pytest.UsageError("%s: %s" % (item.nodeid, exc)) from None
        for marker in item.iter_markers("requires"):
            if marker.kwargs or not marker.args:
                raise pytest.UsageError("%s: requires() takes capability names as positional arguments" % item.nodeid)
            bad = caps.unknown(marker.args)
            if bad:
                raise pytest.UsageError(
                    "%s: requires() has an unknown capability name: %s" % (item.nodeid, ", ".join(repr(b) for b in bad))
                )


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    """Skip with a reason, before any fixture of the test is built, when DUT A lacks a capability."""
    for marker in item.iter_markers("requires"):
        absent = caps.missing(_rig().duts["A"], marker.args)
        if absent:
            reason = caps.skip_reason("A", absent)
            log_boundary("SKIP %s: %s" % (item.nodeid, reason))
            pytest.skip(reason)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    """Keep each phase's report on the item, so the END boundary can name the outcome."""
    report = yield
    reports = item.__dict__.setdefault("_hil_reports", {})
    reports[report.when] = report
    return report


def _outcome(item):
    """passed, failed, skipped (the call phase) or error (setup failed) of a test, for its END line."""
    reports = item.__dict__.get("_hil_reports", {})
    if "call" in reports:
        return reports["call"].outcome
    setup = reports.get("setup")
    if setup is not None and setup.outcome == "failed":
        return "error"
    return setup.outcome if setup is not None else "unknown"


@pytest.fixture(scope="session")
def rig_config():
    return config.load()


@pytest.fixture(scope="session")
def fw_manifest(rig_config):
    return manifest.load_verified(config.firmware_dir(), config.expected_commit(), rig_config.duts["A"])


@pytest.fixture(scope="session", autouse=True)
def supervisor(request, rig_config):
    sv = Supervisor(rig_config.supervisor_host, rig_config.supervisor_key)

    def teardown():
        try:
            sv.release_all()
        finally:
            sv.close()

    request.addfinalizer(teardown)
    sv.connect()
    sv.release_all()
    if sv.serial_connected("A"):
        raise RigError("rig busy: DUT A serial bridge already held by another client")
    return sv


@pytest.fixture(scope="session", autouse=True)
def tap_a(request, rig_config, supervisor):
    """Always-on UART0 tap, autouse so the log covers the whole run from the first test on.
    Depends on `supervisor` so it starts after the bridge-busy check and before any press;
    with esptool it is the two-client maximum."""
    tap = SerialTap(
        rig_config.supervisor_host,
        contract.BRIDGE_PORT["A"],
        config.reports_dir() / "raw" / "uart-dut-a.log",
    )
    request.addfinalizer(tap.stop)
    tap.start()
    add_log_sink(tap)
    request.addfinalizer(lambda: remove_log_sink(tap))  # runs before tap.stop
    return tap


@pytest.fixture(scope="session")
def dut_a(request, rig_config, supervisor, tap_a):
    cfg = rig_config.duts["A"]
    flasher = Flasher(rig_config.supervisor_host, contract.BRIDGE_PORT["A"], cfg.chip)
    dut = Dut("A", cfg, supervisor, flasher, tap=tap_a)

    def write_budget():
        """Every boot the harness caused or saw, and what is left of the reset budget (HARN-12)."""
        reports = config.reports_dir()
        reports.mkdir(parents=True, exist_ok=True)
        text = json.dumps(dut.budget.report(), indent=2, sort_keys=True) + "\n"
        (reports / "budget-dut-a.json").write_text(text, encoding="utf-8")

    request.addfinalizer(write_budget)
    return dut


@pytest.fixture(scope="session", autouse=True)
def dut_link(request, rig_config, dut_a, tap_a):
    """The one persistent API session to DUT A for the whole run (QC reads and fan commands).

    Autouse, so the API log covers the whole run. It does not block on the first connect: the link
    polls in the background and reconnects after every reboot and OTA, and tests that need a session
    call `wait_connected`. It is closed in the finalizer, so no API slot outlives the run. Depends
    on `dut_a` so it starts after the serial tap.
    """
    link = DutLink(
        rig_config.duts["A"].host,
        rig_config.dut_api_key,
        log_path=config.reports_dir() / "raw" / "api-dut-a.log",
        tap=tap_a,
        chip=rig_config.duts["A"].chip,
    )
    request.addfinalizer(link.close)
    link.start()
    add_log_sink(link)
    request.addfinalizer(lambda: remove_log_sink(link))  # runs before link.close
    return link


_TEST_STARTS = [0]  # counter of the UART0 marks taken at each test's start


@pytest.fixture(autouse=True)
def crash_mark(tap_a, dut_link, log_boundaries):
    """D-46, WR-01: a UART0 mark at the test's start; a ROM boot banner after it means the DUT rebooted during the test.

    The DutLink reads it when a wait ends with its API session down: a banner since this mark is a
    FirmwareFailure (FAIL), no banner stays a RigError. Cleared after the test, so a wait in a
    session finalizer is never judged against a finished test. `dut_state` depends on this fixture,
    so the mark exists before the before-check and outlives the after-check.
    """
    _TEST_STARTS[0] += 1
    name = "test_start_%d" % _TEST_STARTS[0]
    tap_a.mark(name)
    dut_link.crash_mark = name
    yield name
    dut_link.crash_mark = None


@pytest.fixture(autouse=True)
def log_boundaries(request):
    """HARN-08: START and END lines around every executed test, in the UART0 log and the API log.

    Both lines carry the node id and the seconds since session start. The outcome in the END line
    is the test's own (call phase); a failure of a later teardown shows in JUnit, not here.
    """
    node = request.node
    log_boundary("START %s t=%.1f" % (node.nodeid, _elapsed()))
    yield
    log_boundary("END %s %s t=%.1f" % (node.nodeid, _outcome(node), _elapsed()))


def _answering_build_id(dut_a, noise_psk, problem):
    """The build ID DUT A reports on the API. No answer is a failed state check, unless the ports say safe mode."""
    try:
        return dut_a.probe(noise_psk).project_version
    except (RigError, APIConnectionError, OSError, TimeoutError) as exc:
        dut_a.check_safe_mode_ports()  # SafeModeError: a RigError, never a firmware FAIL (HARN-12)
        pytest.fail("%s: DUT %s does not answer on the API (%s)" % (problem, dut_a.id, type(exc).__name__))


def _clean_problems(dut_a, dut_link, build_id):
    """CLEAN on the running image: the DutLink session is the image's own, then the settle signals."""
    dut_link.wait_connected(API_WAIT_S, project_version=build_id)
    return dut_a.settle(dut_link)


@pytest.fixture(autouse=True)
def dut_state(request, log_boundaries, crash_mark):
    """HARN-03: a test with an `image` marker starts and ends with DUT A in a confirmed state.

    Before: DUT A answers with the build ID of the marker's before-role and is CLEAN. After: the
    same for the after-role; if the settle finds problems, one budgeted EN reset and a second
    settle, then a failure. Every state is confirmed by a signal (API build ID, fresh tach readings
    of 0, button and switch states), never by a sleep. Nothing is reflashed inside a test.
    Only the exempt test_00_contract (dut.STATE_EXEMPT) has no marker and gets no check.
    """
    node = request.node
    marker = node.get_closest_marker("image")
    if state_roles(marker, node.path.name) is None:
        yield
        return
    rig = request.getfixturevalue("rig_config")
    fw = request.getfixturevalue("fw_manifest")
    cfg = rig.duts["A"]
    before, after = state_roles(marker, node.path.name, {role for (role, rev) in fw.images if rev == cfg.rev})
    dut_a = request.getfixturevalue("dut_a")
    link = request.getfixturevalue("dut_link")
    label = "DUT %s" % dut_a.id

    if before is not None:
        want = fw.image(before, cfg.rev)
        seen = _answering_build_id(dut_a, rig.dut_api_key, "precondition")
        if seen != want.build_id:
            pytest.fail("precondition: %s runs %s, expected %s (%s)" % (label, seen, before, want.build_id))
        problems = _clean_problems(dut_a, link, want.build_id)
        if problems:
            pytest.fail("precondition: %s is not clean (%s): %s" % (label, before, "; ".join(problems)))

    yield

    if after is not None:
        want = fw.image(after, cfg.rev)
        seen = _answering_build_id(dut_a, rig.dut_api_key, "%s did not return to a clean %s state" % (label, after))
        if seen != want.build_id:
            pytest.fail("%s did not return to a clean %s state: runs %s, expected %s" % (label, after, seen, want.build_id))
        problems = _clean_problems(dut_a, link, want.build_id)
        if problems:
            mark = dut_a.reset()  # the one EN reset a test may spend; budgeted, and never inside the rollback window
            dut_a.wait_running(rig.dut_api_key, mark)
            problems = _clean_problems(dut_a, link, want.build_id)
        if problems:
            pytest.fail("%s did not return to a clean %s state: %s" % (label, after, "; ".join(problems)))
