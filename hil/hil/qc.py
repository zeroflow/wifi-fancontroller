"""QC measurements and their pure evaluators (D-27, D-28, D-31).

Fan channel mapping: one channel at a time is driven at 50 % duty and the tach of
every channel is read. The deciding functions are pure over the readings, so the
hosted unit suite covers them; measure_mapping is the only part that talks to a DUT.

Not widened, not retried: the band is D-28's +-10 % and a channel that fails stays
failed. A reading that never arrives is a problem, never a 0.
"""

import math
import re
import time
import tomllib
from pathlib import Path

from . import RigError, entities

MAPPING_TOLERANCE = 0.10
FAN_SETTLE_S = 15  # one phase (a duty step and the readings that follow it)
READINGS_PER_CHECK = 2
# Fresh values dropped after a command. Two, not one: the command can land just after a
# tach publish, so the first fresh value is a pure old-state window and the second one the
# partial window that holds the transition (seen on DUT A: 0.88 of the expected reading).
DISCARD_READINGS = 2
DUTIES = (50, 100, 0)
CHANNELS = entities.CHANNELS

# HDC1080 (D-29, QC-03): bounds are inclusive; two fresh readings of each sensor in one window.
HDC_WINDOW_S = 30
TEMP_RANGE_C = (5.0, 45.0)
HUMIDITY_RANGE = (10.0, 90.0)
HDC_READINGS = 2

# Framework (D-34, QC-05). The DUT's `QC Device Info` text sensor carries `|Framework: Arduino`
# or `|Framework: ESP-IDF`; only these two spellings map, every other one is a problem.
TEXT_SENSOR_WAIT_S = 10
FRAMEWORK_NAMES = {"Arduino": "arduino", "ESP-IDF": "esp-idf"}
FRAMEWORKS_TOML = Path(__file__).resolve().parents[1] / "frameworks.toml"
_FRAMEWORK_FIELD = re.compile(r"\|Framework: ([^|]*)")

# USR buttons (D-30, QC-04): the wait for each state the supervisor's line causes on the DUT.
USR_WAIT_S = 5

NO_FRESH = "no fresh reading"
CANARY_SWAP = (1, 2)  # the canary image swaps the PWM pins of these two fans (hil/rev3.2.canary.yaml)


def expected_reading(fan_hz):
    """Fan N Speed at 50 % duty: rising edges per minute x multiply 0.5 = PWM Hz x 30 (D-28)."""
    return fan_hz * 30


def _within(value, expected, tolerance):
    return abs(value - expected) <= tolerance * expected  # NaN compares False


def evaluate_mapping(fan_hz, readings, tolerance=MAPPING_TOLERANCE, channels=CHANNELS):
    """Problems of a mapping measurement; [] means every channel maps to its own tach.

    readings[duty][n][m] is the list of fresh values of channel m's tach while only channel n
    is driven at `duty`. At duty 50 the driven channel must read within `tolerance` of the
    expected value in every value and every other channel exactly 0; at 100 and 0 every channel
    must read exactly 0. Fewer than READINGS_PER_CHECK values (or an absent entry) is a problem
    with the reason "no fresh reading". Returns tuples (duty, n, m, values, reason) sorted by
    (duty, driven channel, read channel).
    """
    expected = expected_reading(fan_hz)
    problems = []
    for duty in DUTIES:
        for n in channels:
            for m in channels:
                values = list(readings.get(duty, {}).get(n, {}).get(m, []))
                if len(values) < READINGS_PER_CHECK:
                    problems.append((duty, n, m, values, NO_FRESH))
                elif duty == 50 and m == n:
                    if not all(_within(v, expected, tolerance) for v in values):
                        problems.append((duty, n, m, values, "outside +-%d %% of %d" % (round(tolerance * 100), expected)))
                elif not all(v == 0 for v in values):
                    problems.append((duty, n, m, values, "expected exactly 0"))
    return sorted(problems, key=lambda p: (p[0], p[1], p[2]))


def _numbers(readings):
    return [v for by_n in readings.values() for row in by_n.values() for values in row.values() for v in values]


