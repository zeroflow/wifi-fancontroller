"""The job summary (CI-05): verdict heading, the DUT A table, the Canary line, masking before anything is written."""

import json
import re

import pytest

from hil import contract, redact, summary

COMMIT = "0123456789abcdef0123456789abcdef01234567"

JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" errors="0" failures="0" skipped="0" tests="2" time="12.5">
<testcase classname="tests.rig.test_10_smoke_dut_a" name="test_commit_image_boots" time="9.100"/>
<testcase classname="tests.rig.test_30_canary" name="test_canary_swap_is_detected" time="3.400"/>
</testsuite></testsuites>
"""

MANIFEST = {
    "commit": COMMIT,
    "esphome_version": "2026.10.1",
    "images": [
        {"role": "commit", "rev": "3.2", "chip": "esp32s2", "build_id": "3.2+hil.0123456789ab", "final": True},
    ],
}


def put(reports, name, data):
    path = reports / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")


@pytest.fixture
def reports(tmp_path):
    root = tmp_path / "reports"
    put(root, "verdict.json", {"verdict": "PASS", "commit": COMMIT, "build_id": "3.2+hil.0123456789ab"})
    put(root, "raw/junit.xml", JUNIT)
    put(root, "canary-dut-a.json", {"detected": True, "text": "fan 1 <-> fan 2 swap"})
    put(root, "final-image.json", {"image": "commit", "version": "3.2+hil.0123456789ab", "confirmed": True})
    return root


def test_the_heading_is_the_verdict_of_verdict_json(reports):
    text = summary.render(reports, MANIFEST)
    assert text.startswith("## HIL run: PASS\n")
    assert "\nCommit `0123456789ab` | ESPHome 2026.10.1\n" in text
    assert "\nBaseline: not run in this run\n" in text
    assert "\nUpgrade: not run in this run\n" in text


@pytest.mark.parametrize("verdict", ["FAIL", "RIG ERROR", "INTERRUPTED"])
def test_a_verdict_other_than_pass_never_shows_pass(reports, verdict):
    put(reports, "verdict.json", {"verdict": verdict, "commit": COMMIT})
    text = summary.render(reports, MANIFEST)
    assert text.startswith("## HIL run: %s\n" % verdict)
    assert "PASS" not in text


@pytest.mark.parametrize("content", [None, "not json", {"verdict": "GREEN"}, {"verdict": "pass"}, {"verdict": True}, []])
def test_a_missing_or_unknown_verdict_is_unknown_never_pass(reports, content):
    if content is None:
        (reports / "verdict.json").unlink()
    else:
        put(reports, "verdict.json", content)
    text = summary.render(reports, MANIFEST)
    assert text.startswith("## HIL run: UNKNOWN\n") and "PASS" not in text


def test_the_dut_table_lists_each_test_with_result_and_duration(reports):
    text = summary.render(reports, MANIFEST)
    assert "### DUT A (Rev 3.2, esp32s2)" in text
    assert "| tests.rig.test_10_smoke_dut_a::test_commit_image_boots | passed | 9.1 s |" in text
    assert "| tests.rig.test_30_canary::test_canary_swap_is_detected | passed | 3.4 s |" in text


def test_the_canary_line_says_detected_or_not(reports):
    assert "**Canary:** detected (fan 1 <-> fan 2 swap)" in summary.render(reports, MANIFEST)
    put(reports, "canary-dut-a.json", {"detected": False, "text": "mapping looks perfect"})
    assert "**Canary:** NOT detected: mapping looks perfect" in summary.render(reports, MANIFEST)


def test_the_final_image_line(reports):
    assert "**Final image:** commit (3.2+hil.0123456789ab), confirmed" in summary.render(reports, MANIFEST)


def test_write_masks_the_literals_before_it_writes_the_file_and_the_step_summary(reports, tmp_path, monkeypatch):
    step = tmp_path / "step.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(step))
    put(reports, "canary-dut-a.json", {"detected": False, "text": "no swap seen at 198.51.100.7 on HIL-Example-Net"})
    text = summary.write(reports, MANIFEST, ["HIL-Example-Net"])
    assert "198.51.100.7" not in text and "HIL-Example-Net" not in text
    assert (reports / "raw" / "summary.md").read_text(encoding="utf-8") == text
    assert step.read_text(encoding="utf-8") == text


def test_write_refuses_to_run_without_literals(reports):
    with pytest.raises(ValueError):
        summary.write(reports, MANIFEST, None)
    assert not (reports / "raw" / "summary.md").exists()


# ------------------------------------------------------------------ Task 2: full content, order, missing reports, timings

JUNIT_FULL = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" errors="0" failures="1" skipped="1" tests="4" time="352.0">
<testcase classname="tests.rig.test_10_smoke_dut_a" name="test_commit_image_boots" time="9.100"/>
<testcase classname="tests.rig.test_22_qc_fans" name="test_fan_channels_map" time="40.000">
<failure message="Fan 2 Speed outside +-10 % of 750000 at 192.0.2.20">trace</failure></testcase>
<testcase classname="tests.rig.test_23_qc_hdc1080" name="test_hdc1080_reports" time="0.000">
<skipped type="pytest.skip" message="DUT A (rig.toml) lacks capability: hdc1080"/></testcase>
<testcase classname="tests.rig.test_30_canary" name="test_canary_swap_is_detected" time="100.000"/>
</testsuite></testsuites>
"""

