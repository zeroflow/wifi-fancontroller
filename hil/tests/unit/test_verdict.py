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

from hil import __main__ as entry
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
print("%s" + json.dumps({"code": code, "verdict": verdict, "lines": lines, "report": collector.report(), "events": [list(e) for e in collector.events]}))
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


FAIL_THEN_RIG = """
    from hil import RigError

    def test_a_fails():
        assert False, "fan reading wrong\\nsecond line"

    def test_b_rig_down():
        raise RigError("supervisor dropped")
"""

RIG_THEN_FAIL = """
    from hil import RigError

    def test_a_rig_down():
        raise RigError("supervisor dropped")

    def test_b_fails():
        assert False, "fan reading wrong"
"""


def test_fail_then_rig_error_is_fail_and_the_rig_error_stays_listed(tmp_path):
    result = session(tmp_path, {"test_a.py": FAIL_THEN_RIG})
    assert (result["code"], result["verdict"]) == (1, "FAIL")
    assert result["lines"] == ["RIG ERROR (after the first failure): supervisor dropped"]


def test_rig_error_then_fail_is_rig_error_first_class_wins(tmp_path):
    # Task 1 decision (maintainer): the first recorded failure class decides; the later failure is only listed.
    result = session(tmp_path, {"test_a.py": RIG_THEN_FAIL})
    assert (result["code"], result["verdict"]) == (1, "RIG ERROR")
    assert result["lines"] == ["RIG ERROR: supervisor dropped"]
    assert result["report"]["failed_tests"] == ["test_a.py::test_a_rig_down", "test_a.py::test_b_fails"]


def test_a_failing_call_then_a_rig_error_in_teardown_is_fail(tmp_path):
    source = """
        import pytest
        from hil import RigError

        @pytest.fixture
        def late():
            yield
            raise RigError("lines not released")

        def test_a(late):
            assert False, "broke in the call phase"
    """
    result = session(tmp_path, {"test_a.py": source})
    assert (result["code"], result["verdict"]) == (1, "FAIL")
    assert result["lines"] == ["RIG ERROR (after the first failure): lines not released"]


def test_a_rig_error_in_setup_then_nothing_else_is_rig_error(tmp_path):
    source = """
        import pytest
        from hil import RigError

        @pytest.fixture
        def broken():
            raise RigError("setup down")

        def test_a(broken):
            pass
    """
    result = session(tmp_path, {"test_a.py": source})
    assert (result["verdict"], result["lines"]) == ("RIG ERROR", ["RIG ERROR: setup down"])


def test_a_firmware_failure_is_a_failure_not_a_rig_event(tmp_path):
    source = """
        from hil import FirmwareFailure

        def test_a():
            raise FirmwareFailure("DUT A rebooted")
    """
    result = session(tmp_path, {"test_a.py": source})
    assert (result["code"], result["verdict"], result["lines"]) == (1, "FAIL", [])


def test_a_nonzero_exit_without_any_recorded_failure_stays_fail_and_zero_collected_is_rig_error(tmp_path):
    assert decide_verdict(1, Collector()) == ("FAIL", [])
    result = session(tmp_path, {"test_a.py": "x = 1\n"})
    assert result["code"] == 5
    assert result["verdict"] == "RIG ERROR"
    assert result["lines"] == ["RIG ERROR: pytest ended with exit code 5"]


def test_the_collector_keeps_pytest_report_order_of_failure_events(tmp_path):
    source = """
        import pytest
        from hil import RigError

        @pytest.fixture
        def late():
            yield
            raise RigError("teardown rig")

        def test_a(late):
            assert False, "call fail"

        def test_b():
            raise RigError("second rig")
    """
    result = session(tmp_path, {"test_a.py": source})
    assert result["events"] == [
        ["fail", "test_a.py::test_a", "call", "call fail"],
        ["rig", "test_a.py::test_a", "teardown", "teardown rig"],
        ["rig", "test_a.py::test_b", "call", "second rig"],
    ]


def make_collector(*events):
    collector = Collector()
    collector.events = [tuple(e) for e in events]
    collector.rig_errors = [e[3] for e in events if e[0] == "rig"]
    return collector


GITHUB = {"GITHUB_ACTIONS": "true"}


