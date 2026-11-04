"""A DUT that crashes or reboots during a test is the firmware's outcome (FAIL); a silent rig stays a RigError (D-46, WR-01).

Fakes only: a scripted UART0 tap, a stubbed API probe and port check, a fake clock. Real
timing, sockets and hardware are not involved.
"""

import pytest
from test_dut_state import BOOT, FakeClock, make_dut

from hil import FirmwareFailure, RigError, dutlink, entities
from hil import dut as dut_module
from hil.budget import SafeModeError

CHIP = "esp32s2"


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(dut_module, "time", fake)
    return fake


def silent_dut(clock, monkeypatch, *, ports=(False, False)):
    """A Dut whose API probe always fails; `ports` = (ota open, api open) for the safe-mode port check."""
    device, tap, _sv = make_dut()

    def probe(noise_psk):
        raise RigError("attempt timed out")

    device.probe = probe
    monkeypatch.setattr(device, "_port_open", lambda port: ports[0] if port == dut_module.OTA_PORT else ports[1])
    tap.mark("since")
    return device, tap


def test_a_booted_dut_whose_api_never_answers_is_a_firmware_failure(clock, monkeypatch):
    device, tap = silent_dut(clock, monkeypatch)
    tap.feed(BOOT)
    with pytest.raises(FirmwareFailure, match=r"booted after since .*within 5s"):
        device.wait_running("k", "since", deadline_s=5)


def test_no_boot_banner_at_all_stays_a_rig_error_with_the_old_message(clock, monkeypatch):
    device, _tap = silent_dut(clock, monkeypatch)
    with pytest.raises(RigError, match=r"DUT A API did not answer within 5s \(last: no ROM boot banner since since\)") as caught:
        device.wait_running("k", "since", deadline_s=5)
    assert not isinstance(caught.value, FirmwareFailure)


def test_open_ota_port_with_a_closed_api_port_is_still_safe_mode(clock, monkeypatch):
    device, tap = silent_dut(clock, monkeypatch, ports=(True, False))
    tap.feed(BOOT)
    with pytest.raises(SafeModeError):
        device.wait_running("k", "since", deadline_s=5)


# ---- DutLink: the link is down at a wait's deadline ------------------------------------------


class LinkTap:
    """Just enough tap for DutLink: text since a mark."""

    def __init__(self, text=""):
        self.buffer = text
        self.asked = []

    def text(self, since, until=None):
        self.asked.append(since)
        return self.buffer


@pytest.fixture
def down_link(monkeypatch):
    """A DutLink that never connects (nothing listens), with an injectable tap."""
    monkeypatch.setattr(dutlink, "RECONNECT_S", 0.05)

    class Refusing:
        def __init__(self, *args, **kwargs):
            pass

        async def connect(self, **kwargs):
            raise dutlink.APIConnectionError("refused")

        async def disconnect(self, force=False):
            pass

    monkeypatch.setattr(dutlink, "APIClient", Refusing)
    made = []

    def build(**kwargs):
        link = dutlink.DutLink("192.0.2.1", "key", **kwargs)
        link.start()
        made.append(link)
        return link

    yield build
    for link in made:
        link.close()


WAITS = {
    "wait_connected": lambda link: link.wait_connected(0.2),
    "wait_fresh": lambda link: link.wait_fresh(entities.FAN_SPEED[1], 0, 1, 0.2),
    "wait_value": lambda link: link.wait_value(entities.FAN_SPEED[1], lambda v: True, 0.2),
}


@pytest.mark.parametrize("wait", sorted(WAITS))
def test_a_rom_banner_since_the_test_start_turns_a_down_link_into_a_firmware_failure(down_link, wait):
    link = down_link(tap=LinkTap(BOOT), chip=CHIP)
    link.crash_mark = "test_start_7"
    with pytest.raises(FirmwareFailure, match="rebooted during the test"):
        WAITS[wait](link)


@pytest.mark.parametrize("wait", sorted(WAITS))
def test_without_a_banner_the_down_link_stays_a_rig_error(down_link, wait):
    link = down_link(tap=LinkTap("[I][app:1]: only application lines\r\n"), chip=CHIP)
    link.crash_mark = "test_start_7"
    with pytest.raises(RigError) as caught:
        WAITS[wait](link)
    assert not isinstance(caught.value, FirmwareFailure)


@pytest.mark.parametrize("wait", sorted(WAITS))
def test_without_a_crash_mark_the_down_link_stays_a_rig_error(down_link, wait):
    link = down_link(tap=LinkTap(BOOT), chip=CHIP)  # a banner, but no mark to measure it from
    with pytest.raises(RigError) as caught:
        WAITS[wait](link)
    assert not isinstance(caught.value, FirmwareFailure)


@pytest.mark.parametrize("wait", sorted(WAITS))
def test_without_a_tap_the_down_link_stays_a_rig_error(down_link, wait):
    link = down_link()
    link.crash_mark = "test_start_7"
    with pytest.raises(RigError) as caught:
        WAITS[wait](link)
    assert not isinstance(caught.value, FirmwareFailure)


def test_the_crash_check_reads_the_tap_from_the_crash_mark(down_link):
    tap = LinkTap(BOOT)
    link = down_link(tap=tap, chip=CHIP)
    link.crash_mark = "test_start_9"
    with pytest.raises(FirmwareFailure):
        link.wait_connected(0.1)
    assert set(tap.asked) == {"test_start_9"}