FULL_MANIFEST = {
    "commit": COMMIT,
    "esphome_version": "2026.10.1",
    "images": [
        {"role": "commit", "rev": "3.2", "chip": "esp32s2", "build_id": "3.2+hil.0123456789ab", "final": True},
        {"role": "qc-auto", "rev": "3.2", "chip": "esp32s2", "build_id": "3.2+qc.0123456789ab", "final": False},
        {"role": "canary", "rev": "3.2", "chip": "esp32s2", "build_id": "3.2+canary.0123456789ab", "final": False},
    ],
}


@pytest.fixture
def full(reports):
    put(reports, "verdict.json", {"verdict": "FAIL", "commit": COMMIT, "build_id": "3.2+hil.0123456789ab"})
    put(reports, "raw/junit.xml", JUNIT_FULL)
    put(reports, "timings.json", {
        "ota_commit": 28.9, "boot": 5.5, "flash": 76.6, "ota_canary": 29.7, "ota_qc-auto": 29.9,
        "ota_qc-auto_boot": 4.6, "ota_canary_boot": 4.5, "ota_commit_boot": 4.6,
    })
    put(reports, "flash-dut-a.json", {"attempts": 1, "durations_s": [76.6], "ok": True, "retry_reason": None, "verified": True})
    put(reports, "ota-dut-a.json", [
        {"role": "qc-auto", "ok": True, "transfer_s": 29.9, "boot_s": 4.6, "reason": "", "build_id": "x"},
        {"role": "canary", "ok": False, "transfer_s": 29.7, "boot_s": None, "reason": "wrong build id", "build_id": "y"},
    ])
    put(reports, "tests.json", {
        "passed": 2, "failed": 1, "failed_tests": ["tests/rig/test_22_qc_fans.py::test_fan_channels_map"],
        "skipped": [{"nodeid": "tests/rig/test_23_qc_hdc1080.py::test_hdc1080_reports", "reason": "rig.toml lacks capability: hdc1080"}],
        "canary_passed": True, "not_run": 0, "session_cut": None,
    })
    put(reports, "rig-errors.json", [])
    put(reports, "allowlisted-errors.json", {"lines": []})
    put(reports, "budget-dut-a.json", {"limit": 8, "used": 6, "streak": 1, "decay_s": 70, "boots": []})
    return reports


def test_every_section_shows_in_the_documented_order(full):
    text = summary.render(full, FULL_MANIFEST)
    markers = [
        "## HIL run: FAIL",
        "Commit `0123456789ab` | ESPHome 2026.10.1",
        "Baseline: not run in this run",
        "Upgrade: not run in this run",
        "### Preflight",
        "### DUT A (Rev 3.2, esp32s2)",
        "**Canary:** detected",
        "### Images",
        "### Timings",
        "### OTA rollback states",
        "### Entity list",
        "### Skipped",
        "### Rig conditions",
        "### Allowlisted boot-log lines",
        "Reset budget: 6 boots, streak 1/8",
        "**Final image:**",
    ]
    positions = [text.index(m) for m in markers]
    assert positions == sorted(positions) and len(set(positions)) == len(markers)


def test_the_images_table_has_role_build_id_and_final(full):
    text = summary.render(full, FULL_MANIFEST)
    assert "| commit | 3.2+hil.0123456789ab | yes |" in text
    assert "| qc-auto | 3.2+qc.0123456789ab | no |" in text
    assert "| canary | 3.2+canary.0123456789ab | no |" in text


def test_the_dut_table_follows_junit_order_and_marks_failed_and_skipped(full):
    lines = [ln for ln in summary.render(full, FULL_MANIFEST).splitlines() if ln.startswith("| tests.rig.")]
    assert [ln.split(" | ")[1] for ln in lines] == ["passed", "failed", "skipped", "passed"]
    assert lines[0].startswith("| tests.rig.test_10_smoke_dut_a::")
    assert lines[3].endswith("| 100.0 s |")


def test_a_failed_test_shows_its_first_message_line_under_failures(full):
    text = summary.render(full, FULL_MANIFEST)
    assert "### Failures" in text
    assert "- tests.rig.test_22_qc_fans::test_fan_channels_map: Fan 2 Speed outside +-10 % of 750000" in text


def test_timing_rows_follow_the_fixed_order_whatever_the_file_order(full):
    text = summary.render(full, FULL_MANIFEST)
    order = [text.index("| %s |" % name) for name in ("ota_qc-auto", "ota_canary", "ota_commit", "flash", "boot")]
    assert order == sorted(order)
    assert "| flash | 76.6 s |" in text and "| ota_commit | 28.9 s |" in text


def test_a_timing_that_was_never_recorded_has_no_row(full):
    put(full, "timings.json", {"flash": 70.0})
    text = summary.render(full, FULL_MANIFEST)
    assert "| flash | 70.0 s |" in text and "| boot |" not in text and "ota_canary" not in text


