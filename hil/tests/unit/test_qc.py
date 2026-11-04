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


# ------------------------------------------------------------ canary_detected (D-31)


def swapped(hz=HZ, a=1, b=2):
    """A device whose fan a drives tach b and the other way round (the canary's fault)."""
    e = qc.expected_reading(hz)
    wiring = {n: n for n in CHANNELS}
    wiring[a], wiring[b] = b, a
    out = perfect(hz)
    for n in CHANNELS:
        for m in CHANNELS:
            out[50][n][m] = [e, e] if wiring[n] == m else [0, 0]
    return out


SWAP_TEXT = "fan 1 <-> fan 2 swap"


def test_canary_detected_on_the_exact_swap_signature():
    assert qc.canary_detected(HZ, swapped()) == (True, SWAP_TEXT)


def test_canary_swap_is_detected_at_1000_hz_too():
    assert qc.canary_detected(1000, swapped(1000)) == (True, SWAP_TEXT)


def test_the_swapped_fixture_has_exactly_the_four_swap_problems():
    assert [p[:3] for p in qc.evaluate_mapping(HZ, swapped())] == [(50, 1, 1), (50, 1, 2), (50, 2, 1), (50, 2, 2)]


def test_canary_not_detected_on_a_perfect_device():
    detected, text = qc.canary_detected(HZ, perfect())
    assert (detected, text) == (False, "no swap seen")


def test_canary_not_detected_on_an_all_zero_device():
    zero = {duty: {n: {m: [0, 0] for m in CHANNELS} for n in CHANNELS} for duty in qc.DUTIES}
    detected, text = qc.canary_detected(HZ, zero)
    assert detected is False and text == "all channels silent"


def test_canary_not_detected_on_a_swap_of_3_and_4():
    detected, text = qc.canary_detected(HZ, swapped(a=3, b=4))
    assert detected is False and text.startswith("unexpected problems:")


def test_canary_not_detected_when_the_swap_comes_with_a_nonzero_100_percent_reading():
    detected, text = qc.canary_detected(HZ, with_value(swapped(), 100, 3, 3, [0, 9]))
    assert detected is False and text.startswith("unexpected problems:") and "duty 100" in text


def test_canary_not_detected_when_a_reading_is_missing():
    for readings in (
        with_value(swapped(), 50, 3, 3, [E]),
        with_value(swapped(), 50, 1, 2, []),
        with_value(swapped(), 0, 4, 4, []),
    ):
        detected, text = qc.canary_detected(HZ, readings)
        assert detected is False and "no fresh reading" in text


def test_canary_not_detected_when_the_cross_reading_is_out_of_band_or_the_own_tach_is_not_silent():
    # fan 1 drives tach 2 only at half the expected value: a different fault, not the swap
    half = with_value(swapped(), 50, 1, 2, [E // 2, E // 2])
    assert qc.canary_detected(HZ, half)[0] is False
    # fan 1 still reads 1 on its own tach: not the clean swap signature
    leak = with_value(swapped(), 50, 1, 1, [0, 1])
    assert qc.canary_detected(HZ, leak)[0] is False


def test_canary_not_detected_on_nan_readings():
    nan = float("nan")
    assert qc.canary_detected(HZ, with_value(swapped(), 50, 2, 1, [nan, nan]))[0] is False
    all_nan = {duty: {n: {m: [nan, nan] for m in CHANNELS} for n in CHANNELS} for duty in qc.DUTIES}
    assert qc.canary_detected(HZ, all_nan)[0] is False


def test_canary_not_detected_on_the_real_wiring_with_a_dead_tach():
    dead = perfect()
    dead[50][2][2] = [0, 0]
    detected, text = qc.canary_detected(HZ, dead)
    assert detected is False and text.startswith("unexpected problems:")


def test_canary_detection_is_the_only_place_that_knows_the_swap_pair():
    assert qc.CANARY_SWAP == (1, 2)


def test_readings_as_json_has_string_keys_and_survives_a_json_round_trip():
    import json

    data = qc.readings_as_json(swapped())
    assert sorted(data) == ["0", "100", "50"]
    assert json.loads(json.dumps(data))["50"]["1"]["2"] == [E, E]


def test_no_rig_test_marks_anything_as_an_expected_failure():
    """D-31: the canary test passes on detection; nothing in the suite may use xfail."""
    import ast
    from pathlib import Path

    tests = Path(__file__).resolve().parents[1]
    offenders = []
    for path in sorted(tests.rglob("*.py")):
        if path == Path(__file__).resolve():
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute) and node.attr == "xfail":
                offenders.append("%s:%d" % (path.relative_to(tests), node.lineno))
    assert not offenders, ", ".join(offenders)


def test_the_canary_test_passes_only_through_canary_detected():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "rig" / "test_30_canary.py").read_text(encoding="utf-8")
    assert "qc.canary_detected(" in source and "assert detected" in source


