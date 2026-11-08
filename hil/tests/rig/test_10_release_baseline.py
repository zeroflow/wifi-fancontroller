"""D-36, REG-01: every run starts where a customer's board is, on the latest release.

The verified baseline (hil-baseline, fetched by the hosted prepare job and re-hashed on the runner) is
written over serial together with the NVS backup, and DUT A must answer without encryption on the
release's own version. The release is not the firmware under test: a DUT that does not come back on it
is a RIG ERROR (baseline.flash). test_11 then upgrades it to the commit image by OTA, the way a customer
board is upgraded. The D-14 boot-log gate runs on that upgraded boot (test_11) and on the recovery boot
(test_41): the release image prints only the ROM log on UART0, so it has nothing to gate here.
"""

import warnings

import pytest

from hil import baseline, config

pytestmark = pytest.mark.image(after="baseline")


def test_release_baseline_boots_and_rejoins(dut_a, dut_link, fw_baseline, rig_config):
    cfg = rig_config.duts["A"]
    version, rejoin_s = baseline.flash(dut_a, fw_baseline, cfg)  # prints the D-37 drift warning on a rejoin
    warning = baseline.drift_warning(fw_baseline, cfg)
    if warning:
        warnings.warn(warning, stacklevel=1)
    baseline.write_report(config.reports_dir(), fw_baseline, cfg, version, rejoin_s)
    dut_link.use_key(None)  # the release answers without encryption: its runtime log goes to the API log
    assert version == fw_baseline.version
    print(
        "DUT %s runs the release baseline %s (%s), rejoined after %.1f s"
        % (dut_a.id, fw_baseline.tag, version, rejoin_s)
    )
