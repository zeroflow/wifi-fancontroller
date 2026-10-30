"""NVS insurance for DUT A: capture and restore the nvs partition (D-06, D-08).

The offsets come from the live partition table, never from a guess: the capture
reads the table at 0x8000 and refuses unless a partition labelled `nvs` sits at
the offset and size rig.toml names (RESEARCH P1: 0x9000 is otadata, not NVS).
Only region reads and region writes happen here; there is no erase.
"""

import hashlib
import os
import struct
import time
from dataclasses import dataclass
from pathlib import Path

from . import RigError
from .dut import API_CONNECT_S

TABLE_OFFSET = 0x8000
TABLE_SIZE = 0x1000
ENTRY_SIZE = 32
ENTRY_MAGIC = b"\xaa\x50"
API_HOLD_S = 70  # P2: the safe-mode boot counter resets after about 60 s of stable uptime
API_HOLD_LIMIT_S = 300  # give up if the API never answers continuously for API_HOLD_S


@dataclass(frozen=True)
class Partition:
    label: str
    type: int
    subtype: int
    offset: int
    size: int


def parse_partition_table(data):
    """Entries are 32 bytes: AA 50, type, subtype, offset (u32 LE), size (u32 LE), label (16), flags (u32).

    Stops at the first entry without the magic bytes (0xFF end marker or the MD5 entry).
    """
    parts = []
    for start in range(0, len(data) - ENTRY_SIZE + 1, ENTRY_SIZE):
        entry = data[start : start + ENTRY_SIZE]
        if entry[:2] != ENTRY_MAGIC:
            break
        kind, subtype, offset, size = struct.unpack("<BBII", entry[2:12])
        label = entry[12:28].split(b"\x00", 1)[0].decode("ascii", "replace")
        parts.append(Partition(label=label, type=kind, subtype=subtype, offset=offset, size=size))
    return parts


def _private_file(path):
    """Create or truncate `path` with mode 0600 and return it as a Path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.close(fd)
    os.chmod(path, 0o600)
    return path


def hold_api(dut, noise_psk, hold_s=API_HOLD_S, clock=time.monotonic, sleep=time.sleep):
    """Return once the API has answered continuously for `hold_s` seconds (P2)."""
    started = clock()
    streak_start = None
    while True:
        try:
            dut.wait_api(noise_psk, deadline_s=API_CONNECT_S + 5)
        except RigError:
            streak_start = None
        else:
            now = clock()
            if streak_start is None:
                streak_start = now
            if now - streak_start >= hold_s:
                return
        if clock() - started > hold_s + API_HOLD_LIMIT_S:
            raise RigError("DUT %s API did not stay up for %ss within %ss" % (dut.id, hold_s, hold_s + API_HOLD_LIMIT_S))
        sleep(1)


def capture(dut, out_path, noise_psk, hold_s=API_HOLD_S, clock=time.monotonic, sleep=time.sleep):
    """Read the nvs partition into out_path (mode 0600) and return its sha256.

    Order: API stable for hold_s, bootloader, partition table read and check, region read, reset.
    The old file at out_path stays untouched until the new one is complete and valid.
    """
    cfg = dut.cfg
    want_offset = int(cfg.nvs_offset, 16)
    want_size = int(cfg.nvs_size, 16)
    hold_api(dut, noise_psk, hold_s, clock, sleep)
    out_path = Path(out_path)
    table_path = _private_file(out_path.with_name(out_path.name + ".table"))
    part_path = _private_file(out_path.with_name(out_path.name + ".part"))
    try:
        dut.read_flash(TABLE_OFFSET, TABLE_SIZE, table_path)
        table = parse_partition_table(table_path.read_bytes())
        nvs = [p for p in table if p.label == "nvs"]
        if not nvs or (nvs[0].offset, nvs[0].size) != (want_offset, want_size):
            found = "no nvs partition" if not nvs else "nvs at 0x%X size 0x%X" % (nvs[0].offset, nvs[0].size)
            raise RigError(
                "partition table: %s, rig.toml says nvs_offset 0x%X nvs_size 0x%X" % (found, want_offset, want_size)
            )
        dut.read_flash(want_offset, want_size, part_path)
        data = part_path.read_bytes()
        if len(data) != want_size:
            raise RigError("NVS read returned %d bytes, expected %d" % (len(data), want_size))
        if all(b == 0xFF for b in data):
            raise RigError("NVS read is all 0xFF (empty partition); nothing worth backing up")
        os.replace(part_path, out_path)
        os.chmod(out_path, 0o600)
    finally:
        dut.reset()
        for leftover in (table_path, part_path):
            try:
                leftover.unlink()
            except FileNotFoundError:
                pass
    return hashlib.sha256(data).hexdigest()


def restore(dut):
    """Write nvs_backup at nvs_offset: one region write, reset, nothing erased."""
    cfg = dut.cfg
    backup = Path(cfg.nvs_backup)
    try:
        size = backup.stat().st_size
    except OSError:
        raise RigError("nvs_backup file cannot be read") from None
    if size != int(cfg.nvs_size, 16):
        raise RigError("nvs_backup has %d bytes, nvs_size says %d" % (size, int(cfg.nvs_size, 16)))
    return dut.flash_regions([(cfg.nvs_offset, backup)], report_name="nvs-restore-dut-a.json")