# ---- HDC1080 (QC-03, D-29) ----

T = [22.5, 22.6]
H = [40.0, 41.0]


def test_hdc_constants_are_the_decided_ones():
    assert qc.HDC_WINDOW_S == 30
    assert qc.TEMP_RANGE_C == (5.0, 45.0)
    assert qc.HUMIDITY_RANGE == (10.0, 90.0)


def test_plausible_climate_has_no_problems():
    assert qc.evaluate_climate(T, H) == []


@pytest.mark.parametrize("temps", [[5.0, 5.0], [45.0, 45.0], [5.0, 45.0]])
def test_temperature_bounds_are_inclusive(temps):
    assert qc.evaluate_climate(temps, H) == []


@pytest.mark.parametrize("hums", [[10.0, 10.0], [90.0, 90.0], [10.0, 90.0]])
def test_humidity_bounds_are_inclusive(hums):
    assert qc.evaluate_climate(T, hums) == []


@pytest.mark.parametrize("value", [4.9, 45.1])
def test_temperature_just_outside_fails(value):
    problems = qc.evaluate_climate([22.0, value], H)
    assert len(problems) == 1 and problems[0].startswith("temperature:")


@pytest.mark.parametrize("value", [9.9, 90.1])
def test_humidity_just_outside_fails(value):
    problems = qc.evaluate_climate(T, [50.0, value])
    assert len(problems) == 1 and problems[0].startswith("humidity:")


def test_nan_fails_for_either_sensor():
    assert any("NaN" in p for p in qc.evaluate_climate([22.0, float("nan")], H))
    assert any("NaN" in p for p in qc.evaluate_climate(T, [float("nan"), 50.0]))


@pytest.mark.parametrize("temps,hums", [([], H), ([22.0], H), (T, []), (T, [50.0]), ([], [])])
def test_fewer_than_two_readings_of_either_sensor_fails(temps, hums):
    assert any("need 2" in p for p in qc.evaluate_climate(temps, hums))


def test_reading_order_does_not_change_the_result():
    bad = [22.0, 4.9, float("nan")]
    forward = qc.evaluate_climate(bad, [95.0, 50.0])
    backward = qc.evaluate_climate(list(reversed(bad)), [50.0, 95.0])
    assert forward == backward and forward == sorted(forward) and forward


class ClimateLink:
    def __init__(self, temps=None, hums=None, clock=None):
        self.temps = T if temps is None else temps
        self.hums = H if hums is None else hums
        self.counted = []
        self.waits = []

    def count(self, name):
        self.counted.append(name)
        return 7

    def wait_fresh(self, name, after, n, deadline_s):
        self.waits.append((name, after, n, deadline_s))
        return list(self.temps if name == entities.TEMPERATURE else self.hums)[:n]


def test_measure_climate_counts_first_and_asks_for_two_of_each_inside_one_window():
    link = ClimateLink()
    temps, hums = qc.measure_climate(link)
    assert (temps, hums) == (T, H)
    assert set(link.counted) == {entities.TEMPERATURE, entities.HUMIDITY}
    assert [w[:3] for w in link.waits] == [(entities.TEMPERATURE, 7, 2), (entities.HUMIDITY, 7, 2)]
    first, second = link.waits[0][3], link.waits[1][3]
    assert 0 < second <= first <= qc.HDC_WINDOW_S  # one shared deadline, never a second full window


def test_a_silent_sensor_gives_a_short_list_and_a_problem_not_a_value():
    link = ClimateLink(hums=[])
    temps, hums = qc.measure_climate(link)
    assert hums == []
    assert qc.evaluate_climate(temps, hums) == ["humidity: 0 fresh reading(s), need 2"]


# ---------------------------------------------------------------- framework (QC-05, D-34)

INFO_ARDUINO = "ESPHome 2026.10.1|Board: lolin_s2_mini|Framework: Arduino|Reset: Power-on"
INFO_IDF = "ESPHome 2026.10.1|Framework: ESP-IDF|Reset: Software"


