"""QC-03: the HDC1080 reports a plausible climate (D-29).

Two fresh Temperature and two fresh Humidity readings within HDC_WINDOW_S, none NaN,
temperature 5-45 C and humidity 10-90 %RH (bounds included). Runs on the qc-auto image,
whose sensors publish every 5 s; skipped with a reason when rig.toml does not list the
hdc1080 capability for DUT A (HARN-02).
"""

import pytest

from hil import qc

pytestmark = [pytest.mark.image("qc-auto"), pytest.mark.requires("hdc1080")]


def test_hdc1080_reports_plausible_climate(dut_link):
    temps, hums = qc.measure_climate(dut_link)
    print(
        "HDC1080: temperature=%s C humidity=%s %%RH"
        % (",".join("%g" % v for v in temps), ",".join("%g" % v for v in hums))
    )
    problems = qc.evaluate_climate(temps, hums)
    assert not problems, "HDC1080 not plausible:\n" + "\n".join(problems)
