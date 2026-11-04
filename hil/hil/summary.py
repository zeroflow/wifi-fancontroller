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

from . import config, redact

BASELINE_LINE = "Baseline: commit image over serial (no release baseline in this run)"
VERDICTS = ("PASS", "FAIL", "RIG ERROR", "INTERRUPTED")
NOT_RECORDED = "not recorded"
TIMINGS = "timings.json"
# Fixed row order of the Timings table (CI-05); an OTA's boot time follows its transfer.
TIMING_ORDER = ("flash", "boot", "ota_qc-auto", "ota_qc-auto_boot", "ota_canary", "ota_canary_boot", "ota_commit", "ota_commit_boot")
RIG_ERROR_LABELS = {"SafeModeError": "SAFE MODE", "ResetBudgetExhausted": "RESET BUDGET"}
MESSAGE_CHARS = 300


def record_timing(name, seconds):
    """Merge one timing (seconds, one decimal) into reports/timings.json; a second value for a name replaces the first.

    Timings are a report, never a reason to fail a run: an unwritable file is ignored, a corrupt one is started over.
    """
    path = config.reports_dir() / TIMINGS
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    data[name] = round(float(seconds), 1)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        pass


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


def _first_line(text):
    line = str(text).strip().splitlines()[0] if str(text).strip() else ""
    return line if len(line) <= MESSAGE_CHARS else line[: MESSAGE_CHARS - 3] + "..."


def _dut_table(reports):
    cases = _junit_cases(reports / "raw" / "junit.xml")
    if cases is None:
        return ["junit.xml: %s" % NOT_RECORDED]
    lines = ["| Test | Result | Duration |", "|---|---|---|"]
    for key, result, seconds, _message in cases:
        lines.append("| %s | %s | %.1f s |" % (_cell(key), result, seconds))
    bad = [(key, message) for key, result, _s, message in cases if result in ("failed", "error")]
    if bad:
        lines += ["", "### Failures", ""]
        lines += ["- %s: %s" % (key, _first_line(message) or "no message") for key, message in bad]
    return lines


def _canary_line(reports):
    canary = _read_json(reports / "canary-dut-a.json")
    if not isinstance(canary, dict):
        return "**Canary:** not run (%s)" % NOT_RECORDED
    if canary.get("detected") is True:
        return "**Canary:** detected (%s)" % canary.get("text", "swap")
    return "**Canary:** NOT detected: %s" % (canary.get("text") or "no text recorded")


def _images(manifest):
    images = (manifest or {}).get("images")
    if not isinstance(images, list) or not images:
        return ["Images: %s" % NOT_RECORDED]
    lines = ["| Role | Build ID | Final |", "|---|---|---|"]
    for image in images:
        if isinstance(image, dict):
            lines.append("| %s | %s | %s |" % (_cell(image.get("role", "?")), _cell(image.get("build_id", "?")), "yes" if image.get("final") is True else "no"))
    return lines


def _timings(reports):
    data = _read_json(reports / TIMINGS)
    if not isinstance(data, dict):
        return ["Timings: %s" % NOT_RECORDED]
    rows = [(name, data[name]) for name in TIMING_ORDER if isinstance(data.get(name), (int, float))]
    rows += [(name, data[name]) for name in sorted(data) if name not in TIMING_ORDER and isinstance(data[name], (int, float))]
    if not rows:
        return ["Timings: %s" % NOT_RECORDED]
    return ["| Step | Seconds |", "|---|---|"] + ["| %s | %.1f s |" % (_cell(name), value) for name, value in rows]