def test_flash_and_ota_outcomes_are_listed(full):
    text = summary.render(full, FULL_MANIFEST)
    assert "Flash: 1 attempt, verified" in text
    assert "OTA qc-auto: ok" in text
    assert "OTA canary: FAILED (wrong build id)" in text


def test_skipped_tests_are_listed_with_their_reason(full):
    text = summary.render(full, FULL_MANIFEST)
    assert "- tests/rig/test_23_qc_hdc1080.py::test_hdc1080_reports: rig.toml lacks capability: hdc1080" in text


def test_no_skipped_tests_says_none(full):
    put(full, "tests.json", {"skipped": [], "canary_passed": True})
    assert "### Skipped\n\nnone" in summary.render(full, FULL_MANIFEST)


def test_a_fail_summary_has_no_pass_anywhere(full):
    text = summary.render(full, FULL_MANIFEST)
    assert not re.search(r"\bPASS\b", text)


@pytest.mark.parametrize(
    "name, marker",
    [
        ("raw/junit.xml", "junit.xml: not recorded"),
        ("timings.json", "Timings: not recorded"),
        ("canary-dut-a.json", "**Canary:** not run (not recorded)"),
        ("flash-dut-a.json", "Flash: not recorded"),
        ("ota-dut-a.json", "OTA: not recorded"),
        ("tests.json", "Skipped: not recorded"),
        ("budget-dut-a.json", "Reset budget: not recorded"),
        ("rig-errors.json", "Rig conditions: not recorded"),
        ("allowlisted-errors.json", "Allowlisted boot-log lines: not recorded"),
        ("final-image.json", "**Final image:** not recorded"),
    ],
)
def test_a_missing_report_reads_not_recorded_and_the_verdict_is_unchanged(full, name, marker):
    (full / name).unlink()
    text = summary.render(full, FULL_MANIFEST)
    assert marker in text
    assert text.startswith("## HIL run: FAIL\n")


def test_a_run_with_no_reports_at_all_still_renders(tmp_path):
    text = summary.render(tmp_path / "nothing", None)
    assert text.startswith("## HIL run: UNKNOWN\n") and "not recorded" in text


def test_a_corrupt_junit_file_reads_not_recorded(full):
    put(full, "raw/junit.xml", "<testsuites><testsuite")
    assert "junit.xml: not recorded" in summary.render(full, FULL_MANIFEST)


def test_two_tests_with_the_same_name_in_different_modules_are_two_rows(reports):
    put(reports, "raw/junit.xml", (
        '<testsuites><testsuite time="1.0">'
        '<testcase classname="mod_a" name="test_x" time="0.5"/>'
        '<testcase classname="mod_b" name="test_x" time="0.5"/>'
        "</testsuite></testsuites>"
    ))
    text = summary.render(reports, MANIFEST)
    assert "| mod_a::test_x | passed |" in text and "| mod_b::test_x | passed |" in text


@pytest.mark.parametrize(
    "kind, prefix",
    [("SafeModeError", "SAFE MODE: "), ("ResetBudgetExhausted", "RESET BUDGET: "), ("RigError", "RIG ERROR: ")],
)
def test_rig_errors_render_as_their_own_rows(full, kind, prefix):
    put(full, "rig-errors.json", [{"nodeid": "tests/rig/test_x.py::test_a", "kind": kind, "message": "it happened"}])
    text = summary.render(full, FULL_MANIFEST)
    assert "- %sit happened (tests/rig/test_x.py::test_a)" % prefix in text


def test_a_rig_error_before_any_test_has_no_node_id(full):
    put(full, "rig-errors.json", [{"nodeid": None, "kind": "RigError", "message": "manifest: schema must be 2"}])
    assert "- RIG ERROR: manifest: schema must be 2\n" in summary.render(full, FULL_MANIFEST)


def test_no_rig_errors_say_none(full):
    assert "### Rig conditions\n\nnone" in summary.render(full, FULL_MANIFEST)


def test_allowlisted_boot_log_lines_are_listed_as_warnings(full):
    put(full, "allowlisted-errors.json", {"lines": ["E (1234) task_wdt: esp_task_wdt_reset(707): task not found"]})
    text = summary.render(full, FULL_MANIFEST)
    assert "### Allowlisted boot-log lines\n\n- WARNING E (1234) task_wdt: esp_task_wdt_reset(707): task not found" in text


def test_no_allowlisted_lines_say_none(full):
    assert "### Allowlisted boot-log lines\n\nnone" in summary.render(full, FULL_MANIFEST)


def test_the_final_image_line_says_when_it_is_not_confirmed(full):
    put(full, "final-image.json", {"image": "last-green", "version": None, "confirmed": False, "known_good_source": "last-green"})
    assert "**Final image:** last-green (unknown version), NOT confirmed" in summary.render(full, FULL_MANIFEST)


def test_pipes_in_a_test_name_cannot_break_the_table(reports):
    put(reports, "raw/junit.xml", '<testsuites><testsuite><testcase classname="m" name="test_a[x|y]" time="1"/></testsuite></testsuites>')
    assert "| m::test_a[x\\|y] | passed |" in summary.render(reports, MANIFEST)