def test_framework_names_map_exactly_two_spellings():
    assert qc.FRAMEWORK_NAMES == {"Arduino": "arduino", "ESP-IDF": "esp-idf"}
    assert qc.TEXT_SENSOR_WAIT_S == 10


def test_device_info_with_arduino_reads_arduino():
    assert qc.framework_from_device_info(INFO_ARDUINO) == "arduino"


def test_device_info_with_esp_idf_reads_esp_idf():
    assert qc.framework_from_device_info(INFO_IDF) == "esp-idf"


def test_the_field_at_the_end_of_the_text_reads_too():
    assert qc.framework_from_device_info("x|Framework: Arduino") == "arduino"


@pytest.mark.parametrize(
    "text, word",
    [
        ("", "empty"),
        (None, "missing"),
        (float("nan"), "missing"),
        ("ESPHome 2026.10.1|Reset: Power-on", "no Framework field"),
        ("|Framework: arduino|", "not a known framework"),
        ("|Framework: ARDUINO|", "not a known framework"),
        ("|Framework: esp-idf|", "not a known framework"),
        ("|Framework: Arduino |", "not a known framework"),
        ("|Framework: |", "not a known framework"),
        ("|Framework: PlatformIO|", "not a known framework"),
    ],
)
def test_a_missing_empty_or_malformed_report_is_a_value_error_naming_the_problem(text, word):
    with pytest.raises(ValueError, match=word):
        qc.framework_from_device_info(text)


def test_four_equal_values_are_no_problem():
    assert qc.evaluate_framework("arduino", "arduino", "arduino", "arduino") == []
    assert qc.evaluate_framework("esp-idf", "esp-idf", "esp-idf", "esp-idf") == []


def test_one_disagreeing_value_gives_one_problem_in_the_fixed_order():
    assert qc.evaluate_framework("arduino", "arduino", "esp-idf", "arduino") == [
        "table=arduino rig.toml=arduino device=esp-idf manifest=arduino"
    ]


@pytest.mark.parametrize("position", range(4))
def test_each_of_the_four_values_can_be_the_odd_one_out(position):
    values = ["arduino"] * 4
    values[position] = "esp-idf"
    (problem,) = qc.evaluate_framework(*values)
    assert problem == "table=%s rig.toml=%s device=%s manifest=%s" % tuple(values)


@pytest.mark.parametrize("wrong", ["Arduino", "ESP-IDF", "esp_idf", "espidf", "", None])
def test_any_other_spelling_is_a_mismatch(wrong):
    assert len(qc.evaluate_framework("arduino", "arduino", wrong, "arduino")) == 1
    assert len(qc.evaluate_framework(wrong, "arduino", "arduino", "arduino")) == 1


def test_four_equal_but_unknown_names_are_still_a_problem():
    assert qc.evaluate_framework("Arduino", "Arduino", "Arduino", "Arduino") == [
        "table=Arduino rig.toml=Arduino device=Arduino manifest=Arduino"
    ]


def test_the_committed_table_has_rev_3_2_as_arduino_and_rev_4_0_as_esp_idf():
    table = qc.framework_table()
    assert table["3.2"] == "arduino" and table["4.0"] == "esp-idf"
    assert table["1.0"] == "esp-idf"


def test_a_revision_missing_from_the_table_is_a_key_error():
    with pytest.raises(KeyError):
        qc.framework_table()["9.9"]


def test_framework_table_reads_the_given_file(tmp_path):
    path = tmp_path / "frameworks.toml"
    path.write_text('schema = 1\n[revisions]\n"3.2" = "arduino"\n')
    assert qc.framework_table(path) == {"3.2": "arduino"}


def test_a_table_without_revisions_or_with_an_unknown_framework_is_refused(tmp_path):
    path = tmp_path / "frameworks.toml"
    path.write_text("schema = 1\n")
    with pytest.raises(KeyError):
        qc.framework_table(path)
    path.write_text('schema = 1\n[revisions]\n"3.2" = "Arduino"\n')
    with pytest.raises(ValueError, match="3.2"):
        qc.framework_table(path)


# ---------------------------------------------------------------- USR buttons (QC-04, D-30)


def test_usr_wait_is_five_seconds():
    assert qc.USR_WAIT_S == 5


@pytest.mark.parametrize("pressed", [1, 2, 3])
def test_only_the_pressed_button_on_is_no_problem(pressed):
    states = {n: n == pressed for n in (1, 2, 3)}
    assert qc.evaluate_buttons(pressed, states) == []


