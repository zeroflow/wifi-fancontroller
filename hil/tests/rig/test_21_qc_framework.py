"""QC-05: DUT A runs the framework its revision shipped with (D-34, hardware leg).

Four values must be the same name: the committed table (hil/frameworks.toml) for DUT A's
revision, the framework rig.toml declares for DUT A, the framework DUT A itself reports in
`QC Device Info`, and the framework of the qc-auto image in the build manifest. A missing,
empty or field-less device report fails the test (it is never skipped), and the values are
printed in that fixed order. The test only reads; it never changes a framework.
"""

import pytest

from hil import entities, qc

pytestmark = pytest.mark.image("qc-auto")


def test_dut_runs_the_shipped_framework(dut_link, rig_config, fw_manifest):
    dut = rig_config.duts["A"]
    text = dut_link.wait_value(entities.QC_DEVICE_INFO, bool, qc.TEXT_SENSOR_WAIT_S)
    device = qc.framework_from_device_info(text)
    table = qc.framework_table()[dut.rev]
    manifest = fw_manifest.image("qc-auto").framework
    print("framework: table=%s rig.toml=%s device=%s manifest=%s" % (table, dut.framework, device, manifest))
    problems = qc.evaluate_framework(table, dut.framework, device, manifest)
    assert not problems, "framework mismatch (D-34): " + "; ".join(problems)
