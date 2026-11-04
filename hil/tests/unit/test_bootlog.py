"""Boot-log gate parsing, on synthetic text only."""

from hil import bootlog

ESC = "\x1b"


def test_ansi_coloured_error_line_is_found():
    text = "%s[0;31m[E][rmt:123]: synthetic failure%s[0m\r\n" % (ESC, ESC)
    assert bootlog.error_lines(text) == ["[E][rmt:123]: synthetic failure"]


def test_warning_and_debug_lines_are_ignored():
    text = (
        "%s[0;33m[W][wifi:45]: synthetic warning%s[0m\r\n"
        "%s[0;36m[D][sensor:7]: synthetic debug%s[0m\r\n"
        "%s[0;32m[I][app:1]: synthetic info%s[0m\r\n" % (ESC, ESC, ESC, ESC, ESC, ESC)
    )
    assert bootlog.error_lines(text) == []


def test_second_stage_bootloader_error_is_found():
    text = "E (123) boot: synthetic bootloader failure\r\nI (130) boot: fine\r\n"
    assert bootlog.error_lines(text) == ["E (123) boot: synthetic bootloader failure"]


def test_boot_banner_found_for_s2_normal_boot():
    text = "ESP-ROM:esp32s2-rc4-20191025\r\nrst:0x1 (POWERON),boot:0x8 (SPI_FAST_FLASH_BOOT)\r\n"
    assert bootlog.has_boot_banner(text, "esp32s2")


def test_boot_banner_found_for_c6_normal_boot():
    assert bootlog.has_boot_banner("rst:0x1 (POWERON),boot:0x6f (SPI_FAST_FLASH_BOOT)\r\n", "esp32c6")


def test_download_mode_is_not_a_normal_boot_banner():
    assert not bootlog.has_boot_banner("rst:0x1 (POWERON),boot:0x0 (DOWNLOAD(USB/UART0))\r\n", "esp32s2")


def test_empty_text_has_no_banner_and_no_error_lines():
    assert bootlog.error_lines("") == []
    assert not bootlog.has_boot_banner("", "esp32s2")


def test_carriage_return_only_line_endings_split_correctly():
    text = "[I][app:1]: one\r[E][x:2]: two\r[I][app:3]: three\r"
    assert bootlog.lines(text) == ["[I][app:1]: one", "[E][x:2]: two", "[I][app:3]: three"]
    assert bootlog.error_lines(text) == ["[E][x:2]: two"]


def test_unknown_chip_is_a_rig_error():
    import pytest

    from hil import RigError

    with pytest.raises(RigError):
        bootlog.has_boot_banner("boot:0x8", "esp32")


def test_idf_error_forwarded_through_esphome_debug_log_is_found():
    text = (
        "%s[0;36m[D][esp-idf:000]: E (641) rmt: synthetic: no free tx channels%s[0m\r\n"
        "%s[0;36m[D][esp-idf:000]: I (642) rmt: synthetic info%s[0m\r\n" % (ESC, ESC, ESC, ESC)
    )
    assert bootlog.error_lines(text) == ["[D][esp-idf:000]: E (641) rmt: synthetic: no free tx channels"]


def test_debug_line_that_merely_mentions_an_error_is_not_an_error_line():
    assert bootlog.error_lines("[D][app:1]: the E (1) marker appears mid-line only\r\n") == []
