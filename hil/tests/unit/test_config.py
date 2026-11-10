"""config.load edges (RIG-10 from 01-01) and the literals that must be masked (HARN-13, D-16)."""

import contextlib
import io

import pytest

from hil import RigError, config

SUPERVISOR_KEY = "sv-key-0123456789"
DUT_KEY = "dut-key-0123456789"
SHA = "b" * 64


A_KEYS = 'framework = "arduino"\ncapabilities = []\n'


def rig_toml(sup_host="192.0.2.10", a_host="192.0.2.20", a_mac="02:00:00:00:00:0a", b_host="192.0.2.30", b_mac="02:00:00:00:00:0b", a_keys=A_KEYS, b_keys=""):
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
nvs_release_tag = "v1.6.0"
last_green_dir = "/nonexistent/last-green"
%s[dut.b]
rev = "4.0"
chip = "esp32c6"
host = "%s"
mac = "%s"
%s""" % (sup_host, a_host, a_mac, SHA, a_keys, b_host, b_mac, b_keys)


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


# ---- framework and capabilities of rig.toml (HARN-02, D-33) ----


def with_dut_keys(a_keys=A_KEYS, b_keys=""):
    return rig_toml(a_keys=a_keys, b_keys=b_keys)


def test_framework_and_capabilities_are_read_for_dut_a(tmp_path):
    cfg, _env, _net = load(tmp_path, with_dut_keys('framework = "arduino"\ncapabilities = ["hdc1080", "usr1"]\n'))
    assert cfg.duts["A"].framework == "arduino"
    assert cfg.duts["A"].capabilities == ("hdc1080", "usr1")


def test_dut_b_may_carry_the_keys_too(tmp_path):
    cfg, _env, _net = load(tmp_path, with_dut_keys(b_keys='framework = "esp-idf"\ncapabilities = []\n'))
    assert cfg.duts["B"].framework == "esp-idf" and cfg.duts["B"].capabilities == ()


@pytest.mark.parametrize(
    "line,match",
    [
        ('capabilities = ["hdc1080", "usr10"]', r"dut\.a\.capabilities has an unknown name"),
        ('capabilities = ["USR1"]', r"dut\.a\.capabilities has an unknown name"),
        ('capabilities = [" usr1"]', r"dut\.a\.capabilities has an unknown name"),
        ('capabilities = ["usr1", "usr1"]', r"dut\.a\.capabilities has a duplicate"),
        ('capabilities = "usr1"', r"dut\.a\.capabilities must be a list of names"),
        ("capabilities = [1]", r"dut\.a\.capabilities must be a list of names"),
        ('framework = "espidf"', r"dut\.a\.framework is not arduino or esp-idf"),
        ('framework = "Arduino"', r"dut\.a\.framework is not arduino or esp-idf"),
        ("framework = 3", r"dut\.a\.framework is not arduino or esp-idf"),
    ],
)
def test_bad_framework_or_capabilities_are_refused_naming_the_key_not_the_list(tmp_path, line, match):
    with pytest.raises(RigError, match=match) as err:
        other = 'capabilities = []\n' if line.startswith("framework") else 'framework = "arduino"\n'
        load(tmp_path, with_dut_keys(line + "\n" + other))
    assert "usr10" not in str(err.value) and "hdc1080" not in str(err.value)


def test_dut_a_without_capabilities_is_refused(tmp_path):
    with pytest.raises(RigError, match=r"dut\.a\.capabilities is missing"):
        load(tmp_path, with_dut_keys('framework = "arduino"\n'))


def test_dut_a_without_framework_is_refused(tmp_path):
    with pytest.raises(RigError, match=r"dut\.a\.framework is missing"):
        load(tmp_path, with_dut_keys("capabilities = []\n"))


def test_dut_a_with_an_empty_capability_list_is_accepted(tmp_path):
    cfg, _env, _net = load(tmp_path, with_dut_keys('framework = "esp-idf"\ncapabilities = []\n'))
    assert cfg.duts["A"].capabilities == () and cfg.duts["A"].framework == "esp-idf"


def test_dut_b_may_omit_both_keys(tmp_path):
    cfg, _env, _net = load(tmp_path)
    assert cfg.duts["B"].framework == "" and cfg.duts["B"].capabilities == ()


# --- D-37: the release tag the NVS dump was captured with ---------------------------------------

NVS_TAG_LINE = 'nvs_release_tag = "v1.6.0"\n'


def test_dut_a_carries_the_nvs_release_tag(tmp_path):
    cfg, _env, _net = load(tmp_path)
    assert cfg.duts["A"].nvs_release_tag == "v1.6.0"


def test_a_calver_nvs_release_tag_is_accepted(tmp_path):
    cfg, _env, _net = load(tmp_path, rig_toml().replace(NVS_TAG_LINE, 'nvs_release_tag = "v2026.11.0"\n'))
    assert cfg.duts["A"].nvs_release_tag == "v2026.11.0"


def test_dut_a_without_nvs_release_tag_is_refused(tmp_path):
    with pytest.raises(RigError, match=r"^rig\.toml: dut\.a\.nvs_release_tag is missing$"):
        load(tmp_path, rig_toml().replace(NVS_TAG_LINE, ""))


@pytest.mark.parametrize("value", ['"1.6.0"', '"v1.6"', '"v1.6.0-rc1"', '"v1.6.0 "', '""', "160"])
def test_an_nvs_release_tag_outside_vxyz_is_refused_without_its_value(tmp_path, value):
    with pytest.raises(RigError, match=r"^rig\.toml: dut\.a\.nvs_release_tag is not vX\.Y\.Z$"):
        load(tmp_path, rig_toml().replace(NVS_TAG_LINE, "nvs_release_tag = %s\n" % value))


def test_dut_b_does_not_need_an_nvs_release_tag(tmp_path):
    cfg, _env, _net = load(tmp_path)
    assert "nvs_release_tag" not in rig_toml().split("[dut.b]")[1]
    assert cfg.duts["B"].nvs_release_tag == ""


# ---- 03-14 masking gap: masks before any other output, no host or MAC in a repr ----

CHILD = """
import sys
from hil import config
cfg = config.load(network_file=sys.argv[1])
config.emit_masks(cfg, network_file=sys.argv[1])
# aioesphomeapi logs a connection error with the DUT's address to stderr, unbuffered
sys.stderr.write("192.0.2.20: Connection error occurred\\n")
sys.stderr.flush()
"""


def test_the_masks_reach_a_pipe_before_a_later_stderr_line_naming_a_host(tmp_path):
    """p1 (03-14): the ::add-mask:: lines sat in the block-buffered stdout of the Preflight step while
    aioesphomeapi's stderr warning with DUT A's address reached the runner first, unmasked. Both streams
    go to one pipe here, as on the runner: every mask line must come before the stderr line."""
    import os
    import subprocess
    import sys

    cfg_path = tmp_path / "rig.toml"
    cfg_path.write_text(rig_toml(), encoding="utf-8")
    net = network(tmp_path)
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "SYSTEMROOT")}
    env.update(HIL_RIG_CONFIG=str(cfg_path), HIL_SUPERVISOR_KEY=SUPERVISOR_KEY, GITHUB_ACTIONS="true")
    root = os.path.dirname(os.path.dirname(os.path.abspath(config.__file__)))
    env["PYTHONPATH"] = root
    out = subprocess.run(
        [sys.executable, "-c", CHILD, str(net)], cwd=root, env=env, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, timeout=60, check=True,
    ).stdout.splitlines()
    leak = out.index("192.0.2.20: Connection error occurred")
    masks = [i for i, line in enumerate(out) if line.startswith("::add-mask::")]
    assert masks and "::add-mask::192.0.2.20" in out
    assert max(masks) < leak, "a mask line came after the stderr line that names the host"


def test_no_host_mac_or_subnet_in_the_repr_of_the_rig_config(tmp_path):
    """A pytest traceback shows the rig_config fixture's repr truncated ('192.0.2...'), which no
    full-value mask matches: hosts and MACs stay out of every repr, the attributes stay readable."""
    cfg, _env, _net = load(tmp_path)
    text = repr(cfg) + str(cfg) + "".join(repr(d) for d in cfg.duts.values())
    for literal in ("192.0.2.10", "192.0.2.20", "192.0.2.30", "192.0.2", "02:00:00:00:00:0a", "02:00:00:00:00:0b"):
        assert literal not in text, literal
    assert cfg.supervisor_host == "192.0.2.10" and cfg.duts["A"].host == "192.0.2.20"
    assert "rev='3.2'" in repr(cfg.duts["A"])


# ---- 03-17 (WR-03): the /24 prefix of every IPv4 rig host is a mask literal ----


def prefix_values(tmp_path, **env_extra):
    text = rig_toml(sup_host="192.0.2.10", a_host="192.0.2.20", b_host="198.51.100.30")
    cfg, env, net = load(tmp_path, text, **env_extra)
    return cfg, env, net, config.mask_literals(cfg, env=env, network_file=net)


def test_the_prefix_of_every_ipv4_rig_host_is_a_mask_literal_once(tmp_path):
    _cfg, _env, _net, lits = prefix_values(tmp_path)
    assert lits.count("192.0.2.") == 1 and lits.count("198.51.100.") == 1
    for host in ("192.0.2.10", "192.0.2.20", "198.51.100.30"):
        assert host in lits


def test_emit_masks_prints_the_prefixes_under_actions(tmp_path):
    cfg, env, net, _lits = prefix_values(tmp_path, GITHUB_ACTIONS="true")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        config.emit_masks(cfg, env=env, network_file=net)
    lines = out.getvalue().splitlines()
    assert "::add-mask::192.0.2." in lines and "::add-mask::198.51.100." in lines


def test_a_host_that_is_not_ipv4_contributes_no_prefix_and_no_error():
    for value in ("rig.example.net", "2001:db8::1", "", "192.0.2", "192.0.2.300", "a.b.c.d"):
        assert config._prefix24(value) == "", value
    assert config._prefix24("192.0.2.10") == "192.0.2."


# ---- 03-17 follow-up (WR-03): the literals for the emitters never raise ----


def test_safe_mask_literals_equals_mask_literals_for_a_loaded_config(tmp_path):
    cfg, env, net, lits = prefix_values(tmp_path)
    assert lits and config.safe_mask_literals(cfg, env=env, network_file=net) == lits


def test_safe_mask_literals_is_empty_for_none_and_for_a_config_that_did_not_load():
    from types import SimpleNamespace

    assert config.safe_mask_literals(None) == []
    assert config.safe_mask_literals(SimpleNamespace(duts={"A": object()})) == []
