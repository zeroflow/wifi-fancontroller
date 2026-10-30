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


# ---- wiring in __main__: masks first, redaction in a finally block, fail closed -------------

RIG_TOML = """
schema = 1
[supervisor]
host = "192.0.2.10"
[dut.a]
rev = "3.2"
chip = "esp32s2"
host = "192.0.2.20"
mac = "02:00:00:00:00:0a"
flash_offset = "0x0"
known_good_image = "/nonexistent/kg.bin"
known_good_sha256 = "%s"
known_good_api_encryption = false
nvs_backup = "/nonexistent/nvs.bin"
nvs_offset = "0x3A0000"
nvs_size = "0x60000"
last_green_dir = "/nonexistent/last-green"
""" % ("b" * 64)


@pytest.fixture
def main_env(tmp_path, monkeypatch):
    from hil import __main__ as entry

    cfg = tmp_path / "rig.toml"
    cfg.write_text(RIG_TOML, encoding="utf-8")
    net = tmp_path / "hil-network.yaml"
    net.write_text('hil_dut_api_key: "dut-key-0123456789"\n', encoding="utf-8")
    monkeypatch.setattr(config, "NETWORK_FILE", net)
    for name in ("HIL_LOCAL_DUT_API_KEY", "HIL_LOCAL_WIFI_SSID", "HIL_LOCAL_WIFI_PASSWORD", "HIL_NET_SSID", "HIL_NET_PSK", "HIL_FW_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HIL_RIG_CONFIG", str(cfg))
    monkeypatch.setenv("HIL_SUPERVISOR_KEY", "sv-key-0123456789")
    monkeypatch.setenv("HIL_REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("HIL_EXPECTED_COMMIT", "a" * 40)
    return entry


def test_run_prints_the_masks_before_any_other_line_and_still_redacts(main_env, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert main_env.run() == 3  # HIL_FW_DIR is not set: RIG ERROR after the masks
    lines = capsys.readouterr().out.splitlines()
    first_other = next(i for i, line in enumerate(lines) if not line.startswith("::add-mask::"))
    assert first_other >= 5
    assert "::add-mask::sv-key-0123456789" in lines[:first_other]
    assert (tmp_path / "reports" / "redacted" / "verdict.json").is_file()


def test_run_without_a_config_still_writes_the_redacted_verdict_only(main_env, tmp_path, monkeypatch):
    monkeypatch.delenv("HIL_RIG_CONFIG")
    (tmp_path / "reports" / "raw").mkdir(parents=True)
    (tmp_path / "reports" / "raw" / "uart.log").write_text("left over 192.0.2.10", encoding="utf-8")
    assert main_env.run() == 3
    assert [p.name for p in (tmp_path / "reports" / "redacted").rglob("*") if p.is_file()] == ["verdict.json"]


def test_a_redaction_fault_removes_the_redacted_directory(main_env, tmp_path, monkeypatch, capsys):
    (tmp_path / "reports" / "redacted").mkdir(parents=True)
    (tmp_path / "reports" / "redacted" / "half.log").write_text("x", encoding="utf-8")

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(redact, "redact_tree", boom)
    main_env.redact_reports(None)
    assert not (tmp_path / "reports" / "redacted").exists()
    assert "redaction failed (OSError)" in capsys.readouterr().out
