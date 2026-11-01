"""Session fixtures. `supervisor` is the safety fixture: autouse, so every rig
session switches every contract line off before the first test and again in its
finalizer, also when a test is killed by its timeout."""

import pytest

from hil import RigError, caps, config, contract, manifest
from hil.dut import API_WAIT_S, Dut
from hil.dutlink import DutLink
from hil.flasher import Flasher
from hil.serial_tap import SerialTap
from hil.supervisor import Supervisor


_RIG = []


def _rig():
    """rig.toml, loaded once and only when a test asks for a capability (the setup hook runs before any fixture)."""
    if not _RIG:
        _RIG.append(config.load())
    return _RIG[0]


def pytest_collection_modifyitems(config, items):
    """An unknown capability name fails collection, so a typo can never skip a test forever.

    No rig.toml is read here: the hosted collect-only job runs this hook too (HARN-02, T-02-37).
    """
    for item in items:
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
            pytest.skip(caps.skip_reason("A", absent))


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


@pytest.fixture(scope="session")
def tap_a(request, rig_config, supervisor):
    """Always-on UART0 tap. Depends on `supervisor` so it starts after the bridge-busy
    check and before any press; with esptool it is the two-client maximum."""
    tap = SerialTap(
        rig_config.supervisor_host,
        contract.BRIDGE_PORT["A"],
        config.reports_dir() / "raw" / "uart-dut-a.log",
    )
    request.addfinalizer(tap.stop)
    tap.start()
    return tap


@pytest.fixture(scope="session")
def dut_a(rig_config, supervisor, tap_a):
    cfg = rig_config.duts["A"]
    flasher = Flasher(rig_config.supervisor_host, contract.BRIDGE_PORT["A"], cfg.chip)
    return Dut("A", cfg, supervisor, flasher, tap=tap_a)


@pytest.fixture(scope="session")
def dut_link(request, rig_config, dut_a):
    """The one persistent API session to DUT A for the whole run (QC reads and fan commands).

    It reconnects by polling after every reboot and OTA and is closed in the finalizer, so
    no API slot outlives the run. Depends on `dut_a` so it starts after the serial tap.
    """
    link = DutLink(rig_config.duts["A"].host, rig_config.dut_api_key)
    request.addfinalizer(link.close)
    link.start()
    link.wait_connected(API_WAIT_S)
    return link
