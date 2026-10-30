"""NVS capture and restore: partition table parsing and the capture ordering rules (no hardware)."""

import hashlib
import os
import stat
import struct
from types import SimpleNamespace

import pytest

from hil import RigError, nvs

NVS_OFFSET = 0x3A0000
NVS_SIZE = 0x60000

# v1.6.0 layout (RESEARCH P1): label, type, subtype, offset, size
V160 = [
    ("otadata", 1, 0x00, 0x9000, 0x2000),
    ("phy_init", 1, 0x01, 0xB000, 0x1000),
    ("app0", 0, 0x10, 0x10000, 0x1C0000),
    ("app1", 0, 0x11, 0x1D0000, 0x1C0000),
    ("eeprom", 1, 0x99, 0x390000, 0x1000),
    ("spiffs", 1, 0x82, 0x391000, 0xF000),
    ("nvs", 1, 0x02, NVS_OFFSET, NVS_SIZE),
]


def table_bytes(parts, md5=True):
    out = b""
    for label, kind, subtype, offset, size in parts:
        out += b"\xaa\x50" + struct.pack("<BBII", kind, subtype, offset, size)
        out += label.encode().ljust(16, b"\x00") + struct.pack("<I", 0)
    if md5:
        out += b"\xeb\xeb" + b"\xff" * 14 + b"\x00" * 16
    return out.ljust(nvs.TABLE_SIZE, b"\xff")


class FakeDut:
    id = "A"

    def __init__(self, tmp_path, table, nvs_data=None, offset=NVS_OFFSET, size=NVS_SIZE):
        self.cfg = SimpleNamespace(
            nvs_offset="0x%X" % offset, nvs_size="0x%X" % size, nvs_backup=str(tmp_path / "backup.bin")
        )
        self.table = table
        self.nvs_data = nvs_data if nvs_data is not None else bytes(range(256)) * (size // 256)
        self.events = []

    def wait_api(self, noise_psk, deadline_s=None):
        self.events.append(("api", noise_psk))
        return SimpleNamespace(project_version="3.2")

    def read_flash(self, offset, size, out_path, deadline_s=None):
        self.events.append(("read", offset, size))
        with open(out_path, "wb") as handle:
            handle.write(self.table if offset == nvs.TABLE_OFFSET else self.nvs_data)

    def reset(self):
        self.events.append(("reset",))

    def flash_regions(self, regions, report_name=None):
        self.events.append(("write", [(o, str(p)) for o, p in regions]))
        return SimpleNamespace(ok=True)


def test_parse_finds_nvs_at_0x3a0000_and_stops_at_end_marker():
    parts = nvs.parse_partition_table(table_bytes(V160))
    assert [p.label for p in parts] == [p[0] for p in V160]
    found = [p for p in parts if p.label == "nvs"][0]
    assert (found.offset, found.size, found.type, found.subtype) == (NVS_OFFSET, NVS_SIZE, 1, 2)


def test_parse_stops_at_blank_flash_without_md5_entry():
    parts = nvs.parse_partition_table(table_bytes(V160[:2], md5=False))
    assert [p.label for p in parts] == ["otadata", "phy_init"]


def test_capture_reads_table_first_then_region_then_resets(tmp_path):
    dut = FakeDut(tmp_path, table_bytes(V160))
    out = tmp_path / "nvs.bin"
    digest = nvs.capture(dut, out, "psk", hold_s=0)
    assert [e[0] for e in dut.events] == ["api", "read", "read", "reset"]
    assert dut.events[1][1:] == (0x8000, 0x1000)
    assert dut.events[2][1:] == (NVS_OFFSET, NVS_SIZE)
    assert out.stat().st_size == NVS_SIZE
    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    assert digest == hashlib.sha256(out.read_bytes()).hexdigest()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["nvs.bin"]


def test_table_with_nvs_at_0x9000_raises_before_the_region_is_read(tmp_path):
    wrong = [p for p in V160 if p[0] != "nvs"] + [("nvs", 1, 0x02, 0x9000, 0x6000)]
    dut = FakeDut(tmp_path, table_bytes(wrong))
    with pytest.raises(RigError) as err:
        nvs.capture(dut, tmp_path / "nvs.bin", None, hold_s=0)
    assert "0x9000" in str(err.value) and "0x3A0000" in str(err.value)
    reads = [e for e in dut.events if e[0] == "read"]
    assert [r[1] for r in reads] == [0x8000]
    assert dut.events[-1] == ("reset",)
    assert not (tmp_path / "nvs.bin").exists()


def test_table_without_nvs_raises(tmp_path):
    dut = FakeDut(tmp_path, table_bytes(V160[:3]))
    with pytest.raises(RigError, match="no nvs partition"):
        nvs.capture(dut, tmp_path / "nvs.bin", None, hold_s=0)


def test_all_ff_region_is_refused_and_keeps_the_old_backup(tmp_path):
    out = tmp_path / "nvs.bin"
    out.write_bytes(b"old")
    dut = FakeDut(tmp_path, table_bytes(V160), nvs_data=b"\xff" * NVS_SIZE)
    with pytest.raises(RigError, match="all 0xFF"):
        nvs.capture(dut, out, None, hold_s=0)
    assert out.read_bytes() == b"old"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["nvs.bin"]


def test_short_read_is_refused(tmp_path):
    dut = FakeDut(tmp_path, table_bytes(V160), nvs_data=b"\x01" * 100)
    with pytest.raises(RigError, match="100 bytes"):
        nvs.capture(dut, tmp_path / "nvs.bin", None, hold_s=0)


def test_api_must_answer_continuously_for_the_hold_time(tmp_path):
    ticks = {"now": 0.0}
    answers = iter([True, True, False, True, True, True])  # a miss at t=2 resets the streak

    class Dut:
        id = "A"

        def wait_api(self, noise_psk, deadline_s=None):
            if not next(answers):
                raise RigError("no answer")

    def sleep(seconds):
        ticks["now"] += seconds

    nvs.hold_api(Dut(), None, hold_s=2, clock=lambda: ticks["now"], sleep=sleep)
    assert ticks["now"] >= 5  # the streak restarted after the miss and needed 2 more seconds


def test_api_that_never_stays_up_gives_up(tmp_path):
    ticks = {"now": 0.0}

    class Dut:
        id = "A"

        def wait_api(self, noise_psk, deadline_s=None):
            raise RigError("no answer")

    with pytest.raises(RigError, match="did not stay up"):
        nvs.hold_api(Dut(), None, hold_s=70, clock=lambda: ticks["now"], sleep=lambda s: ticks.update(now=ticks["now"] + 50))


def test_restore_is_one_region_write_of_the_backup(tmp_path):
    dut = FakeDut(tmp_path, table_bytes(V160))
    (tmp_path / "backup.bin").write_bytes(b"\x01" * NVS_SIZE)
    nvs.restore(dut)
    assert dut.events == [("write", [("0x3A0000", str(tmp_path / "backup.bin"))])]


def test_restore_refuses_a_backup_of_the_wrong_size(tmp_path):
    dut = FakeDut(tmp_path, table_bytes(V160))
    (tmp_path / "backup.bin").write_bytes(b"\x01" * 10)
    with pytest.raises(RigError, match="10 bytes"):
        nvs.restore(dut)
    assert dut.events == []
