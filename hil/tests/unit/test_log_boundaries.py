"""START, END and SKIP boundary lines of tests/rig/conftest.py (HARN-08), in a real pytest subprocess.

A throwaway rootdir holds a copy of the rig conftest, fake `tap_a` and `dut_link` fixtures that register
two recording sinks, and a few tests. The sinks print every boundary line they are given, which shows
the order, the node ids, the outcomes and that a test without any output still gets both lines.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

from test_capability_hooks import RIG

PROJECT = Path(__file__).resolve().parents[2]
CONFTEST = PROJECT / "tests" / "rig" / "conftest.py"

FAKES = '''
import os

import pytest

import conftest


class Sink:
    def __init__(self, name):
        self.name = name

    def boundary(self, text):
        with open(os.environ["EVENTS"], "a", encoding="utf-8") as handle:
            handle.write("%s|%s\\n" % (self.name, text))

    def mark(self, name):  # the crash_mark fixture marks the tap at each test's start
        pass


@pytest.fixture(scope="session", autouse=True)
def supervisor():
    return None


@pytest.fixture(scope="session", autouse=True)
def tap_a():
    sink = Sink("uart")
    conftest.add_log_sink(sink)
    yield sink
    conftest.remove_log_sink(sink)


@pytest.fixture(scope="session", autouse=True)
def dut_link():
    sink = Sink("api")
    conftest.add_log_sink(sink)
    yield sink
    conftest.remove_log_sink(sink)
'''

TESTS = '''

def test_quiet():
    pass


def test_loud():
    print("some output")


def test_broken():
    assert False, "boom"


def test_skipped_inside():
    pytest.skip("not today")
'''


def run(tmp_path, tests=TESTS, capabilities=None, module="test_00_contract.py"):
    (tmp_path / "conftest.py").write_text(CONFTEST.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\nmarkers =\n    requires(*capabilities): x\n    image(before=None, after=None): x\n", encoding="utf-8"
    )
    (tmp_path / module).write_text(FAKES + tests, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("HIL_", "GITHUB_"))}
    env["PYTHONPATH"] = str(PROJECT)
    events = tmp_path / "events.txt"
    events.write_text("", encoding="utf-8")
    env["EVENTS"] = str(events)
    if capabilities is not None:
        rig = tmp_path / "rig.toml"
        rig.write_text(RIG % ("b" * 64, capabilities), encoding="utf-8")
        env["HIL_RIG_CONFIG"] = str(rig)
        env["HIL_SUPERVISOR_KEY"] = "sv-key-0123456789"
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-s", "-q"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60,
    )
    return proc, events.read_text(encoding="utf-8").splitlines()


def sink_lines(events, sink):
    return [line.split("|", 1)[1] for line in events if line.startswith(sink + "|")]


def test_every_executed_test_has_a_start_and_an_end_line_in_both_logs_in_execution_order(tmp_path):
    proc, events = run(tmp_path)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    for sink in ("uart", "api"):
        kinds = [(line.split()[0], line.split()[1]) for line in sink_lines(events, sink)]
        assert kinds == [
            ("START", "test_00_contract.py::test_quiet"), ("END", "test_00_contract.py::test_quiet"),
            ("START", "test_00_contract.py::test_loud"), ("END", "test_00_contract.py::test_loud"),
            ("START", "test_00_contract.py::test_broken"), ("END", "test_00_contract.py::test_broken"),
            ("START", "test_00_contract.py::test_skipped_inside"), ("END", "test_00_contract.py::test_skipped_inside"),
        ]


def test_a_tests_end_line_precedes_the_next_tests_start_line_and_both_sinks_see_the_same_lines(tmp_path):
    _proc, events = run(tmp_path)
    assert sink_lines(events, "uart") == sink_lines(events, "api")
    text = "\n".join(sink_lines(events, "uart"))
    assert text.index("END test_00_contract.py::test_quiet") < text.index("START test_00_contract.py::test_loud")
    starts = [line for line in sink_lines(events, "uart") if line.startswith("START ")]
    assert len(starts) == len(set(starts)) == 4


def test_a_test_without_any_output_still_gets_both_lines(tmp_path):
    _proc, events = run(tmp_path, tests="def test_quiet():\n    pass\n")
    for sink in ("uart", "api"):
        lines = sink_lines(events, sink)
        assert len(lines) == 2
        assert lines[0].startswith("START test_00_contract.py::test_quiet t=")
        assert lines[1].startswith("END test_00_contract.py::test_quiet passed t=")


def test_lines_carry_the_node_id_the_outcome_and_non_decreasing_seconds_since_session_start(tmp_path):
    _proc, events = run(tmp_path)
    lines = sink_lines(events, "uart")
    pattern = re.compile(r"^(START|END) (\S+?)(?: (passed|failed|skipped|error))? t=(\d+\.\d)$")
    seconds, outcomes = [], {}
    for line in lines:
        found = pattern.match(line)
        assert found, line
        seconds.append(float(found.group(4)))
        if found.group(1) == "END":
            outcomes[found.group(2).split("::")[1]] = found.group(3)
    assert seconds == sorted(seconds) and seconds[0] < 5
    assert outcomes == {"test_quiet": "passed", "test_loud": "passed", "test_broken": "failed", "test_skipped_inside": "skipped"}


def test_a_capability_skip_writes_a_skip_line_to_every_log_and_no_start_or_end(tmp_path):
    source = (
        "@pytest.mark.requires('hdc1080')\n"
        "def test_gated():\n    assert False, 'must not run'\n\n"
        "def test_plain():\n    pass\n"
    )
    proc, events = run(tmp_path, tests=source, capabilities='["usr1"]')
    assert proc.returncode == 0, proc.stdout + proc.stderr
    for sink in ("uart", "api"):
        lines = sink_lines(events, sink)
        assert lines[0] == "SKIP test_00_contract.py::test_gated: DUT A (rig.toml) lacks capability: hdc1080"
        assert [ln.split()[0] for ln in lines] == ["SKIP", "START", "END"]
        assert not any("test_gated" in ln for ln in lines[1:])


def test_a_skip_after_the_sinks_exist_is_written_directly_in_order(tmp_path):
    source = (
        "def test_first():\n    pass\n\n"
        "@pytest.mark.requires('hdc1080')\n"
        "def test_gated():\n    assert False\n\n"
        "def test_last():\n    pass\n"
    )
    _proc, events = run(tmp_path, tests=source, capabilities='["usr1"]')
    words = [ln.split()[0] + ":" + ln.split()[1].split("::")[1].rstrip(":") for ln in sink_lines(events, "api")]
    assert words == ["START:test_first", "END:test_first", "SKIP:test_gated", "START:test_last", "END:test_last"]
