"""HARN-12: a DUT that boots into ESPHome safe mode is reported as safe mode, never as a firmware FAIL.

The qc-auto image has a `QC Safe Mode Boot` button (hil/qc-overrides.yaml). Pressing it makes the
firmware reboot orderly into safe mode: the boot counter is cleared on the way in, WiFi and OTA come
up without the API. That is deterministic, so the detection is proven on every run without a reset
storm, and the safe-mode reboot cannot start a rollback (the image was confirmed long before).

The test passes only when the harness raises SafeModeError for it (a RigError: verdict RIG ERROR
when it happens by itself). It then leaves safe mode with one budgeted EN reset and confirms the
qc-auto build ID again. The safe_mode settings (num_attempts, boot_is_good_after, reboot_timeout)
are the shipped ones in every HIL image.

WR-02 (03-13): the press waits for the qc-auto image's mark first (Dut.wait_confirmed), so it can never
land inside the rollback window of test_20's OTA; in a normal run that window closed long before.
"""

import pytest

from hil import entities
from hil.budget import SafeModeError
from hil.dut import API_WAIT_S, SAFE_MODE_DETECT_S

pytestmark = pytest.mark.image("qc-auto")


def test_safe_mode_boot_is_reported_as_safe_mode(dut_a, dut_link, rig_config, fw_manifest):
    dut_a.wait_confirmed()
    dut_a.tap.mark("safe_mode_press")
    dut_link.press(entities.QC_SAFE_MODE)
    with pytest.raises(SafeModeError) as caught:
        dut_a.wait_running(rig_config.dut_api_key, "safe_mode_press", SAFE_MODE_DETECT_S)
    print("safe mode detected: %s" % caught.value)

    mark = dut_a.reset()
    info = dut_a.wait_running(rig_config.dut_api_key, mark, API_WAIT_S)
    assert info.project_version == fw_manifest.image("qc-auto").build_id
    print("left safe mode with one EN reset")
