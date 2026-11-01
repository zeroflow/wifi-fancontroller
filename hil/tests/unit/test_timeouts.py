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
import yaml

from hil import RigError, contract, dut, dutlink, flasher, ota, qc, serial_tap, supervisor, teardown

LABEL = contract.SERIAL_CONNECTED["A"].removesuffix(" Serial Connected")

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"
WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "hil.yml"


def ini():
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["tool"]["pytest"]["ini_options"]


def test_named_deadlines():
    assert supervisor.SUPERVISOR_CONNECT_S == 10
    assert supervisor.PRESS_S == 5
    assert serial_tap.TAP_CONNECT_S == 5
    assert flasher.FLASH_ATTEMPT_S == 120
    assert dut.API_WAIT_S == 90
    assert dut.BOOT_SETTLE_S == 15
    assert ota.OTA_ATTEMPT_S == 180
    assert dut.OTA_BOOT_S == 90
    assert dut.OTA_CONFIRM_WINDOW_S == 75
    assert qc.FAN_SETTLE_S == 15
    assert qc.DISCARD_READINGS == 2
    assert dutlink.API_CONNECT_S == 10
    assert dutlink.RECONNECT_S == 1
    assert dutlink.COMMAND_S == 5


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


def test_one_ota_test_fits_its_ceiling():
    """The OTA test of D-23: upload, then the new build ID, plus the API connect of the last probe and slack."""
    assert ota.OTA_ATTEMPT_S + dut.OTA_BOOT_S + dut.API_CONNECT_S + 30 < ini()["timeout"]


def test_fan_mapping_test_fits_its_ceiling_with_every_step_hitting_its_deadline():
    """The initial settle plus 4 channels x 3 duty steps, each step at its whole settle deadline,
    plus the session connect, one command per step and the closing switch-off."""
    steps = 1 + len(qc.CHANNELS) * len(qc.DUTIES)
    commands = len(qc.CHANNELS) * (1 + 2) + len(qc.CHANNELS)
    worst = dut.API_WAIT_S + steps * qc.FAN_SETTLE_S + commands * dutlink.COMMAND_S
    assert worst < ini()["timeout"]


def hil_job():
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return data["jobs"]["hil"]


def step_minutes(name):
    matches = [s for s in hil_job()["steps"] if s.get("name") == name]
    assert len(matches) == 1, name
    return matches[0]["timeout-minutes"]


def worst_case_teardown_s():
    """Every deadline of the teardown path hit: connect, release, bridge wait, then the
    known-good attempt and the commit-image fallback, each one flash plus one API wait."""
    switches = len([n for lines in contract.SWITCH.values() for n in lines.values()])
    connect = supervisor.SUPERVISOR_CONNECT_S + supervisor.STATE_WAIT + 5
    release = switches * supervisor.PRESS_S + supervisor.STATE_WAIT
    flash = dut.FLASH_ATTEMPTS * (supervisor.PRESS_S + dut.BOOTLOADER_SETTLE_S + flasher.FLASH_ATTEMPT_S) + supervisor.PRESS_S
    confirm = dut.API_WAIT_S + dut.API_CONNECT_S + 5  # the last probe may overshoot the deadline
    return connect + release + teardown.BRIDGE_FREE_S + 2 * (flash + confirm)


def test_deadlines_nest_operation_then_test_then_session_then_step_then_job():
    options = ini()
    assert flasher.FLASH_ATTEMPT_S < options["timeout"] < options["session_timeout"]
    assert options["session_timeout"] < step_minutes("Run hardware check") * 60
    assert step_minutes("Run hardware check") < hil_job()["timeout-minutes"]


def test_teardown_step_ceiling_exceeds_its_worst_case_so_no_flash_is_cut():
    assert worst_case_teardown_s() < step_minutes("Teardown") * 60


SV_CONNECT_S = supervisor.SUPERVISOR_CONNECT_S + supervisor.STATE_WAIT + 5
SWITCHES = len([n for lines in contract.SWITCH.values() for n in lines.values()])
SV_RELEASE_S = SWITCHES * supervisor.PRESS_S + supervisor.STATE_WAIT


