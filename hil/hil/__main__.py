"""python -m hil run: verify the manifest, run the rig tests, write the verdict.

Exit codes: 0 PASS, 1 FAIL, 2 INTERRUPTED, 3 RIG ERROR (rig or tooling fault).
"""

import argparse
import json
import os
import shutil
import signal
import sys
import time
from pathlib import Path

import pytest

from . import RigError, config, contract, manifest, nvs, redact, summary, teardown
from .dut import Dut
from .flasher import Flasher
from .supervisor import Supervisor

EXIT = {"PASS": 0, "FAIL": 1, "INTERRUPTED": 2, "RIG ERROR": 3}
PROVISIONAL_REASON = "run did not complete"
TEST_DIR = Path(__file__).resolve().parent.parent / "tests" / "rig"
PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


class Collector:
    """pytest plugin: every RigError, and what each test did (passed, failed, skipped and why).

    The run's verdict is decided from these facts by decide_verdict, never from pytest's
    exit code alone: exit 0 also means "everything was skipped" or "the canary never ran".
    """

    def __init__(self):
        self.rig_errors = []
        self.rig_error_records = []  # {"nodeid", "kind", "message"} for reports/rig-errors.json
        self.skipped = []  # {"nodeid", "reason"} in the order pytest reported them
        self.collected = 0
        self.session_cut = None  # pytest's session.shouldfail text when pytest-timeout's session deadline ended the run
        self.events = []  # (kind, nodeid, when, first_line) in pytest's report order; kind is "rig" or "fail" (D-46)
        self._canary = set()
        self._call_passed = set()
        self._failed = set()
        self._finished = set()  # tests whose whole protocol (setup, call, teardown) was reported

    def pytest_runtest_makereport(self, item, call):
        value = call.excinfo.value if call.excinfo is not None else None
        if isinstance(value, RigError):
            self.rig_errors.append(str(value))
            self.rig_error_records.append(rig_error_record(item.nodeid, value))
            self.events.append(("rig", item.nodeid, getattr(call, "when", None), first_line(value)))
        elif value is not None and not isinstance(value, NOT_A_FAILURE):
            self.events.append(("fail", item.nodeid, getattr(call, "when", None), first_line(value)))
        if item.get_closest_marker("canary") is not None:
            self._canary.add(item.nodeid)

    def pytest_collection_finish(self, session):
        self.collected = len(session.items)

    def pytest_sessionfinish(self, session, exitstatus):
        reason = getattr(session, "shouldfail", None)
        if isinstance(reason, str) and reason.startswith("session-timeout"):
            self.session_cut = reason

    def pytest_runtest_logreport(self, report):
        if report.when == "teardown":
            self._finished.add(report.nodeid)
        if report.failed:
            self._failed.add(report.nodeid)
        elif report.skipped and not hasattr(report, "wasxfail"):
            self.skipped.append({"nodeid": report.nodeid, "reason": skip_reason(report)})
        elif report.passed and report.when == "call":
            self._call_passed.add(report.nodeid)

    def first_failure(self):
        """The first recorded event (a firmware or test failure, or a RigError), or None."""
        return self.events[0] if self.events else None

    @property
    def passed(self):
        """Tests whose call phase passed and in which no phase failed."""
        return len(self._call_passed - self._failed)

    @property
    def failed(self):
        return len(self._failed)

    @property
    def not_run(self):
        """Collected tests whose protocol never finished (the run was cut before them)."""
        return max(self.collected - len(self._finished), 0)

    @property
    def canary_passed(self):
        return bool((self._canary & self._call_passed) - self._failed)

    def canary_state(self):
        """Why no canary passed: the skip reason of the canary test, or 'not run'."""
        reasons = [s["reason"] for s in self.skipped if s["nodeid"] in self._canary]
        return "skipped: " + "; ".join(reasons) if reasons else "not run"

    def report(self):
        return {
            "passed": self.passed,
            "failed": self.failed,
            "failed_tests": sorted(self._failed),
            "skipped": list(self.skipped),
            "canary_passed": self.canary_passed,
            "not_run": self.not_run,
            "session_cut": self.session_cut,
        }

    def cut_line(self):
        return "RIG ERROR: run cut by the session deadline (%s); %d test(s) not run" % (self.session_cut, self.not_run)