def test_the_pressed_button_off_is_one_problem():
    (problem,) = qc.evaluate_buttons(2, {1: False, 2: False, 3: False})
    assert "USR2" in problem and "OFF" in problem


def test_another_button_on_is_one_problem_for_each():
    problems = qc.evaluate_buttons(2, {1: True, 2: True, 3: True})
    assert len(problems) == 2
    assert "USR1" in problems[0] and "USR3" in problems[1]


def test_the_pressed_one_off_and_another_on_are_two_problems():
    assert len(qc.evaluate_buttons(1, {1: False, 2: True, 3: False})) == 2


@pytest.mark.parametrize("missing", [None, float("nan")])
def test_a_button_without_a_reading_is_a_problem_never_off(missing):
    assert len(qc.evaluate_buttons(2, {1: False, 2: True, 3: missing})) == 1
    assert len(qc.evaluate_buttons(2, {1: False, 2: missing, 3: False})) == 1


def test_an_absent_button_is_a_problem():
    assert len(qc.evaluate_buttons(2, {1: False, 2: True})) == 1


def test_a_value_that_is_not_a_boolean_is_not_on_or_off():
    assert len(qc.evaluate_buttons(2, {1: 0, 2: 1, 3: False})) == 2


class UsrRig:
    """A supervisor and a DUT link in one fake: holding a line makes that button ON on the DUT."""

    def __init__(self, stuck_on=(), silent=(), fail_wait_on=None):
        self.values = {n: (n in stuck_on) for n in (1, 2, 3)}
        self.held = set()
        self.max_held = 0
        self.calls = []
        self.silent = set(silent)
        self.fail_wait_on = fail_wait_on
        self.lines = {"line%d" % n: n for n in (1, 2, 3)}

    # supervisor
    def set_switch(self, name, on):
        self.calls.append((name, bool(on)))
        n = self.lines[name]
        if on:
            self.held.add(name)
            self.max_held = max(self.max_held, len(self.held))
            if n not in self.silent:
                self.values[n] = True
        else:
            self.held.discard(name)
            if n not in self.silent:
                self.values[n] = False

    # DUT link
    def value(self, name):
        return self.values[_number(name)]

    def wait_value(self, name, predicate, deadline_s):
        if self.fail_wait_on is not None and self.fail_wait_on(self):
            raise TimeoutError("test timeout")
        value = self.values[_number(name)]
        return value if value is not None and predicate(value) else None


def _number(name):
    return {v: k for k, v in entities.BUTTON_USR.items()}[name]


def test_measure_usr_presses_reads_the_others_and_releases():
    rig = UsrRig()
    result = qc.measure_usr(rig, "line2", rig, 2)
    assert result == {"before": False, "states": {1: False, 2: True, 3: False}, "released": False}
    assert rig.calls == [("line2", True), ("line2", False), ("line2", False)]
    assert qc.evaluate_buttons(2, result["states"]) == []


def test_measure_usr_never_holds_two_lines_across_the_three_buttons():
    rig = UsrRig()
    for n in (1, 2, 3):
        qc.measure_usr(rig, "line%d" % n, rig, n)
    assert rig.max_held == 1 and rig.held == set()


def test_measure_usr_releases_the_line_when_a_wait_is_cut_short():
    rig = UsrRig(fail_wait_on=lambda r: bool(r.held))  # the timeout lands while the line is held
    with pytest.raises(TimeoutError):
        qc.measure_usr(rig, "line1", rig, 1)
    assert rig.held == set() and rig.calls[-1] == ("line1", False)


def test_measure_usr_releases_the_line_when_the_dut_never_reports_the_press():
    rig = UsrRig(silent={3})
    result = qc.measure_usr(rig, "line3", rig, 3)
    assert result["states"][3] is None and result["released"] is False
    assert rig.held == set()
    assert qc.evaluate_buttons(3, result["states"])


def test_measure_usr_does_not_press_when_the_button_is_not_off_before():
    rig = UsrRig(stuck_on={2})
    result = qc.measure_usr(rig, "line2", rig, 2)
    assert result["before"] is None and result["states"] == {} and result["released"] is None
    assert rig.calls == []  # a stale ON could not tell a press from the old state


def test_measure_usr_reports_another_button_on_while_one_is_pressed():
    rig = UsrRig(stuck_on={3})
    result = qc.measure_usr(rig, "line1", rig, 1)
    assert result["states"] == {1: True, 2: False, 3: True}
    assert len(qc.evaluate_buttons(1, result["states"])) == 1
