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

VERDICTS = ("PASS", "FAIL", "RIG ERROR", "INTERRUPTED")
NOT_RECORDED = "not recorded"
TIMINGS = "timings.json"
# Fixed row order of the Timings table (CI-05), in run order (D-36): the release baseline, the upgrade OTA and its
# mark, the serial restore, the OTA chain, the rollback tests (03-13: the armed OTA, the forced reset's time after
# it and the boot it brought back, the OTA back to commit and its mark), the broken OTA, the recovery flash. An
# OTA's boot time follows its transfer.
TIMING_ORDER = (
    "baseline_flash",
    "ota_baseline_commit",
    "ota_baseline_commit_boot",
    "soak_mark",
    "restore_flash",
    "restore_boot",
    "ota_qc-auto",
    "ota_qc-auto_boot",
    "ota_canary",
    "ota_canary_boot",
    "ota_rollback_fresh",
    "ota_rollback_fresh_boot",
    "rollback_reset",
    "rollback_boot",
    "ota_rollback_marked",
    "ota_rollback_marked_boot",
    "rollback_mark",
    "ota_broken",
    "flash",
    "boot",
)
BASELINE_REPORT = "baseline-dut-a.json"
UPGRADE_REPORT = "upgrade-dut-a.json"
GOLDEN_REPORT = "golden-dut-a.json"
ROLLBACK_STATES_REPORT = "rollback-states.json"  # rollback.STATES_REPORT (summary imports no harness module)
ROLLBACK_TEST_REPORT = "rollback-dut-a.json"  # rollback.TEST_REPORT
BASELINE_NOT_RUN = "Baseline: not run in this run"
UPGRADE_NOT_RUN = "Upgrade: not run in this run"
ENTITIES_NOT_CHECKED = "not checked in this run"
GATE_SOURCES = {"api": "API", "uart0": "UART0"}
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
    lines.append("Commit `%s` | ESPHome %s" % (str(commit)[:12] if commit else "unknown", version))
    lines += [""] + _baseline_lines(reports)
    lines += ["", _upgrade_line(reports)]
    reason = verdict.get("reason") if isinstance(verdict, dict) else None
    if reason:
        lines.append("")
        lines.append("Reason: %s" % reason)
    return lines


def _seconds_text(value):
    return "%.1f" % value if isinstance(value, (int, float)) and not isinstance(value, bool) else "?"


def _plural(count, word):
    return "%d %s%s" % (count, word, "" if count == 1 else "s")


def _baseline_lines(reports):
    """SC1, REG-01, D-37: the release the run started from (reports/baseline-dut-a.json, 03-10), plus the drift warning.

    `Baseline: release <tag> (<asset>, sha256 <12 hex>, <n> digests agree) + NVS replay captured with <nvs tag>`,
    followed by `WARNING: <drift warning>` when the dump's tag is not the baseline's; without a report (or one
    without a tag) `Baseline: not run in this run`.
    """
    data = _read_json(reports / BASELINE_REPORT)
    if not isinstance(data, dict) or not data.get("tag"):
        return [BASELINE_NOT_RUN]
    digests = data.get("digests_compared")
    count = len(digests) if isinstance(digests, list) else 0
    nvs = (
        "NVS replay captured with %s" % (data.get("nvs_release_tag") or "unknown tag")
        if data.get("nvs_replayed") is True
        else "no NVS replay"
    )
    line = "Baseline: release %s (%s, sha256 %s, %s agree) + %s" % (
        data["tag"],
        data.get("asset") or "unknown asset",
        str(data.get("sha256") or "?")[:12],
        _plural(count, "digest"),
        nvs,
    )
    lines = [_cell(line)]
    if data.get("drift_warning"):
        lines += ["", "WARNING: %s" % _cell(data["drift_warning"])]
    return lines


