"""D-23, D-25, D-41: the OTA back to the commit image, before the broken-image leg.

qc-auto and canary images are never final. This OTA ends the canary leg on the commit image, from
which test_40 delivers the broken image by OTA (D-41); the run's FINAL image then comes from
test_41's UART flash of the commit factory image (D-36). A failed OTA here is a FAIL (D-26).
"""

import pytest

pytestmark = pytest.mark.image(after="commit")


def test_ota_back_to_commit_image(dut_a, fw_manifest, rig_config):
    image = fw_manifest.image("commit")
    dut_a.ota(image, noise_psk=rig_config.dut_api_key)
    print("DUT %s back on the commit image: %s" % (dut_a.id, image.build_id))