def canary_detected(fan_hz, readings, tolerance=MAPPING_TOLERANCE):
    """(True, "fan 1 <-> fan 2 swap") only for the exact signature of the canary's fault (D-31).

    The mapping problems must be exactly the four duty-50 entries of the swapped pair: driving
    fan a reads the expected value on tach b and exactly 0 on tach a, and the other way round.
    Every other tach, every 100 % and 0 % reading must be clean. Anything else is not
    detection: an all-silent or dead-API device ("all channels silent"), a perfect device
    ("no swap seen"), another swap, an extra problem, a missing or NaN reading.
    """
    a, b = CANARY_SWAP
    problems = evaluate_mapping(fan_hz, readings, tolerance)
    values = _numbers(readings)
    if not values or all(v == 0 or v != v for v in values):
        return False, "all channels silent"
    if not problems:
        return False, "no swap seen"
    signature = [(50, a, a), (50, a, b), (50, b, a), (50, b, b)]
    if [p[:3] for p in problems] != signature or any(p[4] == NO_FRESH for p in problems):
        return False, "unexpected problems: " + format_problems(problems).replace("\n", "; ")
    expected = expected_reading(fan_hz)
    row = readings[50]
    shape = (
        all(_within(v, expected, tolerance) for v in row[a][b])
        and all(_within(v, expected, tolerance) for v in row[b][a])
        and all(v == 0 for v in row[a][a])
        and all(v == 0 for v in row[b][b])
    )
    if not shape:
        return False, "unexpected problems: " + format_problems(problems).replace("\n", "; ")
    return True, "fan %d <-> fan %d swap" % (a, b)


def readings_as_json(readings):
    """readings[duty][n][m] with string keys, for the JSON reports."""
    return {
        str(duty): {str(n): {str(m): list(values) for m, values in row.items()} for n, row in by_n.items()}
        for duty, by_n in readings.items()
    }


def format_problems(problems):
    return "\n".join(
        "duty %d %%, driven fan %d, tach %d: %s (values %s)" % (duty, n, m, reason, values)
        for duty, n, m, values, reason in problems
    )


def ratio_table(fan_hz, readings, channels=CHANNELS):
    """Per channel the 50 % record: own readings, expected, observed/expected, the others' readings."""
    expected = expected_reading(fan_hz)
    table = {}
    for n in channels:
        own = list(readings.get(50, {}).get(n, {}).get(n, []))
        ratio = round(sum(own) / len(own) / expected, 4) if own and all(v == v for v in own) else None
        others = {m: list(readings.get(50, {}).get(n, {}).get(m, [])) for m in channels if m != n}
        table[n] = {"own": own, "expected": expected, "ratio": ratio, "others": others}
    return table


def _drive(link, n, duty):
    if duty == 0:
        link.fan(n, False)
    else:
        link.fan(n, True, duty)


def _fans_off(link, channels, strict):
    failed = []
    for n in channels:
        try:
            link.fan(n, False)
        except RigError as exc:
            failed.append(str(exc))
    if failed and strict:
        raise RigError("fans not switched off: %s" % "; ".join(failed))


def measure_mapping(link, fan_hz, channels=CHANNELS, trace=None):
    """Drive each channel at 50 %, 100 % and off in turn and read every tach (D-28).

    Channels run in the order given with every other fan off. For each step the first
    DISCARD_READINGS fresh values of a tach after the command are dropped (one of them covers
    the transition) and the next READINGS_PER_CHECK are kept; one deadline of FAN_SETTLE_S
    covers the step. Every fan is switched off at the end, also when the measurement is cut
    short. `fan_hz` is not used here (the DUT is driven by duty alone); the evaluators take it.
    `trace`, when a list, receives (duty, n, m, dropped values) for the record.
    """
    tachs = {m: entities.FAN_SPEED[m] for m in channels}
    readings = {duty: {n: {} for n in channels} for duty in DUTIES}
    try:
        _fans_off(link, channels, strict=True)
        afters = {m: link.count(name) for m, name in tachs.items()}
        end = time.monotonic() + FAN_SETTLE_S
        for m, name in tachs.items():
            link.wait_fresh(name, afters[m], 1, end - time.monotonic())
        for n in channels:
            for duty in DUTIES:
                afters = {m: link.count(name) for m, name in tachs.items()}
                _drive(link, n, duty)
                end = time.monotonic() + FAN_SETTLE_S
                for m, name in tachs.items():
                    fresh = link.wait_fresh(
                        name, afters[m], DISCARD_READINGS + READINGS_PER_CHECK, end - time.monotonic()
                    )
                    readings[duty][n][m] = fresh[DISCARD_READINGS:]
                    if trace is not None:
                        trace.append((duty, n, m, fresh[:DISCARD_READINGS]))
    except BaseException:
        _fans_off(link, channels, strict=False)
        raise
    _fans_off(link, channels, strict=True)
    return readings