def run_step_worst_case_s():
    """The run step under the harness's own deadlines: supervisor connect and release before the
    session, the session deadline (cooperative: checked after a test), one test started just before
    it running its whole per-test timeout, the final release and the DutLink close."""
    options = ini()
    return (
        SV_CONNECT_S
        + SV_RELEASE_S
        + options["session_timeout"]
        + options["timeout"]
        + SV_RELEASE_S
        + dutlink.API_CONNECT_S
    )


def test_run_step_ceiling_exceeds_the_session_deadline_plus_one_overshooting_test():
    """20 + 55 + 780 + 600 + 55 + 10 = 1520 s < 1560 s: the step ceiling is never the cut, the
    session deadline (RIG ERROR, Task 2 of 02-11) is."""
    assert run_step_worst_case_s() == 1520
    assert run_step_worst_case_s() < step_minutes("Run hardware check") * 60


def test_phase_2_budgets_are_the_documented_numbers():
    options = ini()
    assert (options["timeout"], options["session_timeout"]) == (600, 780)
    assert step_minutes("Run hardware check") == 26
    assert hil_job()["timeout-minutes"] == 60
    steps = [s["timeout-minutes"] for s in hil_job()["steps"]]
    assert steps == [3, 5, 3, 4, 26, 15, 3] and sum(steps) == 59


def test_the_job_deadline_is_one_minute_above_the_step_budgets():
    """The job deadline can never fall inside Teardown: 59 < 60, and 60 is the Phase 1 policy cap."""
    assert sum(s["timeout-minutes"] for s in hil_job()["steps"]) == hil_job()["timeout-minutes"] - 1


def test_step_ceilings_sum_to_less_than_the_job_deadline():
    """If every step used its whole ceiling the job deadline still would not fall inside Teardown."""
    steps = hil_job()["steps"]
    assert all(isinstance(s.get("timeout-minutes"), int) for s in steps), "every hil step needs timeout-minutes"
    assert sum(s["timeout-minutes"] for s in steps) < hil_job()["timeout-minutes"]


def test_session_timeout_is_documented_as_a_soft_check():
    text = PYPROJECT.read_text(encoding="utf-8")
    assert "cooperative only" in text and "HARD ceilings" in text


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


# ---- every rig test has a worst-case budget -------------------------------------------------

ALLOWANCE_S = 30  # supervisor presses and API commands: each normally takes milliseconds; one shared allowance per test
HIL_ROOT = Path(__file__).resolve().parents[2]


def ota_s():
    """Upload, then the new build ID, plus the API connect of the last probe (one OTA)."""
    return ota.OTA_ATTEMPT_S + dut.OTA_BOOT_S + dut.API_CONNECT_S


def fan_steps_s():
    """The initial settle plus every channel at every duty, each step at its whole settle deadline."""
    return (1 + len(qc.CHANNELS) * len(qc.DUTIES)) * qc.FAN_SETTLE_S


def smoke_s():
    """Tap connect, two flash attempts each with a bootloader press and settle, the reset press,
    the API wait with its last probe, and the boot settle window."""
    flash = dut.FLASH_ATTEMPTS * (supervisor.PRESS_S + dut.BOOTLOADER_SETTLE_S + flasher.FLASH_ATTEMPT_S)
    return serial_tap.TAP_CONNECT_S + flash + supervisor.PRESS_S + dut.API_WAIT_S + dut.API_CONNECT_S + dut.BOOT_SETTLE_S + ALLOWANCE_S


# Seconds per rig test function if every named wait of the test ran to its whole deadline, plus the
# session fixture the test is the first to pull in (the supervisor for test_00, the DutLink for the
# framework test) and ALLOWANCE_S. Parametrized tests have one row; the sum counts each case.
# A test that hits a deadline fails at once, so these are the longest a test can take and go on.
# 02-07 adds the state-check allowance to every row and a row for the safe-mode test.
WORST_CASE_S = {
    "test_supervisor_exposes_contract": SV_CONNECT_S + SV_RELEASE_S + ALLOWANCE_S,
    "test_switches_released": SWITCHES * supervisor.STATE_WAIT + ALLOWANCE_S,
    "test_commit_image_boots_and_reports_build_id": smoke_s(),
    "test_ota_to_qc_auto": ota_s() + ALLOWANCE_S,
    "test_dut_runs_the_shipped_framework": dut.API_WAIT_S + qc.TEXT_SENSOR_WAIT_S + ALLOWANCE_S,
    "test_fan_channels_map_to_their_own_tach": fan_steps_s() + ALLOWANCE_S,
    "test_hdc1080_reports_plausible_climate": qc.HDC_WINDOW_S + ALLOWANCE_S,
    "test_usr_button_reaches_dut": 3 * qc.USR_WAIT_S + 3 * supervisor.PRESS_S,
    "test_safe_mode_boot_is_reported_as_safe_mode": (
        dut.SAFE_MODE_DETECT_S + dut.CONFIRM_WAIT_S + supervisor.PRESS_S + dut.API_WAIT_S + ALLOWANCE_S
    ),
    "test_canary_swap_is_detected": ota_s() + fan_steps_s() + ALLOWANCE_S,
    "test_ota_back_to_commit_image": ota_s() + ALLOWANCE_S,
}


