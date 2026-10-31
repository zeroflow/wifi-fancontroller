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

from . import RigError, config, contract, manifest, nvs, redact, teardown
from .dut import Dut
from .flasher import Flasher
from .supervisor import Supervisor

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
    stale = reports / "dut-a.json"
    if stale.exists():
        stale.unlink()
    try:
        rig = load_rig()
        holder["rig"] = rig
        verified = manifest.load_verified(config.firmware_dir(), commit, rig.duts["A"])
        build_id = verified.build_id
    except RigError as exc:
        print("RIG ERROR: %s" % exc)
        return write_verdict("RIG ERROR", commit, build_id)

    signal.signal(signal.SIGTERM, _terminate)
    collector = Collector()
    try:
        code = pytest.main(
            # Timeouts come from pyproject.toml (timeout, timeout_method = signal, session_timeout).
            ["-c", str(PYPROJECT), str(TEST_DIR), "-s"],
            plugins=[collector],
        )
    except KeyboardInterrupt:
        code = 2
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
    finally:
        if supervisor is not None:
            supervisor.close()
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
