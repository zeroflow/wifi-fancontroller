"""Deadlines nest, and a pytest-timeout in signal mode still runs finalizers."""

import ast
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

from hil import RigError, budget, contract, dut, dutlink, flasher, ota, preflight, qc, recovery, rollback, serial_tap, supervisor, teardown

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
    assert dut.BOOTLOADER_BANNER_S == 3
    assert dut.CONFIRM_WAIT_S == 75
    assert dut.MARK_COMMIT_S == 2
    assert dut.SOAK_S == 70
    assert dut.LINK_WAIT_S == 30
    assert dut.SETTLE_S == 10
    assert dut.SAFE_MODE_DETECT_S == 45
    assert budget.RESET_BUDGET_LIMIT == 8
    assert budget.RESET_DECAY_S == 70
    assert qc.FAN_SETTLE_S == 15
    assert qc.HDC_WINDOW_S == 30
    assert qc.USR_WAIT_S == 5
    assert qc.TEXT_SENSOR_WAIT_S == 10
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


def worst_case_preflight_s():
    """`hil preflight` with every deadline hit and its one heal (D-43, D-44): supervisor connect and
    release, both bridges at the whole eviction wait, the tap connect, the boot check, the heal (two
    flash attempts with their bootloader presses and banner waits, the reset, the API wait), the recheck
    and the closing disconnect. A probe is bounded by Supervisor.run (API_CONNECT_S + 5); the boot check
    tries the HIL key and no encryption per poll, so its last poll may overshoot by two probes and a sleep."""
    probe = dut.API_CONNECT_S + 5
    connect = SV_CONNECT_S
    release = SV_RELEASE_S
    bridges = 2 * (preflight.EVICT_WAIT_S + preflight.POLL_S)
    boot_check = supervisor.PRESS_S + preflight.BOOT_BANNER_S + dut.API_WAIT_S + 2 * probe + preflight.API_POLL_S
    flash = dut.FLASH_ATTEMPTS * (supervisor.PRESS_S + dut.BOOTLOADER_BANNER_S + flasher.FLASH_ATTEMPT_S) + supervisor.PRESS_S
    heal = flash + dut.API_WAIT_S + probe + 1  # wait_api: its last probe and the 1 s sleep after it
    close = supervisor.PRESS_S + 5 + 2  # supervisor disconnect and loop join, tap join
    return connect + release + bridges + serial_tap.TAP_CONNECT_S + boot_check + heal + boot_check + close


def test_preflight_step_ceiling_exceeds_its_worst_case_with_one_heal():
    """About 802 s with every deadline hit (a healthy preflight takes about 7 s, a real heal about 200 s,
    03-07): the 14 minute step is never the cut, preflight's own RIG ERROR is."""
    assert 780 < worst_case_preflight_s() < step_minutes("Preflight") * 60


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
    """20 + 55 + 1500 + 620 + 55 + 10 = 2260 s < 2280 s: the step ceiling is never the cut, the
    session deadline (RIG ERROR, Task 2 of 02-11) is."""
    assert run_step_worst_case_s() == 2260
    assert run_step_worst_case_s() < step_minutes("Run hardware check") * 60


def test_phase_3_budgets_are_the_documented_numbers():
    """03-04, maintainer decision cap-90: session 1500 s, run step 38 min, policy cap 90. 03-08 adds the
    14 minute Preflight step; 03-14 adds the 3 minute baseline download right after the firmware download.
    Each changes the step list and the job deadline (always step sum + 1) in the same commit, never the cap."""
    options = ini()
    assert (options["timeout"], options["session_timeout"]) == (620, 1500)
    assert step_minutes("Run hardware check") == 38
    assert step_minutes("Preflight") == 14
    names = [s["name"] for s in hil_job()["steps"]]
    assert names.index("Sync environment") + 1 == names.index("Preflight") == names.index("Run hardware check") - 1
    assert names.index("Download firmware and manifest") + 1 == names.index("Download release baseline")
    steps = [s["timeout-minutes"] for s in hil_job()["steps"]]
    assert steps == [3, 5, 3, 3, 4, 14, 38, 15, 3] and sum(steps) == 88
    assert hil_job()["timeout-minutes"] == sum(steps) + 1 == 89 <= 90


def test_the_job_deadline_is_one_minute_above_the_step_budgets():
    """The job deadline can never fall inside Teardown: the step sum 88 < 89, and 89 is under the 90 minute policy cap."""
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
    """test_10 (release baseline, D-36): tap connect, two flash attempts each with a bootloader press and
    settle, the reset press, the rejoin wait (baseline.REJOIN_S, the API wait) with its last probe, and the
    boot settle window the old smoke test had (kept as slack)."""
    flash = dut.FLASH_ATTEMPTS * (supervisor.PRESS_S + dut.BOOTLOADER_SETTLE_S + flasher.FLASH_ATTEMPT_S)
    return serial_tap.TAP_CONNECT_S + flash + supervisor.PRESS_S + dut.API_WAIT_S + dut.API_CONNECT_S + dut.BOOT_SETTLE_S + ALLOWANCE_S