def _flash_and_ota(reports):
    lines = []
    flash = _read_json(reports / "flash-dut-a.json")
    if isinstance(flash, dict):
        attempts = flash.get("attempts", "?")
        retry = flash.get("retry_reason")
        lines.append(
            "Flash: %s attempt%s, %s%s"
            % (attempts, "" if attempts == 1 else "s", "verified" if flash.get("verified") else "NOT verified", " (retry: %s)" % retry if retry else "")
        )
    else:
        lines.append("Flash: %s" % NOT_RECORDED)
    ota = _read_json(reports / "ota-dut-a.json")
    if isinstance(ota, list) and ota:
        for entry in ota:
            if not isinstance(entry, dict):
                continue
            role = entry.get("role", "?")
            if entry.get("ok") is True:
                lines.append("OTA %s: ok" % role)
            else:
                lines.append("OTA %s: FAILED (%s)" % (role, entry.get("reason") or "no reason recorded"))
    else:
        lines.append("OTA: %s" % NOT_RECORDED)
    return lines


def _skipped(reports):
    tests = _read_json(reports / "tests.json")
    if not isinstance(tests, dict) or not isinstance(tests.get("skipped"), list):
        return ["Skipped: %s" % NOT_RECORDED]
    skipped = [s for s in tests["skipped"] if isinstance(s, dict)]
    if not skipped:
        return ["none"]
    return ["- %s: %s" % (s.get("nodeid", "?"), _first_line(s.get("reason", "")) or "no reason recorded") for s in skipped]


def _rig_conditions(reports):
    errors = _read_json(reports / "rig-errors.json")
    if not isinstance(errors, list):
        return ["Rig conditions: %s" % NOT_RECORDED]
    rows = []
    for entry in errors:
        if not isinstance(entry, dict):
            continue
        label = RIG_ERROR_LABELS.get(entry.get("kind"), "RIG ERROR")
        where = " (%s)" % entry["nodeid"] if entry.get("nodeid") else ""
        rows.append("- %s: %s%s" % (label, _first_line(entry.get("message", "")), where))
    return rows or ["none"]


def _allowlisted(reports):
    data = _read_json(reports / "allowlisted-errors.json")
    if not isinstance(data, dict) or not isinstance(data.get("lines"), list):
        return ["Allowlisted boot-log lines: %s" % NOT_RECORDED]
    lines = [str(line) for line in data["lines"]]
    return ["- WARNING %s" % _cell(line) for line in lines] or ["none"]


def _budget_line(reports):
    budget = _read_json(reports / "budget-dut-a.json")
    if not isinstance(budget, dict):
        return "Reset budget: %s" % NOT_RECORDED
    return "Reset budget: %s boots, streak %s/%s" % (budget.get("used", "?"), budget.get("streak", "?"), budget.get("limit", "?"))


def _final_image_line(reports):
    final = _read_json(reports / "final-image.json")
    if not isinstance(final, dict):
        return "**Final image:** %s" % NOT_RECORDED
    state = "confirmed" if final.get("confirmed") is True else "NOT confirmed"
    return "**Final image:** %s (%s), %s" % (final.get("image", "unknown"), final.get("version") or "unknown version", state)


def render(reports_dir, manifest):
    """The job summary as Markdown. Pure: reads files, writes nothing, never raises for a missing report.

    Order: verdict, commit/ESPHome/baseline line, DUT A table (JUnit order) and failures, Canary, Images, Timings,
    Flash and OTA, Skipped, Rig conditions, Reset budget, Final image.
    """
    reports = Path(reports_dir)
    lines = _head(reports, manifest)
    lines += ["", _dut_heading(manifest), ""] + _dut_table(reports)
    lines += ["", _canary_line(reports)]
    lines += ["", "### Images", ""] + _images(manifest)
    lines += ["", "### Timings", ""] + _timings(reports) + [""] + _flash_and_ota(reports)
    lines += ["", "### Skipped", ""] + _skipped(reports)
    lines += ["", "### Rig conditions", ""] + _rig_conditions(reports)
    lines += ["", "### Allowlisted boot-log lines", ""] + _allowlisted(reports)
    lines += ["", _budget_line(reports), "", _final_image_line(reports)]
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
