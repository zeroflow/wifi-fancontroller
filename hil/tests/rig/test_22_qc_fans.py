"""QC-02: each fan channel drives its own tach, and only its own (D-28).

One channel at a time runs at 50 % duty; its `Fan N Speed` must read the PWM frequency
x 30 (pulse_counter counts rising edges per minute, multiply 0.5) within +-10 % in two
consecutive fresh readings, and every other tach must read exactly 0. At 100 % and at
0 % duty every tach reads 0 (LEDC holds a constant level, no edges; RESEARCH Pitfall 4).

The test runs at 50 % only: at the production 25 kHz each half period is 20 us, just
above the pulse counter's 13 us glitch filter, and any duty far from 50 % would put one
phase under it and read 0 (RESEARCH Pitfall 5).

D-27: the first run of this test is the 25 kHz spike. The frequency comes from the
resolved config of the image (manifest fan_hz), never from a constant here. The QC
module overrides it to 1000 Hz only if a channel fails at 25 kHz. The band is never
widened and a failed channel is never retried: reruns hide the faults the rig exists
to show.
"""

import json

import pytest

from hil import config, qc

pytestmark = pytest.mark.image("qc-auto")


def write_report(fan_hz, readings, problems, dropped):
    reports = config.reports_dir()
    reports.mkdir(parents=True, exist_ok=True)
    table = qc.ratio_table(fan_hz, readings)
    data = {
        "fan_hz": fan_hz,
        "expected": qc.expected_reading(fan_hz),
        "readings": qc.readings_as_json(readings),
        "ratios": {str(n): record for n, record in table.items()},
        "problems": [list(p) for p in problems],
        # the values dropped after each command, for the record (not evaluated)
        "dropped": [[duty, n, m, values] for duty, n, m, values in dropped],
    }
    (reports / "qc-fans-dut-a.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return table


def test_fan_channels_map_to_their_own_tach(dut_link, fw_manifest):
    fan_hz = fw_manifest.image("qc-auto").fan_hz
    dropped = []
    readings = qc.measure_mapping(dut_link, fan_hz, trace=dropped)
    problems = qc.evaluate_mapping(fan_hz, readings)
    table = write_report(fan_hz, readings, problems, dropped)
    for n, record in table.items():
        own = ",".join("%g" % v for v in record["own"])
        others = [record["others"][m] for m in sorted(record["others"])]
        print("fan %d @50%%: own=%s expected=%d ratio=%s others=%s" % (n, own, record["expected"], record["ratio"], others))
    assert not problems, "fan channel mapping failed:\n" + qc.format_problems(problems)