def _upgrade_line(reports):
    """SC1, REG-02: the release-to-commit OTA (reports/upgrade-dut-a.json, 03-11) with its timing, or not run.

    The soak part names the UART0 banners (0 for this leg), whether the API session dropped and the D-14 gate on
    the log it read (API or UART0).
    """
    data = _read_json(reports / UPGRADE_REPORT)
    if not isinstance(data, dict) or not data.get("tag"):
        return UPGRADE_NOT_RUN
    line = "Upgrade: %s -> %s by OTA, transfer %s s, boot %s s, marked valid after %s s, soak %s s" % (
        data["tag"],
        data.get("build_id") or "unknown build",
        _seconds_text(data.get("transfer_s")),
        _seconds_text(data.get("boot_s")),
        _seconds_text(data.get("mark_s")),
        _seconds_text(data.get("soak_s")),
    )
    banners = data.get("banners")
    if isinstance(banners, int) and not isinstance(banners, bool):
        errors = data.get("errors") if isinstance(data.get("errors"), list) else []
        source = GATE_SOURCES.get(data.get("gate_source"), "")
        log = ("%s boot log" % source) if source else "boot log"
        line += ": %s, %s, %s %s" % (
            _plural(banners, "UART0 banner"),
            "API session dropped" if data.get("api_session_dropped") is True else "no API drop",
            log,
            _plural(len(errors), "error") if errors else "clean",
        )
    return _cell(line)


PREFLIGHT_NOT_RUN = "Preflight: not run for this commit"


def _preflight(reports):
    """### Preflight from reports/preflight.json (HARN-05, HARN-10): every check, the heal, every warning.

    Shown only when preflight.json names the same commit as verdict.json (T-03-19): a preflight of an
    earlier commit, or none at all, reads "not run for this commit".
    """
    record = _read_json(reports / "preflight.json")
    verdict = _read_json(reports / "verdict.json")
    commit = verdict.get("commit") if isinstance(verdict, dict) else None
    if not isinstance(record, dict) or not commit or record.get("commit") != commit:
        return [PREFLIGHT_NOT_RUN]
    lines = ["| Check | Result |", "|---|---|"]
    for check in record.get("checks") or []:
        if not isinstance(check, dict):
            continue
        detail = check.get("detail") or ""
        if check.get("ok") is True:
            result = "ok (%s)" % detail if detail else "ok"
        else:
            result = detail or "failed"
        lines.append("| %s | %s |" % (_cell(check.get("name", "?")), _cell(_first_line(result))))
    heal = record.get("heal")
    if not isinstance(heal, dict):
        lines += ["", "Heal: no heal"]
    elif heal.get("ok") is True:
        version = " (%s)" % heal["version"] if heal.get("version") else ""
        lines += ["", "Heal: healed with %s%s" % (heal.get("source") or "unknown source", version)]
    else:
        lines += ["", "Heal: %s" % _first_line(heal.get("detail") or "not completed")]
    warnings = [str(w) for w in record.get("warnings") or []]
    lines += [""] + (["- WARNING %s" % _cell(w) for w in warnings] or ["Warnings: none"])
    return lines


WATCHDOG_NOT_RECORDED = "Supervisor watchdog: %s" % NOT_RECORDED


def _watchdog_line(reports):
    """Supervisor watchdog: none, or each DUT whose counter changed during the run (D-47), from reports/watchdog.json."""
    data = _read_json(reports / "watchdog.json")
    delta = data.get("delta") if isinstance(data, dict) else None
    if not isinstance(delta, dict) or not delta:
        return WATCHDOG_NOT_RECORDED
    start = data.get("start") if isinstance(data.get("start"), dict) else {}
    end = data.get("end") if isinstance(data.get("end"), dict) else {}
    parts, missing = [], []
    for dut_id in sorted(delta):
        value = delta[dut_id]
        label = "DUT %s" % dut_id
        if not isinstance(value, int) or isinstance(value, bool):
            missing.append(label)
        elif value > 0:
            parts.append("%s released %d line(s) during this run (WARNING)" % (label, value))
        elif value < 0:
            parts.append(
                "%s counter fell from %s to %s, the supervisor restarted during this run (WARNING)"
                % (label, start.get(dut_id, "?"), end.get(dut_id, "?"))
            )
    if missing:
        parts.append("%s (%s)" % (NOT_RECORDED, ", ".join(missing)))
    return "Supervisor watchdog: %s" % ("; ".join(parts) if parts else "none")


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


def _uptime_text(value):
    return "%.1f s" % value if isinstance(value, (int, float)) and not isinstance(value, bool) else "?"