def test_the_soak_ends_inside_the_upgrade_rows_boot_and_confirm_waits():
    """The soak runs to SOAK_S after the OTA end; the boot wait and the confirm wait come after that end too."""
    assert dut.SOAK_S <= dut.OTA_BOOT_S + dut.CONFIRM_WAIT_S


def restore_s():
    """test_12 (serial restore after the upgrade, 03-11): two flash attempts each with a bootloader press and
    settle, the reset press, the API wait with its last probe, and the boot settle window of the D-14 gate."""
    flash = dut.FLASH_ATTEMPTS * (supervisor.PRESS_S + dut.BOOTLOADER_SETTLE_S + flasher.FLASH_ATTEMPT_S)
    return flash + supervisor.PRESS_S + dut.API_WAIT_S + dut.API_CONNECT_S + dut.BOOT_SETTLE_S


def test_the_release_baseline_row_waits_as_long_as_baseline_flash_does():
    from hil import baseline

    assert baseline.REJOIN_S == dut.API_WAIT_S


def broken_dark_s():
    """test_40: the OTA upload and the Project line on UART0 (no API probe), the state line, the dark window
    with its last poll and the port probes of one slow poll."""
    return (
        ota.OTA_ATTEMPT_S
        + dut.OTA_BOOT_S
        + recovery.OTA_STATE_LINE_S
        + recovery.DARK_WINDOW_S
        + recovery.DARK_POLL_S
        + 3 * dut.PORT_PROBE_S
    )


def uart_recovery_s():
    """test_41: the two port probes, two flash attempts each with a bootloader press and settle, the reset
    press, the API wait with its last probe, and the boot settle window of the D-14 gate."""
    flash = dut.FLASH_ATTEMPTS * (supervisor.PRESS_S + dut.BOOTLOADER_SETTLE_S + flasher.FLASH_ATTEMPT_S)
    return 2 * dut.PORT_PROBE_S + flash + supervisor.PRESS_S + dut.API_WAIT_S + dut.API_CONNECT_S + dut.BOOT_SETTLE_S


# 02-07: the before and after state checks of a test with an image marker (HARN-03) add one fixed
# allowance: a settle (SETTLE_S) and one wait for the API to answer again (API_WAIT_S). It is a
# fixed allowance, not the sum of every check at its deadline: a check that hits a deadline fails
# the test at once, and the one escalation (EN reset, wait for the boot, settle again) only happens
# after a test has already ended.
STATE_CHECK_S = dut.SETTLE_S + dut.API_WAIT_S

# Seconds per rig test function if every named wait of the test ran to its whole deadline, plus the
# session fixture the test is the first to pull in (the supervisor for test_00, the DutLink for the
# framework test) and ALLOWANCE_S, WITHOUT the state checks (added below). Parametrized tests have
# one row; the sum counts each case. A test that hits a deadline fails at once, so these are the
# longest a test can take and go on.
BASE_S = {
    "test_supervisor_exposes_contract": SV_CONNECT_S + SV_RELEASE_S + ALLOWANCE_S,
    "test_switches_released": SWITCHES * supervisor.STATE_WAIT + ALLOWANCE_S,
    "test_release_baseline_boots_and_rejoins": smoke_s(),
    # REG-02: the OTA, the DutLink session of the new image, the wait for 'Boot seems successful' in the API
    # log (the 70 s soak overlaps it) and the final probe.
    "test_ota_from_the_release_to_the_commit": (
        ota_s() + ALLOWANCE_S + dut.LINK_WAIT_S + dut.CONFIRM_WAIT_S + dut.MARK_COMMIT_S + dut.API_CONNECT_S
    ),
    # REG-03: one fresh API session that connects and lists every entity (golden.capture's deadline).
    "test_entities_match_the_golden_list": dut.API_CONNECT_S + 10 + ALLOWANCE_S,
    "test_commit_image_is_written_over_serial_after_the_upgrade": restore_s() + ALLOWANCE_S,
    "test_ota_to_qc_auto": ota_s() + ALLOWANCE_S,
    "test_dut_runs_the_shipped_framework": dut.API_WAIT_S + qc.TEXT_SENSOR_WAIT_S + ALLOWANCE_S,
    "test_fan_channels_map_to_their_own_tach": fan_steps_s() + ALLOWANCE_S,
    "test_hdc1080_reports_plausible_climate": qc.HDC_WINDOW_S + ALLOWANCE_S,
    "test_usr_button_reaches_dut": 3 * qc.USR_WAIT_S + 3 * supervisor.PRESS_S,
    "test_safe_mode_boot_is_reported_as_safe_mode": (
        dut.SAFE_MODE_DETECT_S + dut.CONFIRM_WAIT_S + dut.MARK_COMMIT_S + supervisor.PRESS_S + dut.API_WAIT_S
        + ALLOWANCE_S
    ),
    "test_canary_swap_is_detected": ota_s() + fan_steps_s() + ALLOWANCE_S,
    # REG-05, D-39: the armed canary -> commit OTA, the wait for its rollback-state line, the forced EN reset and
    # the boot of the image it falls back to.
    "test_en_reset_before_the_mark_rolls_back": (
        ota_s() + rollback.ROLLBACK_LINE_S + supervisor.PRESS_S + dut.API_WAIT_S + dut.API_CONNECT_S + ALLOWANCE_S
    ),
    # The OTA back to commit, the wait for its mark and its otadata commit (03-14), a normal (guarded) EN reset
    # and the boot of the same image.
    "test_en_reset_after_the_mark_keeps_the_image": (
        ota_s() + dut.CONFIRM_WAIT_S + dut.MARK_COMMIT_S + supervisor.PRESS_S + dut.API_WAIT_S + dut.API_CONNECT_S + ALLOWANCE_S
    ),
    "test_broken_image_is_alive_but_dark": broken_dark_s() + ALLOWANCE_S,
    "test_uart_flash_recovers_the_dark_dut": uart_recovery_s() + ALLOWANCE_S,
}


