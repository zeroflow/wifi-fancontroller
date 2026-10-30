"""Deadlines nest, and a pytest-timeout in signal mode still runs finalizers."""

import subprocess
import sys
import textwrap
import tomllib
from pathlib import Path

from hil import dut, flasher, serial_tap, supervisor

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
