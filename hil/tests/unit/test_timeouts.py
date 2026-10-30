"""Deadlines nest, and a pytest-timeout in signal mode still runs finalizers."""

import asyncio
import socket
import subprocess
import sys
import textwrap
import time
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from hil import RigError, contract, dut, flasher, serial_tap, supervisor

LABEL = contract.SERIAL_CONNECTED["A"].removesuffix(" Serial Connected")

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def ini():
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["tool"]["pytest"]["ini_options"]


def test_named_deadlines():
    assert supervisor.SUPERVISOR_CONNECT_S == 10
    assert supervisor.PRESS_S == 5
    assert serial_tap.TAP_CONNECT_S == 5
    assert flasher.FLASH_ATTEMPT_S == 120
    assert dut.API_WAIT_S == 90
    assert dut.BOOT_SETTLE_S == 15


def test_per_test_timeout_exceeds_sum_of_operation_deadlines():
    smoke = (
        supervisor.SUPERVISOR_CONNECT_S
        + serial_tap.TAP_CONNECT_S
        + 2 * flasher.FLASH_ATTEMPT_S
        + 2 * supervisor.PRESS_S  # two bootloader presses
        + supervisor.PRESS_S  # reset
        + dut.API_WAIT_S
        + dut.BOOT_SETTLE_S
    )
    assert ini()["timeout"] > smoke


def test_deadlines_nest_operation_then_test_then_session_then_job():
    options = ini()
    assert flasher.FLASH_ATTEMPT_S < options["timeout"] < options["session_timeout"]
    job_timeout_s = 25 * 60  # hil.yml timeout-minutes (01-08)
    assert options["session_timeout"] < job_timeout_s


def test_pytest_timeout_uses_signal_method():
    assert ini()["timeout_method"] == "signal"


def test_timeout_in_signal_mode_still_runs_finalizers(tmp_path):
    marker = tmp_path / "finalized.txt"
    (tmp_path / "conftest.py").write_text(
        textwrap.dedent(
            """
            import pytest

            @pytest.fixture(scope="session", autouse=True)
            def safety(request):
                def finalize():
                    open(%r, "w").write("done")
                request.addfinalizer(finalize)
            """
            % str(marker)
        ),
        encoding="utf-8",
    )
    (tmp_path / "test_hang.py").write_text(
        "import time\nimport pytest\n\n@pytest.mark.timeout(1)\ndef test_hang():\n    time.sleep(30)\n",
        encoding="utf-8",
    )
    (tmp_path / "pytest.ini").write_text("[pytest]\ntimeout_method = signal\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-c", str(tmp_path / "pytest.ini"), "-p", "no:cacheprovider", str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=tmp_path,
    )
    assert proc.returncode != 0
    assert "Timeout" in proc.stdout
    assert marker.read_text(encoding="utf-8") == "done"


def _silent_server():
    """A TCP listener that accepts connections and never sends a byte."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(5)
    return server


def test_silent_serial_bridge_ends_at_its_deadline_with_a_named_error(tmp_path):
    server = _silent_server()
    tap = serial_tap.SerialTap("127.0.0.1", server.getsockname()[1], tmp_path / "raw" / "uart.log")
    tap.start()
    try:
        tap.mark("reset_pressed")
        started = time.monotonic()
        with pytest.raises(RigError, match="no match"):
            tap.wait_for("boot:0x8", "reset_pressed", deadline_s=1)
        assert time.monotonic() - started < 3
    finally:
        tap.stop()
        server.close()


def test_unreachable_serial_bridge_is_a_named_rig_error(tmp_path):
    server = _silent_server()
    port = server.getsockname()[1]
    server.close()
    with pytest.raises(RigError, match="serial bridge %d unreachable" % port):
        serial_tap.SerialTap("127.0.0.1", port, tmp_path / "uart.log").start()


class _InlineSupervisor:
    """Runs the DUT's coroutine directly, as Supervisor.run would on its loop."""

    def run(self, coro, timeout):
        return asyncio.run(asyncio.wait_for(coro, timeout))


def test_silent_dut_api_ends_the_wait_at_its_deadline_with_a_named_error(monkeypatch):
    server = _silent_server()
    monkeypatch.setattr(dut, "API_CONNECT_S", 0.5)
    cfg = SimpleNamespace(host="127.0.0.1")
    monkeypatch.setattr(dut.contract, "API_PORT", server.getsockname()[1])
    device = dut.Dut("A", cfg, _InlineSupervisor(), flasher=None)
    started = time.monotonic()
    try:
        with pytest.raises(RigError, match="%s API did not answer within 2s" % LABEL):
            device.wait_api(noise_psk=None, deadline_s=2)
        assert time.monotonic() - started < 6
    finally:
        server.close()
