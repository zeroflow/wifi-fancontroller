"""D-23: DUT A goes from the serial-flashed commit image to the qc-auto image by encrypted OTA.

The OTA is firmware under test: a failed upload or a wrong image afterwards is a FAIL
(D-26, hil.FirmwareFailure). The qc-auto image is never a final image (D-25); the
last test of the run (test_90_restore_commit.py) puts the commit image back.
"""

import pytest

pytestmark = pytest.mark.image(before="commit", after="qc-auto")


def test_ota_to_qc_auto(dut_a, fw_manifest, rig_config):
    image = fw_manifest.image("qc-auto")
    dut_a.ota(image, noise_psk=rig_config.dut_api_key)
    print("DUT %s runs the qc-auto image: %s" % (dut_a.id, image.build_id))
