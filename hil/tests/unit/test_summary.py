"""The job summary (CI-05): verdict heading, the DUT A table, the Canary line, masking before anything is written."""

import json

import pytest

from hil import summary

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
