"""The autouse dut_state fixture of tests/rig/conftest.py (HARN-03), in a real pytest subprocess.

A throwaway rootdir holds a copy of the rig conftest and one test module that replaces the hardware
fixtures (supervisor, rig_config, fw_manifest, dut_a, dut_link) with fakes that print what they are
asked. That proves what the fixture does around a test: which checks run before and after, what
fails with which message, that the one EN reset is spent only after a failed settle, and that safe
mode and an exhausted budget stay RigErrors.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from hil import contract

PROJECT = Path(__file__).resolve().parents[2]
CONFTEST = PROJECT / "tests" / "rig" / "conftest.py"
LABEL = contract.SERIAL_CONNECTED["A"].removesuffix(" Serial Connected")  # supervisor-name guard: no literal

COMMIT_ID = "3.2+hil." + "c" * 12
QC_ID = "3.2+qc." + "c" * 12

FAKES = '''
import json
import os
import time

import pytest
from types import SimpleNamespace

from hil import RigError, contract
from hil.budget import ResetBudgetExhausted, SafeModeError

SCRIPT = json.loads(os.environ["SCRIPT"])
IDS = {"commit": "%s", "qc-auto": "%s"}


def event(*parts):
    with open(os.environ["EVENTS"], "a", encoding="utf-8") as handle:
        handle.write(" ".join(str(p) for p in parts) + "\\n")


class FakeDut:
    id = "A"

    def __init__(self):
        self.probes = list(SCRIPT.get("probes", []))
        self.settles = list(SCRIPT.get("settles", []))

    def probe(self, key):
        event("probe")
        item = self.probes.pop(0) if self.probes else SCRIPT["default_probe"]
        if item == "unreachable":
            raise OSError("refused")
        return SimpleNamespace(project_version=IDS.get(item, item))

    def check_safe_mode_ports(self):
        event("ports")
        if SCRIPT.get("safe_mode"):
            raise SafeModeError("safe mode by ports")

    def settle(self, link):
        problems = self.settles.pop(0) if self.settles else []
        event("settle", len(problems))
        return problems

    def reset(self):
        event("reset")
        if SCRIPT.get("budget_exhausted"):
            raise ResetBudgetExhausted("budget exhausted")
        return "reset_9"

    def wait_running(self, key, mark):
        event("wait_running", mark)


class FakeLink:
    def wait_connected(self, deadline_s, project_version=None):
        event("wait_connected", project_version)


class FakeSupervisor:
    """The guard's view of the supervisor (03-08): counters, release lines and driven lines, all scripted.

    SCRIPT["watchdog"] (optional) = {"release": [[dut, line key], ...], "drive": [...], "rise": {dut: n}};
    the test body calls happen(). Without it the fake is silent and logs nothing.
    """

    def __init__(self):
        self.plan = SCRIPT.get("watchdog")
        self.counts = {"A": 6, "B": 0}
        self.releases = []
        self.driven = []

    def _line(self, pair):
        return contract.SWITCH[pair[0]][pair[1]]

    def happen(self):
        now = time.monotonic()
        plan = self.plan or {}
        self.driven += [(now, self._line(p)) for p in plan.get("drive", [])]
        self.releases += [(now, self._line(p)) for p in plan.get("release", [])]
        for dut_id, n in plan.get("rise", {}).items():
            self.counts[dut_id] += n

    def watchdog_counts(self):
        if self.plan is not None:
            event("watchdog_counts")
        return dict(self.counts)

    def releases_since(self, t):
        return [line for at, line in self.releases if at >= t]

    def driven_since(self, t):
        return [line for at, line in self.driven if at >= t]


@pytest.fixture(scope="session", autouse=True)
def supervisor():
    return FakeSupervisor()


@pytest.fixture(scope="session")
def rig_config():
    return SimpleNamespace(duts={"A": SimpleNamespace(rev="3.2")}, dut_api_key="k")


@pytest.fixture(scope="session")
def fw_manifest():
    images = {(role, "3.2"): SimpleNamespace(build_id=build_id) for role, build_id in IDS.items()}
    return SimpleNamespace(images=images, image=lambda role, rev=None: images[(role, rev)])


class FakeTap:
    def __init__(self):
        self.marks = []

    def mark(self, name):
        self.marks.append(name)


@pytest.fixture(scope="session", autouse=True)
def tap_a():
    return FakeTap()


@pytest.fixture(scope="session")
def dut_a():
    return FakeDut()


@pytest.fixture(scope="session", autouse=True)
def dut_link():
    return FakeLink()


''' % (COMMIT_ID, QC_ID)

BODY = '''
pytestmark = pytest.mark.image({marker})


def test_body():
    event("body")
'''


def run(tmp_path, script, marker='before="commit", after="qc-auto"', module="test_x.py", body=None):
    (tmp_path / "conftest.py").write_text(CONFTEST.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\nmarkers =\n    requires(*capabilities): x\n    image(before=None, after=None): x\n", encoding="utf-8"
    )
    source = FAKES + (body if body is not None else BODY.format(marker=marker))
    (tmp_path / module).write_text(source, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("HIL_", "GITHUB_"))}
    env["PYTHONPATH"] = str(PROJECT)
    env["SCRIPT"] = json.dumps({"default_probe": "commit", **script})
    events_file = tmp_path / "events.txt"
    events_file.write_text("", encoding="utf-8")
    env["EVENTS"] = str(events_file)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-s", "-q"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60,
    )
    return proc, events_file.read_text(encoding="utf-8").splitlines()


def test_a_clean_state_before_and_after_costs_no_reset(tmp_path):
    proc, events = run(tmp_path, {"probes": ["commit", "qc-auto"]})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert events == [
        "probe", "wait_connected " + COMMIT_ID, "settle 0",
        "body",
        "probe", "wait_connected " + QC_ID, "settle 0",
    ]


def test_the_before_check_runs_before_the_first_action_of_the_test(tmp_path):
    proc, events = run(tmp_path, {"probes": ["commit", "qc-auto"]})
    assert events.index("body") > events.index("settle 0")
    assert events[0] == "probe"


def test_the_wrong_build_id_before_fails_with_both_ids_and_the_test_does_not_run(tmp_path):
    proc, events = run(tmp_path, {"probes": ["3.2+hil." + "0" * 12]})
    assert proc.returncode != 0
    assert "precondition: %s runs 3.2+hil.%s, expected commit (%s)" % (LABEL, "0" * 12, COMMIT_ID) in proc.stdout
    assert "body" not in events and "reset" not in events


def test_a_dirty_dut_before_fails_naming_the_problems_and_never_resets(tmp_path):
    proc, events = run(tmp_path, {"probes": ["commit"], "settles": [["Fan 2 Speed still reads 5.0", "Button USR1 is not OFF"]]})
    assert proc.returncode != 0
    assert "precondition: %s is not clean (commit): Fan 2 Speed still reads 5.0; Button USR1 is not OFF" % LABEL in proc.stdout
    assert "body" not in events and "reset" not in events


def test_an_unreachable_api_before_is_a_failed_precondition_after_the_safe_mode_port_check(tmp_path):
    proc, events = run(tmp_path, {"probes": ["unreachable"]})
    assert proc.returncode != 0
    assert "does not answer on the API (OSError)" in proc.stdout
    assert events == ["probe", "ports"]


def test_safe_mode_before_is_a_safe_mode_error_not_a_failed_precondition(tmp_path):
    proc, events = run(tmp_path, {"probes": ["unreachable"], "safe_mode": True})
    assert proc.returncode != 0
    assert "SafeModeError: safe mode by ports" in proc.stdout and "does not answer" not in proc.stdout
    assert "body" not in events


def test_a_dirty_dut_after_costs_exactly_one_en_reset_and_a_second_settle(tmp_path):
    script = {"probes": ["commit", "qc-auto"], "settles": [[], ["Fan 3 Speed still reads 5.0"], []]}
    proc, events = run(tmp_path, script)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    after = events[events.index("body") + 1 :]
    assert after == [
        "probe", "wait_connected " + QC_ID, "settle 1",
        "reset", "wait_running reset_9",
        "wait_connected " + QC_ID, "settle 0",
    ]
    assert events.count("reset") == 1


def test_problems_that_survive_the_reset_fail_the_test_after_a_single_reset(tmp_path):
    script = {"probes": ["commit", "qc-auto"], "settles": [[], ["Fan 3 Speed still reads 5.0"], ["Fan 3 Speed still reads 5.0"]]}
    proc, events = run(tmp_path, script)
    assert proc.returncode != 0
    assert "%s did not return to a clean qc-auto state: Fan 3 Speed still reads 5.0" % LABEL in proc.stdout
    assert events.count("reset") == 1 and "body" in events


def test_the_wrong_build_id_after_fails_without_a_reset(tmp_path):
    proc, events = run(tmp_path, {"probes": ["commit", "commit"]})
    assert proc.returncode != 0
    assert "%s did not return to a clean qc-auto state: runs %s, expected %s" % (LABEL, COMMIT_ID, QC_ID) in proc.stdout
    assert "reset" not in events


def test_an_exhausted_budget_in_the_after_check_stays_a_rig_error(tmp_path):
    script = {"probes": ["commit", "qc-auto"], "settles": [[], ["Fan 3 Speed still reads 5.0"]], "budget_exhausted": True}
    proc, events = run(tmp_path, script)
    assert proc.returncode != 0
    assert "ResetBudgetExhausted: budget exhausted" in proc.stdout
    assert "wait_running" not in " ".join(events)


def test_after_alone_has_no_before_check(tmp_path):
    proc, events = run(tmp_path, {"probes": ["commit"]}, marker='after="commit"')
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert events[0] == "body" and events[1:] == ["probe", "wait_connected " + COMMIT_ID, "settle 0"]


def test_a_role_the_manifest_lacks_is_a_rig_error_at_setup(tmp_path):
    proc, events = run(tmp_path, {}, marker='"canary"')
    assert proc.returncode != 0
    assert "image role 'canary' is not in the manifest" in proc.stdout
    assert events == []


def test_the_exempt_module_gets_no_check_and_touches_no_fixture(tmp_path):
    body = "\n\ndef test_body():\n    event('body')\n"
    proc, events = run(tmp_path, {"probes": ["boom"]}, module="test_00_contract.py", body=body)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert events == ["body"]


@pytest.mark.parametrize("problems", [["a"], ["a", "b"]])
def test_every_problem_is_in_the_failure_message(tmp_path, problems):
    proc, _ = run(tmp_path, {"probes": ["commit"], "settles": [problems]})
    assert "; ".join(problems) in proc.stdout