def exempt_test_functions():
    """Test functions of the modules dut.STATE_EXEMPT lists: the only rows without the state-check allowance."""
    names = set()
    for module in dut.STATE_EXEMPT:
        tree = ast.parse((HIL_ROOT / "tests" / "rig" / module).read_text(encoding="utf-8"))
        names |= {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")}
    return names


WORST_CASE_S = {
    name: seconds + (0 if name in exempt_test_functions() else STATE_CHECK_S) for name, seconds in BASE_S.items()
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


def test_state_check_allowance_is_a_settle_plus_one_api_wait():
    assert STATE_CHECK_S == 100 == dut.SETTLE_S + dut.API_WAIT_S


def test_every_row_of_a_test_with_an_image_marker_carries_the_state_check_allowance():
    """The numbers, written out: the two exempt rows (test_00_contract) are unchanged from 02-11, every
    other row is its 02-11 value plus 100 s, and the safe-mode test has its own row."""
    assert exempt_test_functions() == {"test_supervisor_exposes_contract", "test_switches_released"}
    assert WORST_CASE_S == {
        "test_supervisor_exposes_contract": 105,
        "test_switches_released": 80,
        "test_release_baseline_boots_and_rejoins": 506,
        "test_ota_from_the_release_to_the_commit": 527,
        "test_entities_match_the_golden_list": 150,
        "test_commit_image_is_written_over_serial_after_the_upgrade": 501,
        "test_ota_to_qc_auto": 410,
        "test_dut_runs_the_shipped_framework": 230,
        "test_fan_channels_map_to_their_own_tach": 325,
        "test_hdc1080_reports_plausible_climate": 160,
        "test_usr_button_reaches_dut": 130,
        "test_safe_mode_boot_is_reported_as_safe_mode": 347,
        "test_canary_swap_is_detected": 605,
        "test_en_reset_before_the_mark_rolls_back": 535,
        "test_en_reset_after_the_mark_keeps_the_image": 592,
        "test_broken_image_is_alive_but_dark": 486,
        "test_uart_flash_recovers_the_dark_dut": 505,
    }


def test_the_canary_worst_case_with_its_state_checks_fits_the_per_test_timeout():
    """180 s OTA + 90 s boot wait + 13 fan steps of 15 s exceeded the old 420 s ceiling (02-11 raised it to
    600 s). With 02-07's state checks the canary row is 605 s, so the ceiling is 620 s (the run-step bound
    in test_run_step_ceiling_exceeds_the_session_deadline_plus_one_overshooting_test moves with it)."""
    assert ota.OTA_ATTEMPT_S + dut.OTA_BOOT_S + 12 * qc.FAN_SETTLE_S > 420
    assert WORST_CASE_S["test_canary_swap_is_detected"] == 605
    assert ini()["timeout"] - WORST_CASE_S["test_canary_swap_is_detected"] >= 15


def test_the_safe_mode_test_row_is_its_waits_plus_the_allowances():
    expected = (dut.SAFE_MODE_DETECT_S + dut.CONFIRM_WAIT_S + dut.MARK_COMMIT_S + supervisor.PRESS_S + dut.API_WAIT_S
                + ALLOWANCE_S + STATE_CHECK_S)
    assert WORST_CASE_S["test_safe_mode_boot_is_reported_as_safe_mode"] == expected < ini()["timeout"]


def test_the_worst_case_sum_exceeds_the_session_deadline_by_design(capsys):
    """Why the session deadline, not the step ceiling, is the cut: the expected run is about 5
    minutes (measured), but the sum of worst cases is far beyond it."""
    nodeids = collected_nodeids("tests/rig", HIL_ROOT)
    total = worst_case_sum_s(nodeids)
    with capsys.disabled():
        print("\nworst-case sum over %d rig tests: %d s (session_timeout %d s, run step %d s)" % (
            len(nodeids), total, ini()["session_timeout"], step_minutes("Run hardware check") * 60))
    assert total > ini()["session_timeout"]
