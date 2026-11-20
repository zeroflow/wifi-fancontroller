"""The autouse watchdog_guard of tests/rig/conftest.py (D-47, 03-08), in a real pytest subprocess.

Same harness as test_state_fixture: a throwaway rootdir with a copy of the rig conftest and fakes,
the supervisor fake scripted with what happens during the test body (lines driven, lines released,
counter rises). The guard's real decision (hil.supervisor.watchdog_guard_outcome) runs in the
subprocess, so this proves the wiring: a warning for a line the test did not drive and a passing
test, a RIG ERROR for a driven line and for an unexplained counter rise, nothing for the exempt
contract module, and the guard's teardown after the state fixture's after-check.
"""

from hil import contract
from test_state_fixture import run

EN_A = contract.SWITCH["A"]["en"]
EN_B = contract.SWITCH["B"]["en"]
USR1_A = contract.SWITCH["A"]["usr1"]
COUNTER_B = contract.WATCHDOG_RELEASES["B"]

BODY = '''
pytestmark = pytest.mark.image(before="commit", after="commit")


def test_body(supervisor):
    event("body")
    supervisor.happen()
'''

EXEMPT_BODY = '''
def test_body(supervisor):
    event("body")
    supervisor.happen()
'''

PROBES = {"probes": ["commit", "commit"]}


def test_a_release_of_a_line_the_test_did_not_drive_is_a_warning_and_the_test_passes(tmp_path):
    script = {**PROBES, "watchdog": {"drive": [["A", "en"]], "release": [["B", "en"]], "rise": {"B": 1}}}
    proc, events = run(tmp_path, script, body=BODY)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    text = "supervisor watchdog released %s during test_x.py::test_body; the test did not drive that line" % EN_B
    assert "WARNING: " + text in proc.stdout
    assert "UserWarning: " + text in proc.stdout  # pytest's warnings summary names it too
    assert "1 passed" in proc.stdout


def test_a_release_of_a_line_the_test_drove_is_a_rig_error(tmp_path):
    script = {**PROBES, "watchdog": {"drive": [["A", "usr1"]], "release": [["A", "usr1"]], "rise": {"A": 1}}}
    proc, _events = run(tmp_path, script, body=BODY)
    assert proc.returncode != 0
    assert "RigError: supervisor watchdog released %s during this test, and the test drove that line" % USR1_A in proc.stdout
    assert "error" in proc.stdout.splitlines()[-1]  # reported as an error of the test's teardown


def test_a_counter_rise_without_a_release_line_is_a_rig_error_naming_the_counter(tmp_path):
    script = {**PROBES, "watchdog": {"drive": [], "release": [], "rise": {"B": 1}}}
    proc, _events = run(tmp_path, script, body=BODY)
    assert proc.returncode != 0
    assert "RigError: supervisor watchdog counter %s rose during this test (0 -> 1) without a release line" % COUNTER_B in proc.stdout


def test_a_quiet_test_reads_the_counters_before_the_state_check_and_after_the_after_check(tmp_path):
    script = {**PROBES, "watchdog": {}}
    proc, events = run(tmp_path, script, body=BODY)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert events[0] == "watchdog_counts" and events[1] == "probe"
    assert events[-1] == "watchdog_counts" and events.index("body") < len(events) - 1
    assert "settle 0" in events[events.index("body"):-1]


def test_the_exempt_contract_module_gets_no_guard(tmp_path):
    script = {"watchdog": {"release": [["A", "en"]], "drive": [["A", "en"]], "rise": {"A": 1}}}
    proc, events = run(tmp_path, script, module="test_00_contract.py", body=EXEMPT_BODY)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert events == ["body"]
    assert EN_A not in proc.stdout