def test_annotations_one_line_per_verdict_under_github_actions():
    fail = make_collector(("fail", "t.py::test_x", "call", "boom\nsecond"), ("rig", "t.py::test_y", "call", "rig down"))
    assert entry.verdict_annotation("PASS", [], Collector(), "3.2+hil.abc", GITHUB) == [
        "::notice title=HIL PASS::DUT A passed on 3.2+hil.abc"
    ]
    assert entry.verdict_annotation("FAIL", [], fail, "b", GITHUB) == ["::error title=HIL FAIL::t.py::test_x: boom"]
    assert entry.verdict_annotation("RIG ERROR", ["RIG ERROR: rig down", "RIG ERROR: more"], Collector(), "b", GITHUB) == [
        "::error title=RIG ERROR::rig down"
    ]
    assert entry.verdict_annotation("INTERRUPTED", [], Collector(), "b", GITHUB) == [
        "::error title=HIL INTERRUPTED::run interrupted"
    ]


def test_annotations_are_off_outside_github_actions():
    for env in ({}, {"GITHUB_ACTIONS": "false"}):
        for verdict in ("PASS", "FAIL", "RIG ERROR", "INTERRUPTED"):
            assert entry.verdict_annotation(verdict, ["RIG ERROR: x"], make_collector(("fail", "t", "call", "m")), "b", env) == []


def test_annotation_messages_are_one_line_and_capped():
    long = make_collector(("fail", "t.py::test_x", "call", "x" * 1000))
    (line,) = entry.verdict_annotation("FAIL", [], long, "b", GITHUB)
    assert "\n" not in line and "\r" not in line
    assert len(line) <= len("::error title=HIL FAIL::") + 300
    (rig_line,) = entry.verdict_annotation("RIG ERROR", ["RIG ERROR: a\r\nb " + "y" * 1000], Collector(), "b", GITHUB)
    assert "\n" not in rig_line and len(rig_line) <= len("::error title=RIG ERROR::") + 300


def test_run_prints_one_annotation_per_verdict_and_none_outside_actions(run_env, monkeypatch, capsys):
    def stand_in(args, plugins):
        plugins[0].pytest_runtest_makereport(
            SimpleNamespace(nodeid="t::a", get_closest_marker=lambda name: None),
            SimpleNamespace(when="call", excinfo=SimpleNamespace(value=AssertionError("fan wrong"))),
        )
        plugins[0].pytest_runtest_logreport(report("t::a", "call", "failed"))
        return 1

    monkeypatch.setattr(entry.pytest, "main", stand_in)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert entry._run({}) == 1
    lines = capsys.readouterr().out.splitlines()
    assert [x for x in lines if x.startswith("::error title=")] == ["::error title=HIL FAIL::t::a: fan wrong"]
    monkeypatch.setenv("GITHUB_ACTIONS", "false")
    assert entry._run({}) == 1
    assert [x for x in capsys.readouterr().out.splitlines() if x.startswith("::")] == []


def test_the_early_rig_error_return_prints_the_rig_error_annotation(run_env, monkeypatch, capsys):
    from hil import RigError

    def refuse():
        raise RigError("manifest: schema must be 2")

    monkeypatch.setattr(entry, "load_rig", refuse)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert entry._run({}) == 3
    assert "::error title=RIG ERROR::manifest: schema must be 2" in capsys.readouterr().out.splitlines()


def test_exit_codes_two_and_other_keep_their_classes():
    collector = Collector()
    assert decide_verdict(2, collector) == ("INTERRUPTED", [])
    assert decide_verdict(3, collector) == ("RIG ERROR", ["RIG ERROR: pytest ended with exit code 3"])
    assert decide_verdict(5, collector) == ("RIG ERROR", ["RIG ERROR: pytest ended with exit code 5"])


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


# ---- no vacuous green ----------------------------------------------------------------------

SKIP_TWO = """
    import pytest

    def test_one():
        pytest.skip(%r)

    def test_two():
        pytest.skip(%r)
""" % ("first reason", "second reason")


def test_exit_zero_with_every_test_skipped_is_rig_error_no_test_passed(tmp_path):
    result = session(tmp_path, {"test_a.py": SKIP_TWO})
    assert result["code"] == 0  # pytest calls an all-skip run green
    assert result["verdict"] == "RIG ERROR"
    assert result["lines"] == ["RIG ERROR: no test passed; a run without a passing test is never green"]
    assert result["report"]["passed"] == 0
    assert [s["reason"] for s in result["report"]["skipped"]] == ["first reason", "second reason"]


