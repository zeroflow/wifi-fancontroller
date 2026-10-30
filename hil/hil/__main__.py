"""python -m hil run: verify the manifest, run the rig tests, write the verdict.

Exit codes: 0 PASS, 1 FAIL, 2 INTERRUPTED, 3 RIG ERROR (rig or tooling fault).
"""

import argparse
import json
import signal
import sys
from pathlib import Path

import pytest

from . import RigError, config, manifest

EXIT = {"PASS": 0, "FAIL": 1, "INTERRUPTED": 2, "RIG ERROR": 3}
TEST_DIR = Path(__file__).resolve().parent.parent / "tests" / "rig"
PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


class Collector:
    """pytest plugin: remember every RigError, whichever phase raised it."""

    def __init__(self):
        self.rig_errors = []

    def pytest_runtest_makereport(self, item, call):
        if call.excinfo is not None and isinstance(call.excinfo.value, RigError):
            self.rig_errors.append(str(call.excinfo.value))


def _terminate(_signum, _frame):
    raise KeyboardInterrupt


def write_verdict(verdict, commit, build_id):
    reports = config.reports_dir()
    reports.mkdir(parents=True, exist_ok=True)
    reported = None
    dut_file = reports / "dut-a.json"
    if dut_file.is_file():
        try:
            reported = json.loads(dut_file.read_text(encoding="utf-8")).get("project_version")
        except (OSError, ValueError):
            reported = None
    data = {
        "schema": 1,
        "verdict": verdict,
        "commit": commit or None,
        "build_id": build_id,
        "reported_build_id": reported,
    }
    (reports / "verdict.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("HIL verdict: %s build_id=%s" % (verdict, build_id))
    return EXIT[verdict]


def run():
    commit = config.expected_commit()
    build_id = None
    reports = config.reports_dir()
    reports.mkdir(parents=True, exist_ok=True)
    stale = reports / "dut-a.json"
    if stale.exists():
        stale.unlink()
    try:
        rig = config.load()
        verified = manifest.load_verified(config.firmware_dir(), commit, rig.duts["A"])
        build_id = verified.build_id
    except RigError as exc:
        print("RIG ERROR: %s" % exc)
        return write_verdict("RIG ERROR", commit, build_id)

    signal.signal(signal.SIGTERM, _terminate)
    collector = Collector()
    code = pytest.main(
        # Timeouts come from pyproject.toml (timeout, timeout_method = signal, session_timeout).
        ["-c", str(PYPROJECT), str(TEST_DIR), "-s"],
        plugins=[collector],
    )
    code = int(code)
    if code == 0:
        verdict = "PASS"
    elif collector.rig_errors:
        verdict = "RIG ERROR"
        for message in collector.rig_errors:
            print("RIG ERROR: %s" % message)
    elif code == 1:
        verdict = "FAIL"
    elif code == 2:
        verdict = "INTERRUPTED"
    else:
        verdict = "RIG ERROR"
    return write_verdict(verdict, commit, build_id)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m hil")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="verify the manifest, flash DUT A, check the build ID")
    parser.parse_args(argv)
    return run()


if __name__ == "__main__":
    sys.exit(main())