# ------------------------------------------------------------------ timings.json


def test_record_timing_merges_keys_and_a_second_value_replaces_the_first(tmp_path, monkeypatch):
    monkeypatch.setenv("HIL_REPORTS_DIR", str(tmp_path))
    summary.record_timing("flash", 69.34)
    summary.record_timing("boot", 5.55)
    assert json.loads((tmp_path / "timings.json").read_text(encoding="utf-8")) == {"boot": 5.5, "flash": 69.3}
    summary.record_timing("flash", 70.04)
    assert json.loads((tmp_path / "timings.json").read_text(encoding="utf-8"))["flash"] == 70.0
    assert json.loads((tmp_path / "timings.json").read_text(encoding="utf-8"))["boot"] == 5.5


def test_record_timing_starts_fresh_over_a_corrupt_file(tmp_path, monkeypatch):
    monkeypatch.setenv("HIL_REPORTS_DIR", str(tmp_path))
    (tmp_path / "timings.json").write_text("{not json", encoding="utf-8")
    summary.record_timing("boot", 4.0)
    assert json.loads((tmp_path / "timings.json").read_text(encoding="utf-8")) == {"boot": 4.0}


# ------------------------------------------------------------------ redaction (D-16)

LITERALS = ["192.0.2.10", "02:00:00:00:00:0a", "02000000000a", "HIL-Example-Net", "sv-key-0123456789"]
SECRETS = ["192.0.2.10", "198.51.100.9", "02:00:00:00:00:0a", "02000000000a", "HIL-Example-Net", "sv-key-0123456789"]


def test_redact_removes_addresses_macs_and_keys_from_a_junit_sample():
    sample = (
        '<testsuites><testsuite><testcase classname="m" name="t"><failure message="no answer from 192.0.2.10 / '
        '198.51.100.9 mac 02:00:00:00:00:0a (02000000000a) on HIL-Example-Net key sv-key-0123456789">x</failure>'
        "</testcase></testsuite></testsuites>"
    )
    out = redact.redact(sample, LITERALS)
    assert not [s for s in SECRETS if s in out]
    assert "<failure message=" in out


def test_a_rendered_summary_with_addresses_macs_and_keys_is_masked_by_write(full):
    put(full, "rig-errors.json", [{"nodeid": None, "kind": "RigError", "message": " ".join(SECRETS)}])
    put(full, "raw/junit.xml", JUNIT_FULL.replace("192.0.2.20", "198.51.100.9 02:00:00:00:00:0a"))
    text = summary.write(full, FULL_MANIFEST, LITERALS)
    assert not [s for s in SECRETS if s in text]
    assert not [s for s in SECRETS if s in (full / "raw" / "summary.md").read_text(encoding="utf-8")]
    assert "RIG ERROR: " in text


def test_the_phase_2_baseline_constant_is_gone(reports):
    assert not hasattr(summary, "BASELINE_LINE")


# ------------------------------------------------------------------ hil teardown wiring


def test_teardown_writes_the_summary_only_when_a_config_was_loaded(reports, monkeypatch):
    from hil import __main__ as entry

    entry.write_summary(None, reports)
    assert not (reports / "raw" / "summary.md").exists()

    monkeypatch.setattr(entry.config, "mask_literals", lambda rig: ["HIL-Example-Net"])
    monkeypatch.setenv("HIL_FW_DIR", str(reports / "fw"))
    put(reports, "fw/manifest.json", FULL_MANIFEST)
    put(reports, "canary-dut-a.json", {"detected": False, "text": "seen on HIL-Example-Net"})
    entry.write_summary(object(), reports)
    text = (reports / "raw" / "summary.md").read_text(encoding="utf-8")
    assert "HIL-Example-Net" not in text and "ESPHome 2026.10.1" in text and "| canary | 3.2+canary.0123456789ab | no |" in text


def test_a_summary_fault_is_reported_and_never_raised(reports, monkeypatch, capsys):
    from hil import __main__ as entry

    def broken(*_args):
        raise OSError("disk full")

    monkeypatch.setattr(entry.config, "mask_literals", lambda rig: [])
    monkeypatch.setattr(entry.summary, "write", broken)
    entry.write_summary(object(), reports)
    assert "job summary not written (OSError)" in capsys.readouterr().out


def test_the_manifest_dict_is_none_without_a_readable_manifest(tmp_path, monkeypatch):
    from hil import __main__ as entry

    monkeypatch.setenv("HIL_FW_DIR", str(tmp_path))
    assert entry.firmware_manifest_dict() is None
    (tmp_path / "manifest.json").write_text("[1]", encoding="utf-8")
    assert entry.firmware_manifest_dict() is None
    (tmp_path / "manifest.json").write_text('{"commit": "x"}', encoding="utf-8")
    assert entry.firmware_manifest_dict() == {"commit": "x"}


# ---------------------------------------------------------------- Preflight section (03-08, HARN-05)

A = contract.SERIAL_CONNECTED["A"].removesuffix(" Serial Connected")  # the DUT A label, from contract
B = contract.SERIAL_CONNECTED["B"].removesuffix(" Serial Connected")

