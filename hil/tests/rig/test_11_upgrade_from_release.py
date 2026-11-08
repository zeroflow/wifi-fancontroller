"""REG-02, D-36: DUT A is upgraded from the latest release to the commit image by OTA, the way a
customer board is upgraded.

The release predates OTA encryption, so this one upload is allowed in plaintext (maintainer decision
allow-one-plaintext, 2026-11-08, T-03-24): the image carries only the HIL values D-01 classed as
published, the HIL network is isolated, and the key is still offered. Every other OTA keeps refusing
plaintext. A failed upload or a wrong build ID afterwards is a FAIL (D-26).
"""

import json

import pytest

from hil import config

pytestmark = pytest.mark.image(before="baseline", after="commit")

LABEL = "baseline_commit"


def test_ota_from_the_release_to_the_commit(dut_a, dut_link, fw_manifest, fw_baseline, rig_config):
    image = fw_manifest.image("commit")
    dut_link.use_key(rig_config.dut_api_key)  # the commit image answers with the HIL key only
    dut_a.ota(image, noise_psk=rig_config.dut_api_key, allow_plaintext=True, label=LABEL)

    reported = dut_a.probe(rig_config.dut_api_key)
    reports = config.reports_dir()
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "dut-a.json").write_text(
        json.dumps(
            {"project_version": reported.project_version, "compilation_time": reported.compilation_time},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    assert reported.project_version == image.build_id, "DUT %s reports %s after the upgrade, expected %s" % (
        dut_a.id,
        reported.project_version,
        image.build_id,
    )
    print("DUT %s upgraded from %s to %s by OTA" % (dut_a.id, fw_baseline.tag, image.build_id))
