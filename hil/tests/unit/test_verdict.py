"""The run's verdict, decided from what pytest did and not from its exit code alone (HARN-02, D-31, QC-06).

The sessions below are real pytest runs in a throwaway rootdir with the Collector as plugin,
driven from a subprocess so a nested session cannot disturb this one.
"""

import json
import subprocess
import sys
import textwrap
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from hil.__main__ import Collector, decide_verdict

PROJECT = Path(__file__).resolve().parents[2]
MARK = "@@RESULT@@"
LABEL = "DUT %s" % "A"
CAP_REASON = LABEL + " (rig.toml) lacks capability: fan_tach_bridge"

DRIVER = """
import json
import sys

import pytest

from hil.__main__ import Collector, decide_verdict

collector = Collector()
code = int(pytest.main(["-p", "no:cacheprovider", "-q", "-c", "pytest.ini", *sys.argv[1:], "."], plugins=[collector]))
verdict, lines = decide_verdict(code, collector)
print("%s" + json.dumps({"code": code, "verdict": verdict, "lines": lines, "report": collector.report()}))
""" % MARK

INI = "[pytest]\nmarkers =\n    canary: x\n    requires(*capabilities): x\n"


def session(tmp_path, files, ini=INI, args=()):
    """Run a real pytest session over `files` ({name: source}); return the driver's result dict."""
    (tmp_path / "pytest.ini").write_text(ini, encoding="utf-8")
    for name, source in files.items():
        (tmp_path / name).write_text(textwrap.dedent(source), encoding="utf-8")
    driver = tmp_path.parent / (tmp_path.name + "-driver.py")
    driver.write_text(DRIVER, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(driver), *args],
        cwd=tmp_path, env={"PYTHONPATH": str(PROJECT), "PATH": ""}, capture_output=True, text=True, timeout=120,
    )
    line = next((x for x in proc.stdout.splitlines() if x.startswith(MARK)), None)
    assert line is not None, proc.stdout + proc.stderr
    return json.loads(line[len(MARK):])


CANARY_PASSES = """
    import pytest

    @pytest.mark.canary
    def test_canary():
        pass
"""

PLAIN_PASS = """
    def test_plain():
        pass
"""


def test_a_run_with_a_passed_canary_is_pass(tmp_path):
    result = session(tmp_path, {"test_a.py": CANARY_PASSES, "test_b.py": PLAIN_PASS})
    assert (result["code"], result["verdict"], result["lines"]) == (0, "PASS", [])
    assert result["report"]["canary_passed"] is True
    assert result["report"]["passed"] == 2


def test_a_canary_skipped_by_a_capability_is_rig_error_with_the_reason(tmp_path):
    source = """
        import pytest

        @pytest.mark.canary
        def test_canary():
            pytest.skip(%r)
    """ % CAP_REASON
    result = session(tmp_path, {"test_a.py": source, "test_b.py": PLAIN_PASS})
    assert result["code"] == 0  # pytest alone would call this green
    assert result["verdict"] == "RIG ERROR"
    assert result["lines"] == [
        "RIG ERROR: the canary was not detected in this run (skipped: %s); a run without canary detection is never green" % CAP_REASON
    ]
    assert result["report"]["canary_passed"] is False


@pytest.mark.parametrize(
    "decorator",
    ['@pytest.mark.skip(reason="no canary today")', '@pytest.mark.skipif(True, reason="no canary today")'],
)
def test_skip_marks_give_their_reason_without_the_skipped_prefix(tmp_path, decorator):
    source = "import pytest\n\n@pytest.mark.canary\n%s\ndef test_canary():\n    pass\n" % decorator
    result = session(tmp_path, {"test_a.py": source, "test_b.py": PLAIN_PASS})
    assert result["verdict"] == "RIG ERROR"
    assert "(skipped: no canary today)" in result["lines"][0]
    assert [s["reason"] for s in result["report"]["skipped"]] == ["no canary today"]


def test_a_canary_skipped_in_setup_by_a_hook_gives_the_reason(tmp_path):
    hook = """
        import pytest

        @pytest.hookimpl(tryfirst=True)
        def pytest_runtest_setup(item):
            if item.get_closest_marker("requires"):
                pytest.skip(%r)
    """ % CAP_REASON
    source = """
        import pytest

        pytestmark = [pytest.mark.requires("fan_tach_bridge"), pytest.mark.canary]

        def test_canary():
            assert False, "must not run"
    """
    result = session(tmp_path, {"conftest.py": hook, "test_a.py": source, "test_b.py": PLAIN_PASS})
    assert result["verdict"] == "RIG ERROR"
    assert "(skipped: %s)" % CAP_REASON in result["lines"][0]


def test_a_deselected_canary_is_rig_error_not_run(tmp_path):
    result = session(tmp_path, {"test_a.py": CANARY_PASSES, "test_b.py": PLAIN_PASS}, args=("-k", "plain"))
    assert result["code"] == 0
    assert result["verdict"] == "RIG ERROR"
    assert result["lines"] == [
        "RIG ERROR: the canary was not detected in this run (not run); a run without canary detection is never green"
    ]