# Not failures: a skip, an operator interrupt and pytest.exit() end a phase without saying anything about the firmware.
NOT_A_FAILURE = (pytest.skip.Exception, KeyboardInterrupt, pytest.exit.Exception)


def first_line(value):
    """The first non-empty line of an exception's text, as summary._first_line cuts it (MESSAGE_CHARS)."""
    return summary._first_line(value)


def rig_error_record(nodeid, exc):
    """One entry of reports/rig-errors.json: the test, the exception class name and its message."""
    return {"nodeid": nodeid, "kind": type(exc).__name__, "message": str(exc)}


def skip_reason(report):
    """The reason text of a skipped report (the third element of its longrepr tuple)."""
    longrepr = report.longrepr
    text = longrepr[2] if isinstance(longrepr, tuple) and len(longrepr) == 3 else str(longrepr or "")
    return text.removeprefix("Skipped: ")


NO_PASS_LINE = "RIG ERROR: no test passed; a run without a passing test is never green"


def decide_verdict(code, collector):
    """(verdict, lines to print) from pytest's exit code and what the Collector saw.

    pytest's exit 0 also means "everything was skipped" and "the canary never ran", and its
    exit 1 also means "pytest-timeout's session deadline stopped the run", so none of them
    is taken at face value. A green run contains at least one passed test and a passed
    canary detection (HARN-02, D-31, QC-06); a run cut by the session deadline is RIG ERROR
    whatever ran before the cut.

    Otherwise the first recorded failure class decides (D-46, 03-02 Task 1): a firmware or test
    failure before any rig error is FAIL and later rig errors are only listed; a rig error before
    any failure is RIG ERROR even when failures follow, which stay listed in JUnit and the summary.
    """
    if code == 0:
        if collector.passed == 0:
            return "RIG ERROR", [NO_PASS_LINE]
        if not collector.canary_passed:
            return "RIG ERROR", [
                "RIG ERROR: the canary was not detected in this run (%s); a run without canary detection is never green"
                % collector.canary_state()
            ]
        return "PASS", []
    if collector.session_cut is not None:
        lines = ["RIG ERROR: %s" % message for message in collector.rig_errors]
        lines.append(collector.cut_line())
        return "RIG ERROR", lines
    first = collector.first_failure()
    if first is not None and first[0] == "fail":
        # D-46: a failure recorded first is never relabelled; every later rig error stays listed.
        return "FAIL", ["RIG ERROR (after the first failure): %s" % message for message in collector.rig_errors]
    if collector.rig_errors:
        # Decision of 03-02 Task 1 (RESEARCH A8, first-class-wins): a rig error first makes the run a
        # RIG ERROR even when failures follow; they stay listed in JUnit and the summary.
        return "RIG ERROR", ["RIG ERROR: %s" % message for message in collector.rig_errors]
    if code == 1:
        return "FAIL", []
    if code == 2:
        return "INTERRUPTED", []
    return "RIG ERROR", ["RIG ERROR: pytest ended with exit code %d" % code]


def verdict_annotation(verdict, lines, collector, build_id, env=None):
    """The one GitHub Actions annotation line of the verdict (D-45); none outside Actions.

    Messages are one line, at most summary.MESSAGE_CHARS characters, and carry only a test node id
    and the first line of an assertion or rig message (names, never values).
    """
    env = os.environ if env is None else env
    if env.get("GITHUB_ACTIONS") != "true":
        return []
    if verdict == "PASS":
        return ["::notice title=HIL PASS::DUT A passed on %s" % build_id]
    if verdict == "FAIL":
        failure = next((e for e in collector.events if e[0] == "fail"), None)
        text = "%s: %s" % (failure[1], first_line(failure[3])) if failure else "a test failed"
        return ["::error title=HIL FAIL::%s" % first_line(text)]
    if verdict == "INTERRUPTED":
        return ["::error title=HIL INTERRUPTED::run interrupted"]
    cause = lines[0].removeprefix("RIG ERROR: ") if lines else "rig error"
    return ["::error title=RIG ERROR::%s" % first_line(cause)]