PREFLIGHT = {
    "schema": 1,
    "commit": COMMIT,
    "checks": [
        {"name": "supervisor reachable", "ok": True, "detail": ""},
        {"name": "contract", "ok": True, "detail": "21 names"},
        {"name": A + " bridge clients", "ok": True, "detail": "0 after 26 s"},
        {"name": A + " boot", "ok": True, "detail": "boot:0x8 seen, API answered (HIL key), 3.2+hil.0123456789ab"},
        {"name": B + " boot", "ok": False, "detail": "not checked (DUT B joins the suite in Phase 4)"},
    ],
    "warnings": ["stray bridge client on " + A + " evicted after 26 s"],
    "heal": None,
    "watchdog_start": {"A": 6, "B": 0},
}


def test_the_preflight_section_lists_each_check_and_each_warning_for_this_commit(full):
    put(full, "preflight.json", PREFLIGHT)
    text = summary.render(full, FULL_MANIFEST)
    section = text[text.index("### Preflight"):text.index("### DUT A")]
    assert "| supervisor reachable | ok |" in section
    assert "| contract | ok (21 names) |" in section
    assert "| %s bridge clients | ok (0 after 26 s) |" % A in section
    assert "| %s boot | not checked (DUT B joins the suite in Phase 4) |" % B in section
    assert "- WARNING stray bridge client on %s evicted after 26 s" % A in section
    assert "Heal: no heal" in section
    assert summary.PREFLIGHT_NOT_RUN not in section


@pytest.mark.parametrize("commit", ["f" * 40, None, ""])
def test_a_preflight_of_another_commit_reads_not_run_for_this_commit(full, commit):
    put(full, "preflight.json", {**PREFLIGHT, "commit": commit})
    text = summary.render(full, FULL_MANIFEST)
    section = text[text.index("### Preflight"):text.index("### DUT A")]
    assert summary.PREFLIGHT_NOT_RUN in section and "supervisor reachable" not in section


def test_no_preflight_json_reads_not_run_for_this_commit(full):
    assert summary.PREFLIGHT_NOT_RUN in summary.render(full, FULL_MANIFEST)


def test_a_verdict_without_a_commit_never_shows_a_preflight(full):
    put(full, "preflight.json", PREFLIGHT)
    put(full, "verdict.json", {"verdict": "FAIL", "commit": None})
    assert summary.PREFLIGHT_NOT_RUN in summary.render(full, FULL_MANIFEST)


def test_a_heal_shows_its_source_and_version(full):
    healed = {
        **PREFLIGHT,
        "warnings": [A + " healed with v1.6.0 (3.2)"],
        "heal": {"source": "v1.6.0", "ok": True, "version": "3.2", "duration_s": 86.1,
                 "detail": "v1.6.0 (3.2) written and confirmed", "first_failure": A + " boot check failed: ..."},
    }
    put(full, "preflight.json", healed)
    text = summary.render(full, FULL_MANIFEST)
    assert "Heal: healed with v1.6.0 (3.2)" in text
    assert "- WARNING %s healed with v1.6.0 (3.2)" % A in text


def test_a_heal_that_could_not_start_shows_its_cause(full):
    failed = {
        **PREFLIGHT,
        "checks": PREFLIGHT["checks"][:3] + [{"name": A + " boot", "ok": False, "detail": "heal impossible: no image"}],
        "warnings": [],
        "heal": {"source": None, "ok": False, "detail": "heal impossible: no image", "first_failure": "x"},
    }
    put(full, "preflight.json", failed)
    text = summary.render(full, FULL_MANIFEST)
    assert "| %s boot | heal impossible: no image |" % A in text
    assert "Heal: heal impossible: no image" in text
    assert "Warnings: none" in text


# ---------------------------------------------------------- Supervisor watchdog line (03-08, D-47)


def watchdog_line(text):
    return next(line for line in text.splitlines() if line.startswith("Supervisor watchdog:"))


def test_no_release_during_the_run_reads_none(full):
    put(full, "watchdog.json", {"start": {"A": 6, "B": 0}, "end": {"A": 6, "B": 0}, "delta": {"A": 0, "B": 0}})
    assert watchdog_line(summary.render(full, FULL_MANIFEST)) == "Supervisor watchdog: none"


def test_a_release_of_dut_b_is_a_warning_line(full):
    put(full, "watchdog.json", {"start": {"A": 6, "B": 0}, "end": {"A": 6, "B": 1}, "delta": {"A": 0, "B": 1}})
    line = watchdog_line(summary.render(full, FULL_MANIFEST))
    assert line == "Supervisor watchdog: %s released 1 line(s) during this run (WARNING)" % B


def test_releases_of_both_duts_are_both_named(full):
    put(full, "watchdog.json", {"start": {"A": 0, "B": 0}, "end": {"A": 2, "B": 1}, "delta": {"A": 2, "B": 1}})
    line = watchdog_line(summary.render(full, FULL_MANIFEST))
    assert "%s released 2 line(s) during this run (WARNING)" % A in line
    assert "%s released 1 line(s) during this run (WARNING)" % B in line


