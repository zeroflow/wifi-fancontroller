"""config.load edges (RIG-10 from 01-01) and the literals that must be masked (HARN-13, D-16)."""

import contextlib
import io
from pathlib import Path
from types import SimpleNamespace

import pytest

from hil import RigError, config

SUPERVISOR_KEY = "sv-key-0123456789"
DUT_KEY = "dut-key-0123456789"
SHA = "b" * 64


def rig_toml(sup_host="192.0.2.10", a_host="192.0.2.20", a_mac="02:00:00:00:00:0a", b_host="192.0.2.30", b_mac="02:00:00:00:00:0b"):
    return """
schema = 1
[supervisor]
host = "%s"
[dut.a]
rev = "3.2"
chip = "esp32s2"
host = "%s"
mac = "%s"
flash_offset = "0x0"
known_good_image = "/nonexistent/kg.bin"
known_good_sha256 = "%s"
known_good_api_encryption = false
nvs_backup = "/nonexistent/nvs.bin"
nvs_offset = "0x3A0000"
nvs_size = "0x60000"
last_green_dir = "/nonexistent/last-green"
[dut.b]
rev = "4.0"
chip = "esp32c6"
host = "%s"
mac = "%s"
""" % (sup_host, a_host, a_mac, SHA, b_host, b_mac)


def network(tmp_path, ssid=None, psk=None, key=DUT_KEY):
    lines = ['hil_dut_api_key: "%s"' % key]
    if ssid:
        lines.append('hil_wifi_ssid: "%s"' % ssid)
    if psk:
        lines.append('hil_wifi_password: "%s"' % psk)
    path = tmp_path / "hil-network.yaml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def load(tmp_path, text=None, **env_extra):
    cfg_path = tmp_path / "rig.toml"
    cfg_path.write_text(text if text is not None else rig_toml(), encoding="utf-8")
    env = {"HIL_RIG_CONFIG": str(cfg_path), "HIL_SUPERVISOR_KEY": SUPERVISOR_KEY}
    env.update(env_extra)
    net = env.pop("network_file", None) or network(tmp_path)
    return config.load(env=env, network_file=net), env, net


def test_duplicate_host_is_refused(tmp_path):
    with pytest.raises(RigError, match=r"dut\.a\.host duplicates supervisor\.host"):
        load(tmp_path, rig_toml(a_host="192.0.2.10"))


def test_duplicate_mac_is_refused(tmp_path):
    with pytest.raises(RigError, match=r"dut\.b\.mac duplicates dut\.a\.mac"):
        load(tmp_path, rig_toml(b_mac="02:00:00:00:00:0a"))


def test_empty_dut_a_host_is_refused(tmp_path):
    with pytest.raises(RigError, match=r"dut\.a\.host is missing or empty"):
        load(tmp_path, rig_toml(a_host=""))


def test_valid_config_loads_and_keeps_keys_out_of_repr(tmp_path):
    cfg, _env, _net = load(tmp_path)
    assert cfg.duts["A"].mac == "02:00:00:00:00:0a"
    assert SUPERVISOR_KEY not in repr(cfg) and DUT_KEY not in repr(cfg)


def values(tmp_path, **env_extra):
    cfg, env, net = load(tmp_path, **env_extra)
    return config.mask_literals(cfg, env=env, network_file=net)


def test_mac_yields_six_forms_in_both_cases(tmp_path):
    lits = values(tmp_path)
    for form in ("02:00:00:00:00:0a", "02:00:00:00:00:0A", "02000000000a", "02000000000A", "00000a", "00000A"):
        assert form in lits, form


def test_hosts_keys_and_second_dut_are_masked(tmp_path):
    lits = values(tmp_path)
    for expected in ("192.0.2.10", "192.0.2.20", "192.0.2.30", SUPERVISOR_KEY, DUT_KEY, "02:00:00:00:00:0b", "00000B"):
        assert expected in lits, expected


def test_hil_ssid_and_psk_are_masked_when_the_network_file_has_them(tmp_path):
    net = network(tmp_path, ssid="HIL-Example-Net", psk="example-psk-value")
    lits = values(tmp_path, network_file=net)
    assert "HIL-Example-Net" in lits and "example-psk-value" in lits


def test_local_overrides_and_the_published_key_are_masked_too(tmp_path):
    cfg, env, net = load(
        tmp_path,
        HIL_LOCAL_DUT_API_KEY="local-key-0123456789",
        HIL_LOCAL_WIFI_SSID="Local-Example-Net",
        HIL_LOCAL_WIFI_PASSWORD="local-psk-0123",
        HIL_NET_SSID="Isolated-Example",
        HIL_NET_PSK="isolated-psk-0123",
    )
    lits = config.mask_literals(cfg, env=env, network_file=net)
    for expected in ("local-key-0123456789", DUT_KEY, "Local-Example-Net", "local-psk-0123", "Isolated-Example", "isolated-psk-0123"):
        assert expected in lits, expected


def test_a_literal_shorter_than_six_characters_is_a_rig_error_naming_the_key_not_the_value(tmp_path):
    net = network(tmp_path, ssid="hil", psk="example-psk-value")
    cfg, env, _ = load(tmp_path, network_file=net)
    with pytest.raises(RigError) as err:
        config.mask_literals(cfg, env=env, network_file=net)
    assert "hil_wifi_ssid" in str(err.value) and "'hil'" not in str(err.value) and '"hil"' not in str(err.value)


def test_emit_masks_prints_one_line_per_literal_under_actions(tmp_path):
    cfg, env, net = load(tmp_path, GITHUB_ACTIONS="true")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        config.emit_masks(cfg, env=env, network_file=net)
    lines = out.getvalue().splitlines()
    expected = config.mask_literals(cfg, env=env, network_file=net)
    assert lines == ["::add-mask::%s" % lit for lit in expected]
    assert "::add-mask::%s" % SUPERVISOR_KEY in lines


def test_emit_masks_prints_nothing_outside_actions(tmp_path):
    cfg, env, net = load(tmp_path)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        config.emit_masks(cfg, env=env, network_file=net)
    assert out.getvalue() == ""
