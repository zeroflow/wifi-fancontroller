"""D-23, D-25: the run's last DUT test puts the commit image back by encrypted OTA.

DUT A ends every run on the commit image; qc-auto and canary images are never final.
Teardown still decides green (keep the commit image) or red (restore last-green over
serial), but a green run needs this OTA to have succeeded (D-26: a failed OTA is a FAIL).
"""

import pytest

pytestmark = pytest.mark.image(after="commit")


def test_ota_back_to_commit_image(dut_a, fw_manifest, rig_config):
    image = fw_manifest.image("commit")
    dut_a.ota(image, noise_psk=rig_config.dut_api_key)
    print("DUT %s back on the commit image: %s" % (dut_a.id, image.build_id))
