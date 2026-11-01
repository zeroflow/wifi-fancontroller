"""D-31, QC-06: the canary's deliberate fault is detected on every run.

DUT A is taken to the canary image by encrypted OTA (qc-auto with the PWM pins of fan 1
and fan 2 swapped; it boots clean and its API works, so only the mapping check can catch
it). The same measurement as the fan test runs against it, and this test passes ONLY when
the exact swap signature shows up: fan 1 reads on tach 2 and fan 2 on tach 1, fans 3 and 4
map to themselves, everything else reads 0.

There is no expected-failure marker. A canary that slips through (the mapping looks
perfect), a dead API, all-zero readings, another fault or a wrong build ID are not
detection: the test fails and the run is red. A skipped, deselected or uncollected canary
must not leave a run green either: a run in which this test did not pass is never green
(the canary marker; hil.__main__.decide_verdict ends such a run RIG ERROR).
"""

import json

import pytest

from hil import config, qc
from hil.dut import API_WAIT_S

pytestmark = [
    pytest.mark.image(before="qc-auto", after="canary"),
    pytest.mark.requires("fan_tach_bridge"),
    pytest.mark.canary,
]


def test_canary_swap_is_detected(dut_a, dut_link, fw_manifest, rig_config):
    image = fw_manifest.image("canary")
    dut_a.ota(image, noise_psk=rig_config.dut_api_key)
    dut_link.wait_connected(API_WAIT_S, project_version=image.build_id)

    dropped = []
    readings = qc.measure_mapping(dut_link, image.fan_hz, trace=dropped)
    problems = qc.evaluate_mapping(image.fan_hz, readings)
    print("mapping check on the canary: %d problem(s) (the QC test would be red)" % len(problems))
    detected, text = qc.canary_detected(image.fan_hz, readings)

    reports = config.reports_dir()
    reports.mkdir(parents=True, exist_ok=True)
    record = {
        "detected": detected,
        "text": text,
        "build_id": image.build_id,
        "fan_hz": image.fan_hz,
        "readings": qc.readings_as_json(readings),
        "problems": [list(p) for p in problems],
        "dropped": [[duty, n, m, values] for duty, n, m, values in dropped],
    }
    (reports / "canary-dut-a.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    assert detected, "canary not detected: %s\n%s" % (text, qc.format_problems(problems) or "mapping looks perfect")
    print("Canary: detected (%s)" % text)