def warning_lines(collector, env=None):
    """One GitHub Actions warning naming the skip count; skips never hide in a green run."""
    env = os.environ if env is None else env
    if env.get("GITHUB_ACTIONS") != "true" or not collector.skipped:
        return []
    return ["::warning title=HIL skipped tests::%d test(s) skipped, see the job summary" % len(collector.skipped)]


def write_rig_errors(records):
    """reports/rig-errors.json: every RigError of the run (the summary shows SAFE MODE, RESET BUDGET, RIG ERROR rows)."""
    reports = config.reports_dir()
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "rig-errors.json").write_text(json.dumps(records, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_tests_report(collector):
    reports = config.reports_dir()
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "tests.json").write_text(json.dumps(collector.report(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_rig_errors(collector.rig_error_records)


def _terminate(_signum, _frame):
    raise KeyboardInterrupt


def write_verdict(verdict, commit, build_id, reason=None, announce=True):
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
    if reason:
        data["reason"] = reason
    (reports / "verdict.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if announce:
        print("HIL verdict: %s build_id=%s" % (verdict, build_id))
    return EXIT[verdict]


def load_rig():
    """config.load, then the GitHub log masks before anything else is printed."""
    rig = config.load()
    config.emit_masks(rig)
    return rig


NO_CONFIG_REPORTS = ("verdict.json", "final-image.json")


def redact_reports(rig):
    """reports/raw + reports/*.json -> reports/redacted, the only thing a job may upload.

    Fails closed: if redaction breaks, the redacted directory is removed, not left half done.
    Without a loaded config there are no literals to mask, so only the reports this tool
    writes without rig values (verdict, final image) are added; a tree an earlier step
    redacted with the full literal set is kept, and nothing else is copied.
    """
    reports = config.reports_dir()
    try:
        if rig is not None:
            redact.redact_tree(reports / "raw", reports / "redacted", config.mask_literals(rig))
        else:
            redact.redact_tree(reports / "raw", reports / "redacted", [], include_raw=False,
                               json_names=NO_CONFIG_REPORTS, keep_existing=True)
    except Exception as exc:  # noqa: BLE001 - never let a redaction fault leave unredacted files behind
        shutil.rmtree(reports / "redacted", ignore_errors=True)
        print("RIG ERROR: redaction failed (%s); nothing will be uploaded" % type(exc).__name__)


def run():
    holder = {}
    try:
        return _run(holder)
    finally:
        redact_reports(holder.get("rig"))


def _run(holder):
    commit = config.expected_commit()
    build_id = None
    reports = config.reports_dir()
    reports.mkdir(parents=True, exist_ok=True)
    # Nothing of an earlier run may be uploaded or summarised as this run's: reports, logs, JUnit, summary.
    for name in (
        "dut-a.json",
        "tests.json",
        "rig-errors.json",
        "timings.json",
        "budget-dut-a.json",
        "flash-dut-a.json",
        "ota-dut-a.json",
        "qc-fans-dut-a.json",
        "canary-dut-a.json",
        "raw/uart-dut-a.log",
        "raw/uart-dut-a.marks.json",
        "raw/api-dut-a.log",
        "raw/junit.xml",
        "raw/summary.md",
    ):
        stale = reports / name
        if stale.exists():
            stale.unlink()
    # A run that is killed from here on (step ceiling, signal) leaves this, never PASS or an
    # earlier run's verdict; the final write_verdict replaces it. It prints nothing.
    write_verdict("RIG ERROR", commit, None, reason=PROVISIONAL_REASON, announce=False)
    try:
        rig = load_rig()
        holder["rig"] = rig
        verified = manifest.load_verified(config.firmware_dir(), commit, rig.duts["A"])
        build_id = verified.build_id
    except RigError as exc:
        print("RIG ERROR: %s" % exc)
        for line in verdict_annotation("RIG ERROR", ["RIG ERROR: %s" % exc], Collector(), build_id):
            print(line)
        write_rig_errors([rig_error_record(None, exc)])
        return write_verdict("RIG ERROR", commit, build_id)

    signal.signal(signal.SIGTERM, _terminate)
    collector = Collector()
    try:
        code = pytest.main(
            # Timeouts come from pyproject.toml (timeout, timeout_method = signal, session_timeout).
            # JUnit (xunit2) goes under reports/raw, so the redaction copies a masked version (CI-06).
            [
                "-c", str(PYPROJECT), str(TEST_DIR), "-s",
                "--junitxml=%s" % (reports / "raw" / "junit.xml"),
                "-o", "junit_family=xunit2",
            ],
            plugins=[collector],
        )
    except KeyboardInterrupt:
        code = 2
    code = int(code)
    write_tests_report(collector)
    verdict, lines = decide_verdict(code, collector)
    for line in [*warning_lines(collector), *lines, *verdict_annotation(verdict, lines, collector, build_id)]:
        print(line)
    return write_verdict(verdict, commit, build_id)


def _rig_dut(rig):
    """Connected supervisor plus the Dut A facade. The caller closes the supervisor."""
    cfg = rig.duts["A"]
    supervisor = Supervisor(rig.supervisor_host, rig.supervisor_key)
    try:
        supervisor.connect()
    except BaseException:
        supervisor.close()
        raise
    flasher = Flasher(rig.supervisor_host, contract.BRIDGE_PORT["A"], cfg.chip)
    return supervisor, Dut("A", cfg, supervisor, flasher)


def firmware_manifest_dict():
    """manifest.json of HIL_FW_DIR as a dict for the summary's display fields, or None (it was verified by `hil run`)."""
    try:
        data = json.loads((Path(os.environ.get("HIL_FW_DIR", "")) / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_summary(rig, reports):
    """Render the job summary after the final image is known; it never changes the exit code.

    Without a loaded config there are no literals to mask with, so no summary is written (the
    redaction would not be complete).
    """
    if rig is None:
        return
    try:
        summary.write(reports, firmware_manifest_dict(), config.mask_literals(rig))
    except Exception as exc:  # noqa: BLE001 - a summary fault must not hide the teardown result
        print("RIG ERROR: job summary not written (%s)" % type(exc).__name__)


def cmd_teardown():
    reports = config.reports_dir()
    state = teardown.new_state()
    supervisor = None
    rig = None
    try:
        rig = load_rig()
        supervisor, dut = _rig_dut(rig)
        return teardown.run_teardown(
            rig,
            os.environ.get("HIL_FW_DIR", ""),
            os.environ.get("HIL_JOB_STATUS", ""),
            reports,
            supervisor=supervisor,
            dut=dut,
            dut_key=rig.dut_api_key,
        )
    except RigError as exc:
        print("RIG ERROR: %s" % exc)
        state["steps"].append("teardown stopped: %s" % exc)
        teardown.write_final(reports, state)
        return 3
    except Exception as exc:  # noqa: BLE001 - a late non-RigError must still leave final-image.json behind
        print("RIG ERROR: teardown stopped unexpectedly (%s)" % type(exc).__name__)
        state["steps"].append("teardown stopped: %s" % type(exc).__name__)
        teardown.write_final(reports, state)
        return 3
    finally:
        if supervisor is not None:
            supervisor.close()
        write_summary(rig, reports)
        redact_reports(rig)


def cmd_known_good(args):
    """The v1.6.0 factory image alone (with the NVS backup unless --no-nvs). Used for on-site provisioning."""
    rig = load_rig()
    cfg = rig.duts["A"]
    teardown.verify_known_good(cfg, with_nvs=not args.no_nvs)
    supervisor, dut = _rig_dut(rig)
    try:
        supervisor.release_all()
        report = dut.flash_regions(teardown.known_good_regions(cfg, with_nvs=not args.no_nvs), report_name=teardown.TEARDOWN_FLASH_REPORT)
        print("known-good flash: %.1f s, %d attempt(s)" % (sum(report.durations_s), report.attempts))
        if args.no_confirm:
            return 0
        started = time.monotonic()
        info = dut.wait_api(noise_psk=teardown.known_good_psk(cfg, rig.dut_api_key))
        print("API answered %.1f s after reset, project_version %s" % (time.monotonic() - started, info.project_version))
        return 0
    finally:
        try:
            supervisor.release_all()
        finally:
            supervisor.close()


def cmd_status(args):
    """Project name, version and compile time. Never the device name: it carries the MAC suffix."""
    rig = load_rig()
    supervisor, dut = _rig_dut(rig)
    try:
        info = None
        for psk in (rig.dut_api_key, None):
            try:
                info = dut.probe(psk)
                break
            except Exception:  # noqa: BLE001 - wrong key or image without encryption: try the other mode
                continue
        if info is None:
            raise RigError("DUT A did not answer with the HIL key or without encryption")
    finally:
        supervisor.close()
    fields = (
        ("project_name", info.project_name),
        ("project_version", info.project_version),
        ("compilation_time", info.compilation_time),
    )
    for key, value in fields:
        print("%s=%s" % (key, value) if args.plain else "%-17s %s" % (key + ":", value))
    return 0


def detect_psk(dut, key):
    """The API mode DUT A answers in right now: the HIL key first, then plaintext (release image)."""
    for psk in (key, None):
        try:
            dut.probe(psk)
            return psk
        except Exception:  # noqa: BLE001 - wrong key or image without encryption: try the other mode
            continue
    raise RigError("DUT A did not answer with the HIL key or without encryption")


def cmd_nvs(args):
    rig = load_rig()
    supervisor, dut = _rig_dut(rig)
    try:
        supervisor.release_all()
        if args.nvs_command == "capture":
            digest = nvs.capture(dut, args.out, detect_psk(dut, rig.dut_api_key))
            size = Path(args.out).stat().st_size
            if args.plain:
                print("sha256=%s size=%d" % (digest, size))
            else:
                print("NVS backup written: %d bytes, sha256 %s" % (size, digest))
        else:
            nvs.restore(dut)
            print("NVS backup restored at %s" % rig.duts["A"].nvs_offset)
        return 0
    finally:
        try:
            supervisor.release_all()
        finally:
            supervisor.close()


def build_parser():
    parser = argparse.ArgumentParser(prog="python -m hil")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="verify the manifest, flash DUT A, check the build ID")
    sub.add_parser("teardown", help="release every line and leave DUT A on a confirmed image")
    known = sub.add_parser("known-good", help="flash the v1.6.0 factory image (plus NVS backup) to DUT A")
    known.add_argument("--dut", choices=["A"], required=True)
    known.add_argument("--no-nvs", action="store_true", help="write only the factory image")
    known.add_argument("--no-confirm", action="store_true", help="do not wait for the API afterwards")
    status = sub.add_parser("status", help="print project name, version and compile time of DUT A")
    status.add_argument("--dut", choices=["A"], required=True)
    status.add_argument("--plain", action="store_true", help="key=value lines")
    nvs_parser = sub.add_parser("nvs", help="capture or restore the NVS partition of DUT A")
    nvs_sub = nvs_parser.add_subparsers(dest="nvs_command", required=True)
    capture = nvs_sub.add_parser("capture", help="read the nvs partition into a file (mode 0600)")
    capture.add_argument("--dut", choices=["A"], required=True)
    capture.add_argument("--out", required=True)
    capture.add_argument("--plain", action="store_true", help="key=value output")
    restore = nvs_sub.add_parser("restore", help="write nvs_backup back at nvs_offset")
    restore.add_argument("--dut", choices=["A"], required=True)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "run":
        return run()
    try:
        if args.command == "teardown":
            return cmd_teardown()
        if args.command == "known-good":
            return cmd_known_good(args)
        if args.command == "status":
            return cmd_status(args)
        return cmd_nvs(args)
    except RigError as exc:
        print("RIG ERROR: %s" % exc)
        return 3


if __name__ == "__main__":
    sys.exit(main())
