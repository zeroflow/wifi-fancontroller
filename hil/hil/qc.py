"""QC measurements and their pure evaluators (D-27, D-28, D-31).

Fan channel mapping: one channel at a time is driven at 50 % duty and the tach of
every channel is read. The deciding functions are pure over the readings, so the
hosted unit suite covers them; measure_mapping is the only part that talks to a DUT.

Not widened, not retried: the band is D-28's +-10 % and a channel that fails stays
failed. A reading that never arrives is a problem, never a 0.
"""

import time

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

NO_FRESH = "no fresh reading"


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
