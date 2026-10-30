"""Session fixtures. `supervisor` is the safety fixture: autouse, so every rig
session switches every contract line off before the first test and again in its
finalizer, also when a test is killed by its timeout."""

import pytest

from hil import RigError, config, contract, manifest
from hil.dut import Dut
from hil.flasher import Flasher
from hil.serial_tap import SerialTap
from hil.supervisor import Supervisor


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
