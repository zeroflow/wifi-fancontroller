"""Fan mapping evaluator and measurement procedure (QC-02, D-27, D-28)."""

import copy

import pytest

from hil import RigError, entities, qc

HZ = 25000
E = qc.expected_reading(HZ)
CHANNELS = entities.CHANNELS
PARTIAL = 987654321  # what the intervals around a command look like: always dropped


def perfect(hz=HZ):
    """readings[duty][n][m] of a device whose channel n drives only tach n."""
    e = qc.expected_reading(hz)
    return {
        duty: {n: {m: ([e, e] if (duty == 50 and m == n) else [0, 0]) for m in CHANNELS} for n in CHANNELS}
        for duty in qc.DUTIES
    }


def with_value(readings, duty, n, m, values):
    out = copy.deepcopy(readings)
    out[duty][n][m] = values
    return out


def test_expected_reading_is_pwm_hz_times_30():
    assert qc.expected_reading(25000) == 750000
    assert qc.expected_reading(1000) == 30000


def test_constants_are_the_decided_ones():
    assert qc.MAPPING_TOLERANCE == 0.10
    assert qc.FAN_SETTLE_S == 15
    assert qc.READINGS_PER_CHECK == 2
    assert qc.DUTIES == (50, 100, 0)


def test_perfect_device_has_no_problems():
    assert qc.evaluate_mapping(HZ, perfect()) == []