def report(nodeid, when, outcome, longrepr=None):
    return SimpleNamespace(
        nodeid=nodeid, when=when, passed=outcome == "passed", failed=outcome == "failed", skipped=outcome == "skipped", longrepr=longrepr
    )


def test_a_collector_that_saw_two_setup_skips_and_no_call_is_rig_error():
    collector = Collector()
    for nodeid in ("t::a", "t::b"):
        collector.pytest_runtest_logreport(report(nodeid, "setup", "skipped", ("f.py", 1, "Skipped: no cap")))
        collector.pytest_runtest_logreport(report(nodeid, "teardown", "passed"))
    assert decide_verdict(0, collector) == ("RIG ERROR", ["RIG ERROR: no test passed; a run without a passing test is never green"])


def test_exit_zero_with_three_passes_and_no_canary_is_rig_error_with_the_canary_line(tmp_path):
    files = {"test_%s.py" % n: PLAIN_PASS for n in "abc"}
    result = session(tmp_path, files)
    assert result["code"] == 0 and result["report"]["passed"] == 3
    assert result["verdict"] == "RIG ERROR"
    assert result["lines"][0].startswith("RIG ERROR: the canary was not detected in this run (not run)")


def test_one_passed_canary_and_two_skips_is_pass_and_the_skips_are_listed_with_reasons(tmp_path):
    files = {"test_a.py": CANARY_PASSES, "test_b.py": SKIP_TWO}
    result = session(tmp_path, files)
    assert (result["code"], result["verdict"], result["lines"]) == (0, "PASS", [])
    skipped = result["report"]["skipped"]
    assert [(s["nodeid"], s["reason"]) for s in skipped] == [
        ("test_b.py::test_one", "first reason"),
        ("test_b.py::test_two", "second reason"),
    ]


def test_tests_json_is_written_with_the_counts_and_the_skip_reasons(tmp_path, monkeypatch):
    monkeypatch.setenv("HIL_REPORTS_DIR", str(tmp_path / "reports"))
    collector = Collector()
    collector.pytest_runtest_logreport(report("t::a", "call", "passed"))
    collector.pytest_runtest_logreport(report("t::b", "setup", "skipped", ("f.py", 1, "Skipped: why")))
    entry.write_tests_report(collector)
    data = json.loads((tmp_path / "reports" / "tests.json").read_text(encoding="utf-8"))
    assert data["passed"] == 1 and data["failed"] == 0 and data["canary_passed"] is False
    assert data["skipped"] == [{"nodeid": "t::b", "reason": "why"}]


def test_one_warning_line_names_the_skip_count_under_github_actions_only():
    collector = Collector()
    for nodeid in ("t::a", "t::b"):
        collector.pytest_runtest_logreport(report(nodeid, "setup", "skipped", ("f.py", 1, "Skipped: why")))
    assert entry.warning_lines(collector, {"GITHUB_ACTIONS": "true"}) == [
        "::warning title=HIL skipped tests::2 test(s) skipped, see the job summary"
    ]
    assert entry.warning_lines(collector, {}) == []
    assert entry.warning_lines(collector, {"GITHUB_ACTIONS": "false"}) == []
    assert entry.warning_lines(Collector(), {"GITHUB_ACTIONS": "true"}) == []


# ---- a run cut by its session deadline is never green -------------------------------------

CUT_INI = INI + "timeout_method = signal\nsession_timeout = 1\n"
SLOW_THEN_SECOND = """
    import time

    def test_first_is_slow():
        time.sleep(2)

    def test_second_never_runs():
        raise AssertionError("must not run")
"""


def test_a_real_session_cut_by_session_timeout_is_rig_error_never_fail(tmp_path):
    result = session(tmp_path, {"test_a.py": SLOW_THEN_SECOND}, ini=CUT_INI)
    assert result["code"] == 1  # what pytest makes of the cut: today this read as FAIL
    assert result["verdict"] == "RIG ERROR"
    assert result["lines"] == ["RIG ERROR: run cut by the session deadline (session-timeout: 1.0 sec exceeded); 1 test(s) not run"]
    assert result["report"]["not_run"] == 1
    assert result["report"]["session_cut"] == "session-timeout: 1.0 sec exceeded"


