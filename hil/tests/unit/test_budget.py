"""Reset budget (HARN-12): a fake clock, no hardware."""

import json

import pytest

from hil import RigError, budget, contract
from hil.budget import ResetBudget, ResetBudgetExhausted, SafeModeError

LABEL_A = contract.SERIAL_CONNECTED["A"].removesuffix(" Serial Connected")
LABEL_B = contract.SERIAL_CONNECTED["B"].removesuffix(" Serial Connected")


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture
def clock():
    return Clock()


def make(clock, **kwargs):
    return ResetBudget(clock=clock, **kwargs)


def test_the_policy_numbers_are_below_the_firmwares_ten_attempts():
    assert (budget.RESET_BUDGET_LIMIT, budget.RESET_DECAY_S) == (8, 70)
    assert ResetBudget().limit == 8 and ResetBudget().decay_s == 70


def test_eight_rapid_boots_exhaust_the_budget_before_the_ninth_press(clock):
    b = make(clock)
    for _ in range(8):
        b.before_reset()
        b.record("en_reset")
        clock.advance(10)
    assert b.streak() == 8
    with pytest.raises(ResetBudgetExhausted, match=r"8/8 boots less than 70 s apart \(en_reset x8\)") as caught:
        b.before_reset()
    assert str(caught.value).startswith(LABEL_A + " reset budget exhausted")


def test_seven_rapid_boots_still_allow_one_more_press(clock):
    b = make(clock)
    for _ in range(7):
        b.record("en_reset")
        clock.advance(10)
    b.before_reset()


def test_a_gap_of_71_seconds_resets_the_streak(clock):
    b = make(clock)
    for _ in range(5):
        b.record("en_reset")
        clock.advance(10)
    assert b.streak() == 5
    clock.advance(61)  # 71 s since the last boot: that boot stayed up
    assert b.streak() == 0
    b.record("en_reset")
    assert b.streak() == 1


def test_a_gap_of_exactly_the_decay_clears_and_one_second_less_does_not(clock):
    b = make(clock)
    b.record("en_reset")
    clock.advance(69)
    b.record("en_reset")
    assert b.streak() == 2
    clock.advance(70)
    b.record("en_reset")
    assert b.streak() == 1


def test_an_exhausted_budget_recovers_when_the_dut_stays_up(clock):
    b = make(clock)
    for _ in range(8):
        b.record("en_reset")
        clock.advance(1)
    with pytest.raises(ResetBudgetExhausted):
        b.before_reset()
    clock.advance(70)
    b.before_reset()


def test_an_orderly_boot_clears_the_streak_and_starts_a_new_one(clock):
    b = make(clock)
    for _ in range(6):
        b.record("en_reset")
        clock.advance(5)
    b.record("ota_reboot", orderly=True)
    assert b.streak() == 1
    b.before_reset()


def test_report_lists_every_boot_in_order_with_cause_and_time(clock):
    b = make(clock)
    b.record("flash_reset")
    clock.advance(12.34)
    b.record("ota_reboot", orderly=True)
    clock.advance(1)
    b.record("safe_mode_reboot", orderly=True)
    clock.advance(1)
    b.record("en_reset")
    report = b.report()
    assert report["limit"] == 8 and report["decay_s"] == 70 and report["used"] == 4 and report["streak"] == 2
    assert [(x["cause"], x["t"]) for x in report["boots"]] == [
        ("flash_reset", 0.0),
        ("ota_reboot", 12.3),
        ("safe_mode_reboot", 13.3),
        ("en_reset", 14.3),
    ]
    json.dumps(report)  # it is written to reports/budget-dut-a.json


def test_an_unknown_cause_is_a_programming_error(clock):
    with pytest.raises(ValueError, match="unknown boot cause"):
        make(clock).record("power_cycle")


def test_both_errors_are_rig_errors_not_firmware_failures():
    for cls in (ResetBudgetExhausted, SafeModeError):
        assert issubclass(cls, RigError) and not issubclass(cls, AssertionError)


def test_the_message_names_the_causes_of_the_streak_in_order_of_first_appearance(clock):
    b = make(clock, limit=3, label=LABEL_B)
    b.record("flash_reset")
    b.record("en_reset")
    b.record("en_reset")
    with pytest.raises(ResetBudgetExhausted, match=LABEL_B + r" reset budget exhausted: 3/3 .*\(flash_reset x1, en_reset x2\)"):
        b.before_reset()


def test_a_forced_boot_is_marked_in_the_report_and_counts_like_any_other(clock):
    b = make(clock)
    b.record("ota_reboot", orderly=True)
    clock.advance(7)
    b.record("en_reset", forced=True)
    assert b.report()["boots"] == [{"cause": "ota_reboot", "t": 0.0}, {"cause": "en_reset", "t": 7.0, "forced": True}]
    assert b.streak() == 2


# The planned Phase 3 run (03-13, engineer-arming) at nominal spacing, seconds since the session start (runs S1/S2
# of 03-13 for the existing legs; the rollback legs added at their measured lengths: transfer about 28 s, boot 5 s,
# the forced reset about 7 s after the OTA, the mark 61 s).
PLANNED_RUN = [
    (74.0, "flash_reset", False),  # test_10: release baseline flash
    (112.5, "ota_reboot", True),  # test_11: release -> commit
    (262.0, "flash_reset", False),  # test_12: serial restore
    (320.5, "ota_reboot", True),  # test_20: commit -> qc-auto
    (403.1, "safe_mode_reboot", True),  # test_25: the safe-mode button
    (405.0, "en_reset", False),  # test_25: leaving safe mode
    (439.1, "ota_reboot", True),  # test_30: qc-auto -> canary
    (523.5, "ota_reboot", True),  # test_36: canary -> commit (rollback_fresh)
    (530.5, "en_reset", False),  # test_36: the forced reset before the mark
    (575.0, "ota_reboot", True),  # test_37: canary -> commit (rollback_marked)
    (640.0, "en_reset", False),  # test_37: the guarded reset after the mark
    (660.0, "ota_reboot", True),  # test_40: commit -> broken
    (810.0, "flash_reset", False),  # test_41: UART recovery
]


def test_the_planned_phase_3_run_never_has_more_than_three_unclean_boots_in_a_row(clock):
    """RESEARCH Pitfall 19, STATE blocker: RESET_DECAY_S stays 70 s. Every press of the planned run passes
    before_reset, and the streak never goes above 3 against the limit of 8."""
    b = make(clock)
    start = clock.now
    highest = 0
    for t, cause, orderly in PLANNED_RUN:
        clock.now = start + t
        if cause in ("en_reset", "flash_reset"):
            b.before_reset()  # raises ResetBudgetExhausted if the plan ever reached the limit
        b.record(cause, orderly=orderly)
        highest = max(highest, b.streak())
    assert highest <= 3 < budget.RESET_BUDGET_LIMIT == 8
    assert budget.RESET_DECAY_S == 70
    assert b.report()["used"] == len(PLANNED_RUN)
