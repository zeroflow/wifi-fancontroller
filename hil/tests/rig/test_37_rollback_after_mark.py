"""REG-05, D-39: an EN reset after the fresh OTA image is marked valid keeps the new image.

DUT A runs the canary after test_36's rollback. This test goes back to the commit image by its own OTA
(label rollback_marked), waits for `Boot seems successful` on UART0 (Dut.wait_confirmed, about 61 s),
then presses a normal, guarded EN reset: the commit's build ID must still answer. It also takes over
test_35's job: the canary leg ends on the commit image, from which test_40 delivers the broken image
(D-41). If test_36 did not roll back (DUT A still on commit), the commit image test_36 left is used and
no OTA runs (`ota_done` false); that run is already FAIL by test_36.
"""

import pytest
from aioesphomeapi import APIConnectionError

from hil import RigError, rollback, summary

pytestmark = pytest.mark.image(after="commit")

LABEL = "rollback_marked"


def test_en_reset_after_the_mark_keeps_the_image(dut_a, fw_manifest, rig_config):
    key = rig_config.dut_api_key
    commit = fw_manifest.image("commit")
    record = {"mark_s": None, "ota_done": False, "build_after": None, "state": None}
    try:
        try:
            running = dut_a.probe(key).project_version
        except (RigError, APIConnectionError, OSError, TimeoutError) as exc:
            pytest.fail("precondition: DUT A does not answer on the API (%s)" % type(exc).__name__)
        if running != commit.build_id:
            dut_a.ota(commit, noise_psk=key, label=LABEL)
            record["ota_done"] = True
            record["state"] = rollback.state_in(dut_a.tap.text("ota_end_%s" % LABEL))
        record["mark_s"] = round(dut_a.wait_confirmed(), 1)
        summary.record_timing("rollback_mark", record["mark_s"])
        mark = dut_a.reset()
        info = dut_a.wait_running(key, mark)
        record["build_after"] = info.project_version
        assert info.project_version == commit.build_id, (
            "EN reset after the mark rolled back to %s, expected the commit image %s to stay (REG-05)"
            % (info.project_version, commit.build_id)
        )
        print(
            "rollback: marked valid after %.1f s, EN reset kept %s (rollback state at its boot: %s)"
            % (record["mark_s"], info.project_version, record["state"] or "no line")
        )
    finally:
        rollback.write_test("marked", record)