def collected_nodeids(target, cwd):
    """`pytest --collect-only -q <target>` run from `cwd`; the node ids it prints."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", target],
        cwd=cwd, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return [line.strip() for line in proc.stdout.splitlines() if "::" in line]


def function_name(nodeid):
    return nodeid.split("::")[-1].split("[")[0]


def budget_problems(nodeids, table):
    """Collected functions without a row, and rows without a collected function."""
    names = {function_name(n) for n in nodeids}
    return sorted(names - set(table)), sorted(set(table) - names)


def worst_case_sum_s(nodeids, table=None):
    table = WORST_CASE_S if table is None else table
    return sum(table[function_name(n)] for n in nodeids)


def test_every_collected_rig_test_has_exactly_one_worst_case_row():
    nodeids = collected_nodeids("tests/rig", HIL_ROOT)
    assert len(nodeids) >= len(WORST_CASE_S)
    assert budget_problems(nodeids, WORST_CASE_S) == ([], [])


def test_a_new_rig_test_without_a_row_fails_the_guard(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (tmp_path / "test_new.py").write_text(
        "import pytest\n\ndef test_new_thing():\n    pass\n\n@pytest.mark.parametrize('n', [1, 2])\ndef test_usr_button_reaches_dut(n):\n    pass\n",
        encoding="utf-8",
    )
    nodeids = collected_nodeids(".", tmp_path)
    assert budget_problems(nodeids, WORST_CASE_S)[0] == ["test_new_thing"]
    assert function_name("tests/rig/test_24_qc_buttons.py::test_usr_button_reaches_dut[3]") == "test_usr_button_reaches_dut"


def test_a_row_without_a_collected_test_fails_the_guard():
    nodeids = collected_nodeids("tests/rig", HIL_ROOT)
    assert budget_problems(nodeids, {**WORST_CASE_S, "test_that_was_removed": 1})[1] == ["test_that_was_removed"]


def test_every_row_stays_below_the_per_test_timeout():
    over = {name: seconds for name, seconds in WORST_CASE_S.items() if seconds >= ini()["timeout"]}
    assert over == {}


def test_the_canary_worst_case_fits_the_per_test_timeout_with_room_for_state_checks():
    """180 s OTA + 90 s boot wait + 13 fan steps of 15 s (the 12 steps and the initial settle)
    exceeded the old 420 s ceiling; 02-11 raised it to 600 s."""
    assert ota.OTA_ATTEMPT_S + dut.OTA_BOOT_S + 12 * qc.FAN_SETTLE_S > 420
    assert WORST_CASE_S["test_canary_swap_is_detected"] < ini()["timeout"]
    assert ini()["timeout"] - WORST_CASE_S["test_canary_swap_is_detected"] >= 90  # left for 02-07's state checks


def test_the_worst_case_sum_exceeds_the_session_deadline_by_design(capsys):
    """Why the session deadline, not the step ceiling, is the cut: the expected run is about 5
    minutes (measured), but the sum of worst cases is far beyond it."""
    nodeids = collected_nodeids("tests/rig", HIL_ROOT)
    total = worst_case_sum_s(nodeids)
    with capsys.disabled():
        print("\nworst-case sum over %d rig tests: %d s (session_timeout %d s, run step %d s)" % (
            len(nodeids), total, ini()["session_timeout"], step_minutes("Run hardware check") * 60))
    assert total > ini()["session_timeout"]