def test_a_cut_after_a_failed_first_test_is_still_rig_error_and_the_failure_stays_listed(tmp_path):
    source = """
        import time

        def test_first_fails_slowly():
            time.sleep(2)
            assert False, "broke before the cut"

        def test_second_never_runs():
            raise AssertionError("must not run")
    """
    result = session(tmp_path, {"test_a.py": source}, ini=CUT_INI)
    assert result["verdict"] == "RIG ERROR"
    assert result["lines"] == ["RIG ERROR: run cut by the session deadline (session-timeout: 1.0 sec exceeded); 1 test(s) not run"]
    assert result["report"]["failed"] == 1
    assert result["report"]["failed_tests"] == ["test_a.py::test_first_fails_slowly"]


def test_a_rig_error_and_a_cut_print_both_lines_and_stay_rig_error(tmp_path):
    source = """
        import time
        from hil import RigError

        def test_first_is_down():
            time.sleep(2)
            raise RigError("the rig is down")

        def test_second_never_runs():
            pass
    """
    result = session(tmp_path, {"test_a.py": source}, ini=CUT_INI)
    assert result["verdict"] == "RIG ERROR"
    assert result["lines"][0] == "RIG ERROR: the rig is down"
    assert result["lines"][1].startswith("RIG ERROR: run cut by the session deadline (session-timeout: 1.0 sec exceeded)")


def test_other_stop_reasons_are_not_a_session_cut():
    collector = Collector()
    session_obj = SimpleNamespace(shouldfail="something else", items=[])
    collector.pytest_sessionfinish(session_obj, 1)
    assert collector.session_cut is None
    assert decide_verdict(1, collector) == ("FAIL", [])
    collector.pytest_sessionfinish(SimpleNamespace(shouldfail=False, items=[]), 1)
    assert collector.session_cut is None


# ---- a killed or interrupted run never leaves a stale verdict ------------------------------

@pytest.fixture
def run_env(tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "verdict.json").write_text(json.dumps({"schema": 1, "verdict": "PASS", "build_id": "old"}), encoding="utf-8")
    (reports / "tests.json").write_text(json.dumps({"passed": 99}), encoding="utf-8")
    monkeypatch.setenv("HIL_REPORTS_DIR", str(reports))
    monkeypatch.setenv("HIL_EXPECTED_COMMIT", "a" * 40)
    monkeypatch.setenv("GITHUB_ACTIONS", "false")
    monkeypatch.setenv("HIL_FW_DIR", str(tmp_path / "fw"))
    monkeypatch.setattr(entry.signal, "signal", lambda *args: None)  # the test process keeps its SIGTERM handler
    monkeypatch.setattr(entry, "load_rig", lambda: SimpleNamespace(duts={"A": object()}))
    monkeypatch.setattr(entry.manifest, "load_verified", lambda *args: SimpleNamespace(build_id="3.2+hil.new"))
    return reports


def stored(reports):
    return json.loads((reports / "verdict.json").read_text(encoding="utf-8"))


def test_the_provisional_verdict_is_on_disk_before_pytest_runs_and_prints_nothing(run_env, monkeypatch, capsys):
    seen = {}

    def stand_in(args, plugins):
        seen["verdict"] = stored(run_env)
        seen["out"] = capsys.readouterr().out
        seen["tests_json"] = (run_env / "tests.json").exists()
        plugins[0].pytest_runtest_logreport(report("t::canary", "call", "passed"))
        plugins[0]._canary.add("t::canary")
        return 0

    monkeypatch.setattr(entry.pytest, "main", stand_in)
    assert entry._run({}) == 0
    assert seen["verdict"]["verdict"] == "RIG ERROR" and seen["verdict"]["reason"] == "run did not complete"
    assert seen["verdict"]["commit"] == "a" * 40 and seen["verdict"]["build_id"] is None
    assert "HIL verdict" not in seen["out"]
    assert seen["tests_json"] is False  # the previous run's tests.json is gone too
    final = stored(run_env)
    assert final["verdict"] == "PASS" and "reason" not in final and final["build_id"] == "3.2+hil.new"
    assert "HIL verdict: PASS" in capsys.readouterr().out


def test_a_stand_in_pytest_that_raises_system_exit_leaves_the_provisional_verdict(run_env, monkeypatch, capsys):
    def stand_in(args, plugins):
        raise SystemExit(4)

    monkeypatch.setattr(entry.pytest, "main", stand_in)
    with pytest.raises(SystemExit):
        entry._run({})
    assert stored(run_env)["verdict"] == "RIG ERROR"
    assert stored(run_env)["reason"] == "run did not complete"
    assert "HIL verdict" not in capsys.readouterr().out