def _climate_problems(label, unit, values, bounds):
    problems = []
    if len(values) < HDC_READINGS:
        problems.append("%s: %d fresh reading(s), need %d" % (label, len(values), HDC_READINGS))
    low, high = bounds
    for value in values:
        if math.isnan(value):
            problems.append("%s: NaN" % label)
        elif not low <= value <= high:
            problems.append("%s: %g %s outside %g-%g" % (label, value, unit, low, high))
    return problems


def evaluate_climate(temps, hums):
    """Problems of an HDC1080 measurement (D-29); [] means plausible.

    At least two values of each sensor, none NaN, temperature inside TEMP_RANGE_C and humidity
    inside HUMIDITY_RANGE, bounds included. The result does not depend on the order in which the
    readings arrived: the problems are returned sorted.
    """
    problems = _climate_problems("temperature", "C", list(temps), TEMP_RANGE_C)
    problems += _climate_problems("humidity", "%RH", list(hums), HUMIDITY_RANGE)
    return sorted(problems)


def measure_climate(link, window_s=HDC_WINDOW_S):
    """Two fresh Temperature and two fresh Humidity readings under one overall deadline.

    The counters are taken first, so only messages that arrive from now on count. The two sensors
    publish on their own schedule, so the deadline is shared: whichever reading is late takes the
    time the other left over. Returns (temps, hums); a sensor that stayed silent gives a shorter
    list (never a made-up value), which evaluate_climate turns into a problem.
    """
    after_t = link.count(entities.TEMPERATURE)
    after_h = link.count(entities.HUMIDITY)
    end = time.monotonic() + window_s
    temps = link.wait_fresh(entities.TEMPERATURE, after_t, HDC_READINGS, end - time.monotonic())
    hums = link.wait_fresh(entities.HUMIDITY, after_h, HDC_READINGS, max(0.0, end - time.monotonic()))
    return temps, hums


def framework_from_device_info(text):
    """The framework a DUT reports in `QC Device Info`, as "arduino" or "esp-idf".

    ValueError, never a skip or a guess, for a missing or empty report, one without the
    `|Framework: ` field, or one whose value is not exactly "Arduino" or "ESP-IDF" (QC-05).
    """
    if not isinstance(text, str) or not text:
        raise ValueError("QC Device Info is missing or empty")
    found = _FRAMEWORK_FIELD.search(text)
    if found is None:
        raise ValueError("QC Device Info has no Framework field")
    name = found.group(1)
    if name not in FRAMEWORK_NAMES:
        raise ValueError("QC Device Info Framework value %r is not a known framework" % name)
    return FRAMEWORK_NAMES[name]


def framework_table(path=FRAMEWORKS_TOML):
    """The committed framework per board revision, e.g. {"3.2": "arduino", "4.0": "esp-idf", ...}.

    Indexing a revision that is not listed raises KeyError. A value other than the two framework
    names is refused here so a typo in the table cannot pass a matching typo elsewhere.
    """
    with open(path, "rb") as handle:
        revisions = tomllib.load(handle)["revisions"]
    for rev, framework in revisions.items():
        if framework not in FRAMEWORK_NAMES.values():
            raise ValueError("frameworks.toml: revision %s has an unknown framework" % rev)
    return dict(revisions)


def evaluate_framework(table, rig, device, manifest):
    """Problems of the four-way framework check; [] means all four are the same known name.

    Names compare exactly. The problem text lists the values in the fixed order table, rig.toml,
    device, manifest, so two failing runs read alike.
    """
    values = (table, rig, device, manifest)
    if len(set(values)) == 1 and table in FRAMEWORK_NAMES.values():
        return []
    return ["table=%s rig.toml=%s device=%s manifest=%s" % values]
