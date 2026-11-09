"""REG-05, D-39: an EN reset before a fresh OTA image is marked valid brings DUT A back to the previous image.

Maintainer decision engineer-arming (03-13, 2026-11-09). The 03-13 spike found rollback armed reproducibly
(4 of 4 runs) only for the canary -> commit OTA, so this test takes that OTA, the one test_35 did before:
the commit image goes in by OTA from the canary left by test_30, its boot must print `Bootloader rollback:
supported`, and an EN reset pressed before `Boot seems successful` must bring back the canary, told by
its build ID (the `OTA rollback detected` line is recorded, the build ID decides, RESEARCH A3). When the
boot is not armed the test FAILs with the observed line and the canary's age: a not-armed rollback is
never a pass and never a skip.

Why the arming may break: the cause is not known, (a) the old image came by OTA and has not reached its
own mark, or (b) the target is the commit image. Under (a) the canary must not reach its mark (about
60 s after its OTA) before this upload starts; the measured margin was 4.5-5.6 s. That is why this test
has no before-check (test_30's after-check confirmed a clean canary right before) and why an explicit
warning names test_30 when the margin falls below rollback.ARMING_MARGIN_WARN_S.

The only forced reset of the harness (`reset(force=True)`, grep-guarded): it skips the rollback-window
guard and nothing else, so it is budgeted and recorded as forced. The end state is the canary
(after-check); test_37 then goes back to the commit image by its own OTA.
"""

import os
import time
import warnings

import pytest
from aioesphomeapi import APIConnectionError

from hil import RigError, bootlog, rollback, summary

pytestmark = pytest.mark.image(after="canary")

LABEL = "rollback_fresh"


def _warn(text):
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print("::warning title=HIL rollback::%s" % text)
    else:
        print("WARNING: %s" % text)
    warnings.warn(text, stacklevel=2)


def _running(dut_a, key):
    try:
        return dut_a.probe(key).project_version
    except (RigError, APIConnectionError, OSError, TimeoutError):
        return None


def test_en_reset_before_the_mark_rolls_back(dut_a, fw_manifest, rig_config):
    key = rig_config.dut_api_key
    canary, commit = fw_manifest.image("canary"), fw_manifest.image("commit")
    tap = dut_a.tap
    if (dut_a.last_ota or {}).get("label") != "canary" or not tap.has_mark("ota_end_canary") or dut_a.ota_end_at is None:
        pytest.fail("precondition: the last OTA of the run is not test_30's canary OTA, so rollback cannot be armed (D-39)")

    marked_before = bootlog.BOOT_OK_RE.search(bootlog.strip_ansi(tap.text("ota_end_canary"))) is not None
    arming = rollback.arming_facts(time.monotonic() - dut_a.ota_end_at, marked_before)
    print(
        "rollback arming: canary up %.1f s since its OTA end, %.1f s before its own mark%s"
        % (arming["old_age_s"], arming["margin_s"], " (already marked)" if marked_before else "")
    )
    early = rollback.arming_warning(arming)
    if early:
        _warn(early)

    record = {
        "state": None, "line": None, "outcome": None, "build_after": None, "reset_after_s": None,
        "rollback_line_seen": False, "arming": arming,
    }
    try:
        dut_a.ota(commit, noise_psk=key, label=LABEL)
        end = "ota_end_%s" % LABEL
        try:
            tap.wait_for(rollback.ROLLBACK_STATE_RE.pattern, since=end, deadline_s=rollback.ROLLBACK_LINE_S)
        except RigError:
            if tap.closed:
                raise
        text = tap.text(end)
        record["line"] = rollback.state_line(text)
        record["state"] = rollback.state_in(text)
        if record["state"] != "supported":
            record["outcome"] = "failed"
            record["build_after"] = _running(dut_a, key)
            pytest.fail(rollback.not_armed_message(record["line"], arming))
        if bootlog.BOOT_OK_RE.search(bootlog.strip_ansi(tap.text(end))):
            raise RigError("too late: the commit image was marked valid before the forced reset; the test proves nothing")

        record["reset_after_s"] = round(time.monotonic() - dut_a.ota_end_at, 1)
        mark = dut_a.reset(force=True)
        pressed = time.monotonic()
        summary.record_timing("rollback_reset", record["reset_after_s"])
        info = dut_a.wait_running(key, mark)
        summary.record_timing("rollback_boot", time.monotonic() - pressed)
        record["build_after"] = info.project_version
        record["rollback_line_seen"] = rollback.rolled_back(tap.text(mark))
        record["outcome"] = rollback.fresh_outcome(info.project_version, previous=canary.build_id, new=commit.build_id)
        assert record["outcome"] == "rolled_back", (
            "EN reset %.1f s after the OTA, before the mark, did not roll back: DUT A runs %s, expected the canary %s (REG-05)"
            % (record["reset_after_s"], info.project_version, canary.build_id)
        )
        print(
            "rollback: EN reset %.1f s after the OTA brought back %s (OTA rollback detected line %s)"
            % (record["reset_after_s"], info.project_version, "seen" if record["rollback_line_seen"] else "not seen")
        )
    finally:
        rollback.write_test("fresh", record)