def _rollback_states(reports):
    """### OTA rollback states (D-39, D-41) from reports/rollback-states.json, one row per OTA, and the rollback tests."""
    data = _read_json(reports / ROLLBACK_STATES_REPORT)
    if not isinstance(data, list):
        lines = [NOT_RECORDED]
    elif not data:
        lines = ["no OTA in this run"]
    else:
        lines = ["| OTA | Role | Rollback state | Source | Image state | Old image up |", "|---|---|---|---|---|---|"]
        for row in data:
            if not isinstance(row, dict):
                continue
            state = row.get("state") or "no line"
            lines.append(
                "| %s | %s | %s | %s | %s | %s |"
                % (
                    _cell(row.get("label") or "?"),
                    _cell(row.get("role") or "?"),
                    _cell(state),
                    _cell(row.get("source") or "?"),
                    _cell(row.get("image_state") or "-"),
                    _uptime_text(row.get("old_uptime_s")),
                )
            )
    tests = _read_json(reports / ROLLBACK_TEST_REPORT)
    if isinstance(tests, dict):
        fresh, marked = tests.get("fresh"), tests.get("marked")
        if isinstance(fresh, dict):
            text = "Rollback before the mark: %s (state %s, build after %s)" % (
                _cell(fresh.get("outcome") or "?"), _cell(fresh.get("state") or "no line"), _cell(fresh.get("build_after") or "?"),
            )
            if isinstance(fresh.get("reset_after_s"), (int, float)):
                text += ", forced EN reset %s after the OTA, OTA rollback detected line %s" % (
                    _uptime_text(fresh["reset_after_s"]), "seen" if fresh.get("rollback_line_seen") else "not seen",
                )
            lines += ["", text]
        if isinstance(marked, dict):
            lines += [
                "",
                "Reset after the mark: build after %s, marked valid after %s"
                % (_cell(marked.get("build_after") or "?"), _uptime_text(marked.get("mark_s"))),
            ]
    return lines


def _entity_list(reports):
    """### Entity list (REG-03, D-38) from reports/golden-dut-a.json: the match, or every removed and added entry."""
    data = _read_json(reports / GOLDEN_REPORT)
    if not isinstance(data, dict) or not isinstance(data.get("actual"), list):
        return [ENTITIES_NOT_CHECKED]
    if data.get("error"):
        return ["golden list not usable: %s" % _cell(_first_line(data["error"]))]
    actual = data["actual"]
    if not actual:
        return ["DUT A listed no entities"]

    def entries(key):
        found = data.get(key) if isinstance(data.get(key), list) else []
        return ["%s: %s" % (e.get("type", "?"), e.get("name", "?")) for e in found if isinstance(e, dict)]

    removed, added = entries("removed"), entries("added")
    if not removed and not added:
        return ["matches golden (%d entities)" % len(actual)]
    lines = ["- removed: %s" % _cell(e) for e in removed] + ["- added: %s" % _cell(e) for e in added]
    golden_file = data.get("golden_file") or "hil/golden/entities-<rev>.json"
    lines += [
        "",
        "If the change is intended, regenerate with `python -m hil golden from-run --report reports/%s --out %s` "
        "and commit it with the firmware change (D-38)." % (GOLDEN_REPORT, _cell(golden_file)),
    ]
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

    Order: verdict, commit/ESPHome line, Baseline line (and its drift warning), Upgrade line, Preflight,
    Supervisor watchdog, DUT A table (JUnit order) and failures, Canary, Images, Timings, Flash and OTA, OTA
    rollback states, Entity list, Skipped, Rig conditions, Reset budget, Final image.
    """
    reports = Path(reports_dir)
    lines = _head(reports, manifest)
    lines += ["", "### Preflight", ""] + _preflight(reports)
    lines += ["", _watchdog_line(reports)]
    lines += ["", _dut_heading(manifest), ""] + _dut_table(reports)
    lines += ["", _canary_line(reports)]
    lines += ["", "### Images", ""] + _images(manifest)
    lines += ["", "### Timings", ""] + _timings(reports) + [""] + _flash_and_ota(reports)
    lines += ["", "### OTA rollback states", ""] + _rollback_states(reports)
    lines += ["", "### Entity list", ""] + _entity_list(reports)
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