def test_without_watchdog_json_the_line_reads_not_recorded(full):
    assert watchdog_line(summary.render(full, FULL_MANIFEST)) == "Supervisor watchdog: not recorded"


def test_a_dut_without_a_start_value_reads_not_recorded_for_that_dut(full):
    put(full, "watchdog.json", {"start": None, "end": {"A": 6, "B": 1}, "delta": {"A": None, "B": None}})
    line = watchdog_line(summary.render(full, FULL_MANIFEST))
    assert line == "Supervisor watchdog: not recorded (%s, %s)" % (A, B)


def test_a_counter_that_fell_says_the_supervisor_restarted(full):
    put(full, "watchdog.json", {"start": {"A": 6, "B": 0}, "end": {"A": 0, "B": 0}, "delta": {"A": -6, "B": 0}})
    line = watchdog_line(summary.render(full, FULL_MANIFEST))
    assert "%s counter fell from 6 to 0" % A in line and "(WARNING)" in line


def test_the_watchdog_line_sits_after_the_preflight_section_and_before_dut_a(full):
    put(full, "preflight.json", PREFLIGHT)
    put(full, "watchdog.json", {"start": {"A": 6, "B": 0}, "end": {"A": 6, "B": 0}, "delta": {"A": 0, "B": 0}})
    text = summary.render(full, FULL_MANIFEST)
    assert text.index("### Preflight") < text.index("Supervisor watchdog: none") < text.index("### DUT A")


# ------------------------------------------------------------------ 03-12: SC1 lines (baseline, upgrade, timings) and the entity list

SHA = "ab" * 32
BASELINE_REPORT = {
    "schema": 1, "tag": "v2026.11.0", "rev": "3.2", "asset": "fancontroller-r3-2-esp32s2.factory.bin", "sha256": SHA,
    "digests_compared": ["asset", "manifest"], "flash_s": 73.3, "rejoin_s": 5.6, "version": "2026.11.0",
    "nvs_replayed": True, "nvs_release_tag": "v2026.11.0", "drift_warning": None,
}
UPGRADE_REPORT = {
    "schema": 1, "tag": "v2026.11.0", "from_version": "2026.11.0", "build_id": "3.2+hil.0123456789ab",
    "reported_build_id": "3.2+hil.0123456789ab", "label": "baseline_commit", "reboot_proof": "build id",
    "transfer_s": 28.0, "boot_s": 4.6, "mark_s": 60.8, "mark_source": "api", "soak_s": 70.0, "banners": 0,
    "api_session_dropped": False, "api_log_lines": 259, "errors": [], "allowed": [], "gate": "pass", "gate_source": "api",
}
BASELINE_TEXT = (
    "Baseline: release v2026.11.0 (fancontroller-r3-2-esp32s2.factory.bin, sha256 abababababab, 2 digests agree)"
    " + NVS replay captured with v2026.11.0"
)
UPGRADE_TEXT = (
    "Upgrade: v2026.11.0 -> 3.2+hil.0123456789ab by OTA, transfer 28.0 s, boot 4.6 s, marked valid after 60.8 s,"
    " soak 70.0 s: 0 UART0 banners, no API drop, API boot log clean"
)


def lines_of(text):
    return text.splitlines()


def test_the_baseline_line_names_tag_asset_hash_and_digests_and_follows_the_commit_line(reports):
    put(reports, "baseline-dut-a.json", BASELINE_REPORT)
    lines = lines_of(summary.render(reports, MANIFEST))
    assert BASELINE_TEXT in lines
    assert not [line for line in lines if line.startswith("WARNING: NVS")]
    assert lines.index(BASELINE_TEXT) > lines.index("Commit `0123456789ab` | ESPHome 2026.10.1")


def test_a_tag_drift_adds_the_warning_line_right_after_the_baseline_line(reports):
    put(reports, "baseline-dut-a.json", {
        **BASELINE_REPORT, "tag": "v1.7.0", "nvs_release_tag": "v1.6.0", "drift_warning": "NVS captured with v1.6.0, baseline v1.7.0",
    })
    lines = lines_of(summary.render(reports, MANIFEST))
    head = [line for line in lines if line.startswith("Baseline: release v1.7.0")]
    assert head == [
        "Baseline: release v1.7.0 (fancontroller-r3-2-esp32s2.factory.bin, sha256 abababababab, 2 digests agree)"
        " + NVS replay captured with v1.6.0"
    ]
    after = [line for line in lines[lines.index(head[0]) + 1:] if line][0]
    assert after == "WARNING: NVS captured with v1.6.0, baseline v1.7.0"


def test_a_baseline_without_the_nvs_replay_says_so(reports):
    put(reports, "baseline-dut-a.json", {**BASELINE_REPORT, "nvs_replayed": False, "nvs_release_tag": None})
    text = summary.render(reports, MANIFEST)
    assert "sha256 abababababab, 2 digests agree) + no NVS replay" in text


@pytest.mark.parametrize("content", [None, "not json", [], {"schema": 1}])
def test_without_a_usable_baseline_report_the_baseline_was_not_run(reports, content):
    if content is not None:
        put(reports, "baseline-dut-a.json", content)
    lines = lines_of(summary.render(reports, MANIFEST))
    assert "Baseline: not run in this run" in lines