def test_the_provisional_verdict_exists_before_the_rig_is_loaded(run_env, monkeypatch):
    def killed(*args):
        raise SystemExit(15)

    monkeypatch.setattr(entry, "load_rig", killed)
    with pytest.raises(SystemExit):
        entry._run({})
    assert stored(run_env)["verdict"] == "RIG ERROR" and stored(run_env)["reason"] == "run did not complete"


def test_run_prints_the_rule_lines_and_the_warning_and_writes_the_final_verdict(run_env, monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    def stand_in(args, plugins):
        plugins[0].pytest_runtest_logreport(report("t::a", "setup", "skipped", ("f.py", 1, "Skipped: why")))
        plugins[0].pytest_runtest_logreport(report("t::b", "call", "passed"))
        return 0

    monkeypatch.setattr(entry.pytest, "main", stand_in)
    assert entry._run({}) == 3
    lines = capsys.readouterr().out.splitlines()
    assert "::warning title=HIL skipped tests::1 test(s) skipped, see the job summary" in lines
    assert any(x.startswith("RIG ERROR: the canary was not detected in this run (not run)") for x in lines)
    assert lines[-1].startswith("HIL verdict: RIG ERROR")
    assert stored(run_env)["verdict"] == "RIG ERROR" and "reason" not in stored(run_env)
    assert json.loads((run_env / "tests.json").read_text(encoding="utf-8"))["skipped"] == [{"nodeid": "t::a", "reason": "why"}]


def test_rig_errors_are_recorded_with_node_id_class_name_and_message_for_the_summary(tmp_path, monkeypatch):
    from hil import RigError
    from hil.budget import ResetBudgetExhausted, SafeModeError

    monkeypatch.setenv("HIL_REPORTS_DIR", str(tmp_path))
    collector = Collector()
    item = SimpleNamespace(nodeid="tests/rig/test_x.py::test_a", get_closest_marker=lambda name: None)
    for exc in (SafeModeError("in safe mode"), ResetBudgetExhausted("8/8"), RigError("plain"), ValueError("not a rig error")):
        collector.pytest_runtest_makereport(item, SimpleNamespace(excinfo=SimpleNamespace(value=exc)))
    entry.write_tests_report(collector)
    records = json.loads((tmp_path / "rig-errors.json").read_text(encoding="utf-8"))
    assert records == [
        {"nodeid": "tests/rig/test_x.py::test_a", "kind": "SafeModeError", "message": "in safe mode"},
        {"nodeid": "tests/rig/test_x.py::test_a", "kind": "ResetBudgetExhausted", "message": "8/8"},
        {"nodeid": "tests/rig/test_x.py::test_a", "kind": "RigError", "message": "plain"},
    ]


def test_a_run_with_no_rig_error_writes_an_empty_list(tmp_path, monkeypatch):
    monkeypatch.setenv("HIL_REPORTS_DIR", str(tmp_path))
    entry.write_tests_report(Collector())
    assert json.loads((tmp_path / "rig-errors.json").read_text(encoding="utf-8")) == []


def test_a_run_that_fails_before_any_test_clears_the_last_runs_files_and_records_the_error(tmp_path, monkeypatch):
    from hil import RigError

    monkeypatch.setenv("HIL_REPORTS_DIR", str(tmp_path))
    monkeypatch.setenv("HIL_EXPECTED_COMMIT", "a" * 40)
    stale = [
        "tests.json", "timings.json", "canary-dut-a.json", "budget-dut-a.json", "flash-dut-a.json",
        "raw/uart-dut-a.log", "raw/uart-dut-a.marks.json", "raw/api-dut-a.log", "raw/junit.xml", "raw/summary.md",
    ]
    for name in stale:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("from an earlier run", encoding="utf-8")

    def refuse():
        raise RigError("manifest: schema must be 2")

    monkeypatch.setattr(entry, "load_rig", refuse)
    assert entry._run({}) == 3
    assert [name for name in stale if (tmp_path / name).exists()] == []
    assert json.loads((tmp_path / "rig-errors.json").read_text(encoding="utf-8")) == [
        {"nodeid": None, "kind": "RigError", "message": "manifest: schema must be 2"}
    ]
    assert json.loads((tmp_path / "verdict.json").read_text(encoding="utf-8"))["verdict"] == "RIG ERROR"
