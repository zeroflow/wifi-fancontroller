"""The job summary (CI-05): verdict heading, the DUT A table, the Canary line, masking before anything is written."""

import json
import re

import pytest

from hil import redact, summary

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
    assert "Commit `0123456789ab` | ESPHome 2026.10.1 | Baseline: commit image over serial (no release baseline in this run)" in text


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
        "Baseline: commit image over serial",
        "### DUT A (Rev 3.2, esp32s2)",
        "**Canary:** detected",
        "### Images",
        "### Timings",
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
    order = [text.index("| %s |" % name) for name in ("flash", "boot", "ota_qc-auto", "ota_canary", "ota_commit")]
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


def test_the_baseline_line_is_the_phase_2_wording(reports):
    assert summary.BASELINE_LINE == "Baseline: commit image over serial (no release baseline in this run)"


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
