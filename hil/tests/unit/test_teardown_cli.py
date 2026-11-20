"""WR-06 reproduction: the real `python -m hil teardown` path in a subprocess (03-15, HARN-06, D-45).

A run whose verdict.json is PASS, a rig whose supervisor cannot be reached: the Teardown step is red,
so verdict.json, the summary heading and the annotation must all say RIG ERROR and name the cause.
"""

import base64
import os
import socket
import subprocess
import sys
from pathlib import Path

from hil import contract

from test_config import rig_toml

ROOT = Path(__file__).resolve().parents[2]
# Documentation-style 32-byte key; the real thing is never in a test.
TEST_KEY = base64.b64encode(bytes(range(1, 33))).decode("ascii")
MASK_PREFIX = "::add-mask::"
ANNOTATION = "::error title=RIG ERROR::teardown: supervisor unreachable"


def nothing_listens_on_the_api_port():
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", contract.API_PORT)) != 0


def test_teardown_that_cannot_reach_the_supervisor_ends_rig_error_through_the_real_cli(tmp_path):
    assert nothing_listens_on_the_api_port(), (
        "something listens on 127.0.0.1:%d here; stop it, this test needs the supervisor to be unreachable"
        % contract.API_PORT
    )
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "verdict.json").write_text('{"schema": 1, "verdict": "PASS", "build_id": "3.2+hil.aaaaaaaaaaaa"}\n')
    rig_file = tmp_path / "rig.toml"
    rig_file.write_text(rig_toml(sup_host="127.0.0.1"), encoding="utf-8")
    step_summary = tmp_path / "step-summary.md"
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "SYSTEMROOT")}
    env.update(
        PYTHONPATH=str(ROOT),
        HIL_RIG_CONFIG=str(rig_file),
        HIL_SUPERVISOR_KEY=TEST_KEY,
        HIL_REPORTS_DIR=str(reports),
        HIL_JOB_STATUS="success",
        GITHUB_ACTIONS="true",
        GITHUB_STEP_SUMMARY=str(step_summary),
    )
    done = subprocess.run(
        [sys.executable, "-m", "hil", "teardown"], cwd=ROOT, env=env, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, timeout=60,
    )
    out = done.stdout.splitlines()
    verdict = (reports / "verdict.json").read_text()
    head = (reports / "raw" / "summary.md").read_text().splitlines()[0] if (reports / "raw" / "summary.md").exists() else None
    step_head = step_summary.read_text().splitlines()[0] if step_summary.exists() and step_summary.read_text() else None
    annotation_lines = [line for line in out if line.startswith("::error title=RIG ERROR::")]
    print(
        "WR-06 observed: exit=%d verdict=%s summary=%r annotations=%d"
        % (done.returncode, '"verdict": "RIG ERROR"' in verdict and "RIG ERROR" or "PASS/other", head, len(annotation_lines))
    )
    assert done.returncode == 3, done.stdout
    assert '"verdict": "RIG ERROR"' in verdict
    assert '"reason": "teardown: supervisor unreachable"' in verdict
    assert head == "## HIL run: RIG ERROR"
    assert step_head == "## HIL run: RIG ERROR"
    assert annotation_lines == [ANNOTATION]
    assert all(TEST_KEY not in line for line in out if not line.startswith(MASK_PREFIX))
