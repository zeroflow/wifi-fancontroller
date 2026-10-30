"""Redaction of everything that may be uploaded (HARN-13, D-16), on a synthetic capture."""

import re
from pathlib import Path

import pytest

from hil import config, redact

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "uart-sample.log"
LITERALS = [
    "192.0.2.10",
    "192.0.2.20",
    "02:00:00:00:00:0a",
    "02:00:00:00:00:0A",
    "02000000000a",
    "02000000000A",
    "00000a",
    "00000A",
    "HIL-Example-Net",
]
IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
MAC = re.compile(r"(?i)\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b")


def fixture_text():
    return FIXTURE.read_text(encoding="utf-8")


def test_fixture_holds_only_documentation_addresses_and_locally_administered_macs():
    text = fixture_text()
    for address in IPV4.findall(text):
        assert address.startswith(("192.0.2.", "198.51.100.")), address
    for mac in MAC.findall(text):
        assert mac.lower().startswith("02:00:00:00:00:"), mac
    assert re.search(r"(?i)02:00:00:00:00:0a", text) and "02:00:00:00:00:0A" in text and "02000000000A" in text


def test_redacted_fixture_has_no_address_mac_suffix_or_socket_host():
    out = redact.redact(fixture_text(), LITERALS)
    assert not IPV4.search(out)
    assert not MAC.search(out)
    for leftover in ("fancontroller-r3-2-00000a", "02000000000A", "00000A", "00000a", "192.0.2.10", "HIL-Example-Net"):
        assert leftover not in out, leftover
    assert "socket://***" in out and not re.search(r"socket://[^*]", out)


def test_pattern_pass_catches_values_the_literals_do_not_know():
    out = redact.redact(fixture_text(), [])
    assert not IPV4.search(out) and not MAC.search(out)  # the BSSID and the gateway were never listed


def test_error_line_text_survives_and_ansi_is_stripped():
    out = redact.redact(fixture_text(), LITERALS)
    assert "[E][rmt:105]: Channel creation failed for ***" in out
    assert "\x1b" not in out


def test_literals_are_replaced_longest_first():
    assert redact.redact("key=abcdefghijkl end", ["abcdefgh", "abcdefghijkl"]) == "key=*** end"
    assert redact.redact("key=abcdefghijkl end", ["abcdefghijkl", "abcdefgh"]) == "key=*** end"


def test_redact_tree_writes_raw_files_and_root_json_and_nothing_else(tmp_path):
    reports = tmp_path / "reports"
    (reports / "raw").mkdir(parents=True)
    (reports / "raw" / "uart-dut-a.log").write_text(fixture_text(), encoding="utf-8")
    (reports / "raw" / "sub").mkdir()
    (reports / "raw" / "sub" / "marks.json").write_text('{"host": "192.0.2.10"}', encoding="utf-8")
    (reports / "verdict.json").write_text('{"verdict": "FAIL", "host": "192.0.2.20"}', encoding="utf-8")
    (reports / "final-image.json").write_text('{"image": "known-good"}', encoding="utf-8")
    (reports / "notes.txt").write_text("not a report", encoding="utf-8")
    out_dir = reports / "redacted"
    written = redact.redact_tree(reports / "raw", out_dir, LITERALS)
    names = sorted(str(p.relative_to(out_dir)) for p in out_dir.rglob("*") if p.is_file())
    assert names == ["final-image.json", "sub/marks.json", "uart-dut-a.log", "verdict.json"]
    assert sorted(written) == sorted(out_dir / n for n in names)
    assert "192.0.2" not in (out_dir / "verdict.json").read_text()
    assert "192.0.2" not in (out_dir / "sub" / "marks.json").read_text()


def test_redact_tree_clears_files_left_by_an_earlier_run(tmp_path):
    reports = tmp_path / "reports"
    (reports / "raw").mkdir(parents=True)
    (reports / "redacted").mkdir()
    (reports / "redacted" / "stale.log").write_text("old", encoding="utf-8")
    redact.redact_tree(reports / "raw", reports / "redacted", LITERALS)
    assert not (reports / "redacted" / "stale.log").exists()


def test_redact_tree_without_raw_redacts_only_the_json_reports(tmp_path):
    reports = tmp_path / "reports"
    (reports / "raw").mkdir(parents=True)
    (reports / "raw" / "uart-dut-a.log").write_text("secret 192.0.2.10", encoding="utf-8")
    (reports / "verdict.json").write_text('{"verdict": "RIG ERROR"}', encoding="utf-8")
    redact.redact_tree(reports / "raw", reports / "redacted", [], include_raw=False)
    assert [p.name for p in (reports / "redacted").rglob("*") if p.is_file()] == ["verdict.json"]


def test_binary_garbage_is_decoded_with_replacement(tmp_path):
    reports = tmp_path / "reports"
    (reports / "raw").mkdir(parents=True)
    (reports / "raw" / "uart.log").write_bytes(b"\xff\xfe 192.0.2.10 \x00")
    redact.redact_tree(reports / "raw", reports / "redacted", ["192.0.2.10"])
    assert "192.0.2.10" not in (reports / "redacted" / "uart.log").read_text(encoding="utf-8")