def test_the_upgrade_line_comes_from_the_upgrade_report_after_the_baseline_line(reports):
    put(reports, "baseline-dut-a.json", BASELINE_REPORT)
    put(reports, "upgrade-dut-a.json", UPGRADE_REPORT)
    lines = lines_of(summary.render(reports, MANIFEST))
    assert UPGRADE_TEXT in lines
    assert lines.index(UPGRADE_TEXT) > lines.index(BASELINE_TEXT)


def test_the_upgrade_line_shows_banners_drop_and_gate_errors(reports):
    put(reports, "upgrade-dut-a.json", {
        **UPGRADE_REPORT, "banners": 1, "api_session_dropped": True, "errors": ["[E] a", "[E] b"], "gate": "fail",
    })
    text = summary.render(reports, MANIFEST)
    assert "soak 70.0 s: 1 UART0 banner, API session dropped, API boot log 2 errors" in text


def test_the_upgrade_line_with_a_uart0_gate_and_one_error(reports):
    put(reports, "upgrade-dut-a.json", {**UPGRADE_REPORT, "gate_source": "uart0", "banners": 2, "errors": ["[E] a"]})
    assert "soak 70.0 s: 2 UART0 banners, no API drop, UART0 boot log 1 error" in summary.render(reports, MANIFEST)


def test_an_upgrade_report_with_missing_numbers_shows_question_marks_never_raises(reports):
    put(reports, "upgrade-dut-a.json", {"schema": 1, "tag": "v2026.11.0", "build_id": "3.2+hil.0123456789ab"})
    text = summary.render(reports, MANIFEST)
    assert "Upgrade: v2026.11.0 -> 3.2+hil.0123456789ab by OTA, transfer ? s, boot ? s, marked valid after ? s, soak ? s" in text


@pytest.mark.parametrize("content", [None, "not json", [], {"schema": 1}])
def test_without_a_usable_upgrade_report_the_upgrade_was_not_run(reports, content):
    if content is not None:
        put(reports, "upgrade-dut-a.json", content)
    assert "Upgrade: not run in this run" in lines_of(summary.render(reports, MANIFEST))


def test_the_head_lines_are_masked_like_the_rest(reports):
    put(reports, "upgrade-dut-a.json", {**UPGRADE_REPORT, "tag": "v2026.11.0 HIL-Example-Net"})
    text = summary.write(reports, MANIFEST, ["HIL-Example-Net"])
    assert "HIL-Example-Net" not in text and "Upgrade: v2026.11.0 " in text


def test_timing_order_starts_with_the_upgrade_leg_and_ends_with_the_last_serial_flash():
    assert summary.TIMING_ORDER == (
        "baseline_flash", "ota_baseline_commit", "ota_baseline_commit_boot", "soak_mark", "restore_flash", "restore_boot",
        "ota_qc-auto", "ota_qc-auto_boot", "ota_canary", "ota_canary_boot", "ota_commit", "ota_commit_boot", "ota_broken",
        "flash", "boot",
    )


def test_the_upgrade_timings_lead_the_timings_table(full):
    put(full, "timings.json", {"flash": 74.0, "soak_mark": 60.8, "baseline_flash": 73.3, "ota_baseline_commit": 28.0, "zz_extra": 1.0})
    text = summary.render(full, FULL_MANIFEST)
    order = [text.index("| %s |" % name) for name in ("baseline_flash", "ota_baseline_commit", "soak_mark", "flash", "zz_extra")]
    assert order == sorted(order)


def entity_report(removed=(), added=(), actual=None, error=None):
    actual = [{"type": "fan", "name": "Fan X"}, {"type": "sensor", "name": "Speed X"}] if actual is None else actual
    return {
        "schema": 1, "rev": "3.2", "golden_file": "hil/golden/entities-3.2.json", "actual": actual,
        "removed": [{"type": t, "name": n} for t, n in removed], "added": [{"type": t, "name": n} for t, n in added],
        "error": error,
    }


def entity_section(text):
    start = text.index("### Entity list\n")
    end = text.index("\n### ", start + 1)
    return text[start:end]


def test_the_entity_list_section_says_it_matches_golden(full):
    put(full, "golden-dut-a.json", entity_report())
    assert "matches golden (2 entities)" in entity_section(summary.render(full, FULL_MANIFEST))


def test_the_entity_list_section_lists_removed_and_added_entries_one_per_line(full):
    put(full, "golden-dut-a.json", entity_report(
        removed=[("light", "NeoPixel X"), ("sensor", "Speed Y")], added=[("sensor", "HIL Invented Sensor")],
    ))
    section = entity_section(summary.render(full, FULL_MANIFEST))
    lines = lines_of(section)
    assert "- removed: light: NeoPixel X" in lines and "- removed: sensor: Speed Y" in lines
    assert "- added: sensor: HIL Invented Sensor" in lines
    assert "matches golden" not in section
    assert "golden from-run" in section  # how to accept an intended change (D-38)