@pytest.mark.parametrize("hz", [25000, 1000])
def test_reading_exactly_ten_percent_off_passes_on_both_sides(hz):
    e = qc.expected_reading(hz)
    low = with_value(perfect(hz), 50, 2, 2, [e * 9 // 10] * 2)
    high = with_value(perfect(hz), 50, 2, 2, [e * 11 // 10] * 2)
    assert qc.evaluate_mapping(hz, low) == []
    assert qc.evaluate_mapping(hz, high) == []


@pytest.mark.parametrize("hz", [25000, 1000])
def test_one_count_beyond_the_band_fails_on_both_sides(hz):
    e = qc.expected_reading(hz)
    for value in (e * 9 // 10 - 1, e * 11 // 10 + 1):
        problems = qc.evaluate_mapping(hz, with_value(perfect(hz), 50, 3, 3, [e, value]))
        assert [p[:3] for p in problems] == [(50, 3, 3)]
        assert problems[0][3] == [e, value]


def test_a_single_bad_value_of_the_pair_fails_the_channel():
    problems = qc.evaluate_mapping(HZ, with_value(perfect(), 50, 1, 1, [E, E // 2]))
    assert [p[:3] for p in problems] == [(50, 1, 1)]


def test_non_target_channel_reading_one_fails_because_exactly_zero_is_required():
    problems = qc.evaluate_mapping(HZ, with_value(perfect(), 50, 1, 4, [0, 1]))
    assert problems == [(50, 1, 4, [0, 1], "expected exactly 0")]


def test_nonzero_at_100_and_at_0_percent_fails():
    for duty in (100, 0):
        problems = qc.evaluate_mapping(HZ, with_value(perfect(), duty, 2, 2, [0, 5]))
        assert [p[:3] for p in problems] == [(duty, 2, 2)]


def test_missing_value_is_a_no_fresh_reading_problem_never_a_zero():
    problems = qc.evaluate_mapping(HZ, with_value(perfect(), 100, 3, 3, [0]))
    assert problems == [(100, 3, 3, [0], "no fresh reading")]


def test_empty_list_and_absent_entries_are_no_fresh_reading_too():
    empty = with_value(perfect(), 50, 1, 1, [])
    assert qc.evaluate_mapping(HZ, empty) == [(50, 1, 1, [], "no fresh reading")]
    absent = perfect()
    del absent[100][2][4]
    assert qc.evaluate_mapping(HZ, absent) == [(100, 2, 4, [], "no fresh reading")]
    no_duty = perfect()
    del no_duty[0]
    assert len(qc.evaluate_mapping(HZ, no_duty)) == 16


def test_nan_is_not_zero_and_not_in_band():
    nan = float("nan")
    assert [p[:3] for p in qc.evaluate_mapping(HZ, with_value(perfect(), 50, 1, 1, [nan, nan]))] == [(50, 1, 1)]
    assert [p[:3] for p in qc.evaluate_mapping(HZ, with_value(perfect(), 100, 1, 2, [nan, nan]))] == [(100, 1, 2)]


def test_problems_come_back_sorted_by_duty_driven_channel_read_channel():
    bad = perfect()
    bad[0][4][2] = [7, 7]
    bad[100][3][1] = [7, 7]
    bad[50][2][4] = [7, 7]
    bad[50][2][1] = [7, 7]
    bad[50][1][3] = [7, 7]
    shuffled = {duty: dict(reversed(list(bad[duty].items()))) for duty in reversed(list(bad))}
    expected = [(0, 4, 2), (50, 1, 3), (50, 2, 1), (50, 2, 4), (100, 3, 1)]
    assert [p[:3] for p in qc.evaluate_mapping(HZ, bad)] == expected
    assert [p[:3] for p in qc.evaluate_mapping(HZ, shuffled)] == expected


def test_format_problems_names_duty_driven_fan_tach_and_values():
    text = qc.format_problems([(50, 1, 2, [0, 1], "expected exactly 0")])
    assert "duty 50 %" in text and "driven fan 1" in text and "tach 2" in text and "[0, 1]" in text


def test_ratio_table_records_observed_expected_ratio_and_the_others():
    readings = with_value(perfect(), 50, 2, 2, [E * 9 // 10, E])
    readings[50][2][4] = [0, 3]
    table = qc.ratio_table(HZ, readings)
    assert sorted(table) == [1, 2, 3, 4]
    assert table[1] == {"own": [E, E], "expected": E, "ratio": 1.0, "others": {2: [0, 0], 3: [0, 0], 4: [0, 0]}}
    assert table[2]["ratio"] == 0.95
    assert table[2]["others"][4] == [0, 3]


def test_ratio_table_has_no_ratio_without_readings_or_with_nan():
    missing = with_value(perfect(), 50, 1, 1, [])
    nan = with_value(perfect(), 50, 2, 2, [float("nan"), E])
    assert qc.ratio_table(HZ, missing)[1]["ratio"] is None
    assert qc.ratio_table(HZ, nan)[2]["ratio"] is None


# ------------------------------------------------------------ measure_mapping


class FakeLink:
    """A DUT whose fan n reaches tach wiring[n]; a driven 50 % channel reads fan_hz x 30, else 0."""

    def __init__(self, fan_hz=HZ, wiring=None, silent=(), fail_after=None, down=False):
        self.hz = fan_hz
        self.wiring = wiring or {n: n for n in CHANNELS}
        self.duty = {n: 0 for n in CHANNELS}
        self.silent = set(silent)
        self.fail_after = fail_after
        self.down = down
        self.commands = []
        self.waits = []
        self.tach_name = {entities.FAN_SPEED[m]: m for m in CHANNELS}

    def fan(self, n, on, speed_level=None):
        if self.down and self.commands and self.commands[-1][0] == "fail":
            raise RigError("DUT API link is down; command to 'x' not sent")
        self.commands.append((n, on, speed_level))
        self.duty[n] = speed_level if on else 0

    def count(self, name):
        return 0

    def wait_fresh(self, name, after, n, deadline_s):
        self.waits.append((name, n, deadline_s))
        if self.fail_after is not None and len(self.waits) > self.fail_after:
            self.commands.append(("fail",))
            raise RigError("DUT API link is down; waiting ended")
        tach = self.tach_name[name]
        if tach in self.silent:
            return []
        reading = 0
        for fan, duty in self.duty.items():
            if self.wiring[fan] == tach and duty == 50:
                reading = qc.expected_reading(self.hz)
        return [PARTIAL] * qc.DISCARD_READINGS + [reading] * (n - qc.DISCARD_READINGS)


def test_measure_mapping_on_a_perfect_device_passes_and_drops_the_first_two_values():
    link = FakeLink()
    readings = qc.measure_mapping(link, HZ)
    assert qc.evaluate_mapping(HZ, readings) == []
    assert all(PARTIAL not in row for by_n in readings.values() for row in (r for n in by_n.values() for r in n.values()))


def test_two_values_are_dropped_because_the_transition_can_sit_in_the_second_one():
    """DUT A, first hardware run: fan 4's first kept value read 0.88 of the expected one."""
    assert qc.DISCARD_READINGS == 2


def test_measure_mapping_traces_what_it_dropped():
    trace = []
    qc.measure_mapping(FakeLink(), HZ, trace=trace)
    assert len(trace) == 3 * 4 * 4
    assert all(values == [PARTIAL, PARTIAL] for *_key, values in trace)
    assert trace[0][:3] == (50, 1, 1)


def test_measure_mapping_drives_1_2_3_4_with_everything_off_first_and_last():
    link = FakeLink()
    qc.measure_mapping(link, HZ)
    commands = link.commands
    assert commands[:4] == [(n, False, None) for n in CHANNELS]
    middle = commands[4:-4]
    assert middle == [step for n in CHANNELS for step in ((n, True, 50), (n, True, 100), (n, False, None))]
    assert commands[-4:] == [(n, False, None) for n in CHANNELS]
    assert link.duty == {n: 0 for n in CHANNELS}


def test_measure_mapping_waits_for_two_dropped_plus_two_kept_values_within_the_settle_deadline():
    link = FakeLink()
    qc.measure_mapping(link, HZ)
    steps = [w for w in link.waits if w[1] == qc.DISCARD_READINGS + qc.READINGS_PER_CHECK]
    assert len(steps) == 3 * 4 * 4  # duties x driven channels x tachs
    assert all(0 <= deadline <= qc.FAN_SETTLE_S for _name, _n, deadline in link.waits)


def test_measure_mapping_on_a_device_with_swapped_wiring_reports_the_swap():
    link = FakeLink(wiring={1: 2, 2: 1, 3: 3, 4: 4})
    problems = qc.evaluate_mapping(HZ, qc.measure_mapping(link, HZ))
    assert [p[:3] for p in problems] == [(50, 1, 1), (50, 1, 2), (50, 2, 1), (50, 2, 2)]


def test_measure_mapping_with_a_silent_tach_names_the_channel_and_never_reads_it_as_zero():
    link = FakeLink(silent={3})
    problems = qc.evaluate_mapping(HZ, qc.measure_mapping(link, HZ))
    assert problems
    assert {p[2] for p in problems} == {3}
    assert all(p[4] == "no fresh reading" for p in problems)
    assert {p[0] for p in problems} == {0, 50, 100}


def test_measure_mapping_turns_every_fan_off_when_the_measurement_is_cut_short():
    link = FakeLink(fail_after=10)
    with pytest.raises(RigError, match="waiting ended"):
        qc.measure_mapping(link, HZ)
    assert link.duty == {n: 0 for n in CHANNELS}


def test_a_link_that_cannot_switch_fans_off_is_a_rig_error_after_a_clean_run():
    class Stuck(FakeLink):
        def fan(self, n, on, speed_level=None):
            if len(self.commands) >= 4 + 12:
                raise RigError("DUT API link is down; command to 'x' not sent")
            super().fan(n, on, speed_level)

    with pytest.raises(RigError, match="fans not switched off"):
        qc.measure_mapping(Stuck(), HZ)
