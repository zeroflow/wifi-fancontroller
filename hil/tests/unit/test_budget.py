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
