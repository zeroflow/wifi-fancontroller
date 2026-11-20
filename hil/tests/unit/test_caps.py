"""Capability vocabulary, matching and skip reasons (HARN-02, D-33)."""

import pytest

from hil import caps
from hil.config import DutConfig, RigConfig


def dut(capabilities=(), dut_id="A"):
    return DutConfig(id=dut_id, rev="3.2", chip="esp32s2", host="192.0.2.20", mac="02:00:00:00:00:0a", capabilities=tuple(capabilities))


def rig(**by_id):
    return RigConfig("192.0.2.10", "k", {i: dut(c, i) for i, c in by_id.items()}, "d")


def test_vocabulary_is_the_runner_contract():
    assert caps.VOCABULARY == ("fan_tach_bridge", "hdc1080", "usr1", "usr2", "usr3")
    assert caps.FRAMEWORKS == ("arduino", "esp-idf")


@pytest.mark.parametrize("name", ["usr10", "USR1", " usr1", "usr1 ", "hdc_1080", "", "usr"])
def test_names_compare_exactly_against_the_vocabulary(name):
    assert caps.unknown([name]) == [name]
    assert caps.missing(dut(["usr1", "hdc1080"]), [name]) == [name]


def test_unknown_keeps_input_order_and_ignores_known_names():
    assert caps.unknown(["usr3", "usr10", "hdc1080", "USR1"]) == ["usr10", "USR1"]


def test_a_non_string_is_unknown_not_a_crash():
    assert caps.unknown([1, None]) == [1, None]


def test_missing_keeps_the_marker_order_not_the_vocabulary_order():
    assert caps.missing(dut(["usr2"]), ["usr3", "usr1", "usr2", "hdc1080"]) == ["usr3", "usr1", "hdc1080"]


def test_a_name_listed_twice_in_a_marker_is_reported_once():
    assert caps.missing(dut([]), ["usr1", "usr1"]) == ["usr1"]


def test_a_dut_with_every_required_capability_misses_nothing():
    assert caps.missing(dut(["hdc1080", "usr1"]), ["usr1", "hdc1080"]) == []


def test_an_empty_capability_list_misses_every_required_name():
    assert caps.missing(dut([]), ["hdc1080", "usr1"]) == ["hdc1080", "usr1"]


def test_skip_reason_names_every_missing_capability_in_order():
    assert caps.skip_reason("A", ["usr3", "hdc1080"]) == "DUT %s (rig.toml) lacks capability: usr3, hdc1080" % "A"


def test_empty_capabilities_skip_reason_for_each_required_name():
    reason = caps.skip_reason("A", caps.missing(dut([]), ["fan_tach_bridge", "hdc1080"]))
    assert "fan_tach_bridge" in reason and "hdc1080" in reason


def test_select_dut_returns_the_duts_that_meet_the_requirement():
    r = rig(A=["hdc1080", "usr1"], B=[])
    assert caps.select_dut(r, ["hdc1080"]) == ["A"]
    assert caps.select_dut(r, ["hdc1080", "usr2"]) == []
    assert caps.select_dut(r, []) == ["A", "B"]