def test_an_entity_name_cannot_break_the_markdown(full):
    put(full, "golden-dut-a.json", entity_report(added=[("sensor", "a | b\n### Fake")]))
    section = entity_section(summary.render(full, FULL_MANIFEST))
    assert "- added: sensor: a \\| b ### Fake" in lines_of(section)


def test_a_golden_file_error_is_shown_in_the_entity_list_section(full):
    put(full, "golden-dut-a.json", entity_report(error="golden entity list hil/golden/entities-3.2.json is missing"))
    section = entity_section(summary.render(full, FULL_MANIFEST))
    assert "golden list not usable: golden entity list hil/golden/entities-3.2.json is missing" in section
    assert "matches golden" not in section


def test_an_empty_device_list_never_reads_as_a_match(full):
    put(full, "golden-dut-a.json", entity_report(actual=[]))
    section = entity_section(summary.render(full, FULL_MANIFEST))
    assert "matches golden" not in section and "listed no entities" in section


@pytest.mark.parametrize("content", [None, "not json", [], {"schema": 1}])
def test_without_a_usable_entity_report_the_list_was_not_checked(full, content):
    if content is not None:
        put(full, "golden-dut-a.json", content)
    assert "### Entity list\n\nnot checked in this run" in summary.render(full, FULL_MANIFEST)


def test_the_entity_list_section_follows_the_timings_and_precedes_skipped(full):
    put(full, "golden-dut-a.json", entity_report())
    text = summary.render(full, FULL_MANIFEST)
    assert text.index("### Timings") < text.index("### Entity list") < text.index("### Skipped")


# OTA rollback states (D-39, D-41) ---------------------------------------------------------


def rollback_section(text):
    start = text.index("### OTA rollback states\n")
    end = text.index("\n### ", start + 1)
    return text[start:end]


ROLLBACK_ROWS = [
    {"label": "baseline_commit", "role": "commit", "ok": True, "state": None, "source": "unobservable (release bootloader)",
     "image_state": None, "old_uptime_s": 83.2, "rolled_back": False},
    {"label": "qc-auto", "role": "qc-auto", "ok": True, "state": "support unknown", "source": "uart0",
     "image_state": None, "old_uptime_s": 121.0, "rolled_back": False},
    {"label": "broken", "role": "broken", "ok": True, "state": None, "source": "uart0",
     "image_state": "valid", "old_uptime_s": 40.5, "rolled_back": False},
]


def test_the_rollback_section_has_one_row_per_ota_with_state_source_image_state_and_old_uptime(full):
    put(full, "rollback-states.json", ROLLBACK_ROWS)
    lines = lines_of(rollback_section(summary.render(full, FULL_MANIFEST)))
    assert "| OTA | Role | Rollback state | Source | Image state | Old image up |" in lines
    assert "| baseline_commit | commit | no line | unobservable (release bootloader) | - | 83.2 s |" in lines
    assert "| qc-auto | qc-auto | support unknown | uart0 | - | 121.0 s |" in lines
    assert "| broken | broken | no line | uart0 | valid | 40.5 s |" in lines


@pytest.mark.parametrize("content", [None, "not json", {"rows": []}])
def test_without_a_usable_rollback_report_the_section_reads_not_recorded(full, content):
    if content is not None:
        put(full, "rollback-states.json", content)
    assert "### OTA rollback states\n\nnot recorded" in summary.render(full, FULL_MANIFEST)


def test_a_missing_uptime_reads_as_a_question_mark(full):
    put(full, "rollback-states.json", [dict(ROLLBACK_ROWS[1], old_uptime_s=None)])
    assert "| qc-auto | qc-auto | support unknown | uart0 | - | ? |" in lines_of(rollback_section(summary.render(full, FULL_MANIFEST)))


def test_the_rollback_tests_add_one_line_each(full):
    put(full, "rollback-states.json", ROLLBACK_ROWS)
    put(full, "rollback-dut-a.json", {
        "fresh": {"state": "support unknown", "outcome": "skipped", "build_after": "3.2+qc.0123456789ab"},
        "marked": {"mark_s": 60.8, "ota_done": False, "build_after": "3.2+qc.0123456789ab"},
    })
    section = rollback_section(summary.render(full, FULL_MANIFEST))
    assert "Rollback before the mark: skipped (state support unknown, build after 3.2+qc.0123456789ab)" in section
    assert "Reset after the mark: build after 3.2+qc.0123456789ab, marked valid after 60.8 s" in section


def test_the_rollback_section_follows_the_timings_and_precedes_the_entity_list(full):
    text = summary.render(full, FULL_MANIFEST)
    assert text.index("### Timings") < text.index("### OTA rollback states") < text.index("### Entity list")


def test_the_rollback_reports_are_stale_at_the_start_of_a_run():
    from hil import __main__ as entry
    from hil import rollback

    assert {rollback.STATES_REPORT, rollback.TEST_REPORT} <= set(entry.STALE_REPORTS)
    assert (summary.ROLLBACK_STATES_REPORT, summary.ROLLBACK_TEST_REPORT) == (rollback.STATES_REPORT, rollback.TEST_REPORT)