def test_a_canary_that_is_not_collected_is_rig_error_not_run(tmp_path):
    result = session(tmp_path, {"test_b.py": PLAIN_PASS})
    assert result["verdict"] == "RIG ERROR"
    assert "(not run)" in result["lines"][0]


def test_a_failed_canary_is_fail_not_rig_error(tmp_path):
    source = "import pytest\n\n@pytest.mark.canary\ndef test_canary():\n    assert False, 'slipped through'\n"
    result = session(tmp_path, {"test_a.py": source, "test_b.py": PLAIN_PASS})
    assert (result["code"], result["verdict"], result["lines"]) == (1, "FAIL", [])
    assert result["report"]["canary_passed"] is False
    assert result["report"]["failed"] == 1


def test_a_canary_whose_teardown_fails_did_not_pass(tmp_path):
    source = """
        import pytest

        @pytest.fixture
        def late():
            yield
            raise RuntimeError("teardown broke")

        @pytest.mark.canary
        def test_canary(late):
            pass
    """
    result = session(tmp_path, {"test_a.py": source})
    assert result["code"] == 1 and result["verdict"] == "FAIL"
    assert result["report"]["canary_passed"] is False
    assert result["report"]["passed"] == 0


def test_a_rig_error_stays_rig_error(tmp_path):
    source = """
        from hil import RigError

        def test_rig():
            raise RigError("the rig is down")
    """
    result = session(tmp_path, {"test_a.py": source})
    assert (result["code"], result["verdict"], result["lines"]) == (1, "RIG ERROR", ["RIG ERROR: the rig is down"])


def test_exit_codes_two_and_other_keep_their_classes():
    collector = Collector()
    assert decide_verdict(2, collector) == ("INTERRUPTED", [])
    assert decide_verdict(3, collector) == ("RIG ERROR", [])
    assert decide_verdict(5, collector) == ("RIG ERROR", [])


def test_collector_reads_the_reports_it_is_given():
    collector = Collector()

    def item(nodeid, canary):
        return SimpleNamespace(nodeid=nodeid, get_closest_marker=lambda name: object() if (canary and name == "canary") else None)

    call_ok = SimpleNamespace(excinfo=None)
    collector.pytest_runtest_makereport(item("t::canary", True), call_ok)
    collector.pytest_runtest_makereport(item("t::other", False), call_ok)

    def report(nodeid, when, outcome, longrepr=None):
        return SimpleNamespace(
            nodeid=nodeid, when=when, passed=outcome == "passed", failed=outcome == "failed", skipped=outcome == "skipped", longrepr=longrepr
        )

    collector.pytest_runtest_logreport(report("t::canary", "setup", "passed"))
    collector.pytest_runtest_logreport(report("t::canary", "call", "passed"))
    collector.pytest_runtest_logreport(report("t::canary", "teardown", "passed"))
    collector.pytest_runtest_logreport(report("t::other", "setup", "skipped", ("f.py", 3, "Skipped: why not")))
    collector.pytest_runtest_logreport(report("t::other", "teardown", "passed"))
    assert collector.passed == 1 and collector.failed == 0 and collector.canary_passed is True
    assert collector.skipped == [{"nodeid": "t::other", "reason": "why not"}]


def test_the_canary_marker_is_registered_and_set_on_the_canary_test_only():
    ini = tomllib.loads((PROJECT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["pytest"]["ini_options"]
    assert any(m.startswith("canary:") for m in ini["markers"])
    script = (
        "import json, pytest\n"
        "class P:\n"
        "    def pytest_collection_finish(self, session):\n"
        "        rows = {}\n"
        "        for item in session.items:\n"
        "            req = [list(m.args) for m in item.iter_markers('requires')]\n"
        "            rows[item.nodeid] = {'requires': req, 'canary': item.get_closest_marker('canary') is not None}\n"
        "        print('%s' + json.dumps(rows))\n"
        "pytest.main(['-c', 'pyproject.toml', '--collect-only', '-q', 'tests/rig'], plugins=[P()])\n" % MARK
    )
    proc = subprocess.run([sys.executable, "-c", script], cwd=PROJECT, capture_output=True, text=True, timeout=120)
    line = next(x for x in proc.stdout.splitlines() if x.startswith(MARK))
    rows = json.loads(line[len(MARK):])
    canary = {n: r for n, r in rows.items() if "test_30_canary" in n}
    fans = {n: r for n, r in rows.items() if "test_22_qc_fans" in n}
    assert canary and fans
    for row in [*canary.values(), *fans.values()]:
        assert ["fan_tach_bridge"] in row["requires"]
    assert all(r["canary"] for r in canary.values())
    assert [n for n, r in rows.items() if r["canary"]] == list(canary)
