"""The job summary of a run (CI-05): what ran, what each test did, what the canary said, which image DUT A ends on.

render() is pure: it reads the report files under reports_dir and the firmware manifest (a dict, or None)
and returns Markdown. The verdict heading comes from reports/verdict.json and nothing else, so the summary
can never show PASS that the verdict file does not state. write() masks the text with the rig's literals
before it is written to reports/raw/summary.md (which the redaction copies into the uploadable tree) and
appended to $GITHUB_STEP_SUMMARY.
"""

import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path

from . import redact

BASELINE_LINE = "Baseline: commit image over serial (no release baseline in this run)"
VERDICTS = ("PASS", "FAIL", "RIG ERROR", "INTERRUPTED")
NOT_RECORDED = "not recorded"


def _read_json(path):
    """The parsed JSON file, or None when it is missing or unreadable."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def _junit_cases(path):
    """[(key, result, seconds, message)] in execution order from a JUnit file, or None when it is missing."""
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return None
    cases = []
    for case in root.iter("testcase"):
        key = "%s::%s" % (case.get("classname", ""), case.get("name", ""))
        result, message = "passed", ""
        for tag, label in (("failure", "failed"), ("error", "error"), ("skipped", "skipped")):
            child = case.find(tag)
            if child is not None:
                result, message = label, child.get("message", "")
                break
        try:
            seconds = float(case.get("time", "0"))
        except ValueError:
            seconds = 0.0
        cases.append((key, result, seconds, message))
    return cases


def _head(reports, manifest):
    verdict = _read_json(reports / "verdict.json")
    value = verdict.get("verdict") if isinstance(verdict, dict) else None
    value = value if value in VERDICTS else "UNKNOWN"
    lines = ["## HIL run: %s" % value, ""]
    commit = (verdict or {}).get("commit") if isinstance(verdict, dict) else None
    commit = commit or (manifest or {}).get("commit") or ""
    version = (manifest or {}).get("esphome_version") or NOT_RECORDED
    lines.append(
        "Commit `%s` | ESPHome %s | %s" % (str(commit)[:12] if commit else "unknown", version, BASELINE_LINE)
    )
    reason = verdict.get("reason") if isinstance(verdict, dict) else None
    if reason:
        lines.append("")
        lines.append("Reason: %s" % reason)
    return lines


def _dut_heading(manifest):
    images = (manifest or {}).get("images")
    first = next((i for i in images if isinstance(i, dict) and i.get("role") == "commit"), None) if isinstance(images, list) else None
    if first is None:
        return "### DUT A"
    return "### DUT A (Rev %s, %s)" % (first.get("rev", "?"), first.get("chip", "?"))


def _dut_table(reports):
    cases = _junit_cases(reports / "raw" / "junit.xml")
    if cases is None:
        return ["junit.xml: %s" % NOT_RECORDED]
    lines = ["| Test | Result | Duration |", "|---|---|---|"]
    for key, result, seconds, _message in cases:
        lines.append("| %s | %s | %.1f s |" % (_cell(key), result, seconds))
    return lines


def _canary_line(reports):
    canary = _read_json(reports / "canary-dut-a.json")
    if not isinstance(canary, dict):
        return "**Canary:** not run (%s)" % NOT_RECORDED
    if canary.get("detected") is True:
        return "**Canary:** detected (%s)" % canary.get("text", "swap")
    return "**Canary:** NOT detected: %s" % (canary.get("text") or "no text recorded")


def _final_image_line(reports):
    final = _read_json(reports / "final-image.json")
    if not isinstance(final, dict):
        return "**Final image:** %s" % NOT_RECORDED
    state = "confirmed" if final.get("confirmed") is True else "NOT confirmed"
    return "**Final image:** %s (%s), %s" % (final.get("image", "unknown"), final.get("version") or "unknown version", state)


def render(reports_dir, manifest):
    """The job summary as Markdown. Pure: reads files, writes nothing, never raises for a missing report."""
    reports = Path(reports_dir)
    lines = _head(reports, manifest)
    lines += ["", _dut_heading(manifest), ""]
    lines += _dut_table(reports)
    lines += ["", _canary_line(reports), "", _final_image_line(reports)]
    return "\n".join(lines) + "\n"


def write(reports_dir, manifest, literals):
    """Render, mask with the rig's literals, write reports/raw/summary.md and append to $GITHUB_STEP_SUMMARY.

    `literals` must be the rig's mask literals: without them the text is not masked, so None is refused.
    Returns the masked text.
    """
    if literals is None:
        raise ValueError("summary.write needs the rig's mask literals")
    text = redact.redact(render(reports_dir, manifest), literals)
    raw = Path(reports_dir) / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "summary.md").write_text(text, encoding="utf-8")
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as handle:
            handle.write(text)
    return text
