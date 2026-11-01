"""The requires() hooks of tests/rig/conftest.py, run in a real pytest subprocess (HARN-02, T-02-37).

A throwaway rootdir holds a copy of the rig conftest and one test file; no supervisor exists, so
a test that reaches its fixtures errors, which proves a skip happens before any fixture is built.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]
CONFTEST = PROJECT / "tests" / "rig" / "conftest.py"

RIG = """
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
capabilities = %s
"""


def run_pytest(tmp_path, test_source, capabilities=None, extra=()):
    (tmp_path / "conftest.py").write_text(CONFTEST.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "pytest.ini").write_text("[pytest]\nmarkers =\n    requires(*capabilities): x\n    image(before=None, after=None): x\n", encoding="utf-8")
    (tmp_path / "test_x.py").write_text(test_source, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("HIL_", "GITHUB_"))}
    env["PYTHONPATH"] = str(PROJECT)
    if capabilities is not None:
        rig = tmp_path / "rig.toml"
        rig.write_text(RIG % ("b" * 64, capabilities), encoding="utf-8")
        env["HIL_RIG_CONFIG"] = str(rig)
        env["HIL_SUPERVISOR_KEY"] = "sv-key-0123456789"
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-rs", *extra],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60,
    )


GATED = 'import pytest\n\n@pytest.mark.requires("hdc1080")\ndef test_gated():\n    assert False, "must not run"\n'


def test_a_missing_capability_skips_with_the_reason_before_any_fixture(tmp_path):
    result = run_pytest(tmp_path, GATED, capabilities='["usr1"]')
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 skipped" in result.stdout
    assert "DUT %s (rig.toml) lacks capability: hdc1080" % "A" in result.stdout


def test_an_empty_capability_list_skips_and_names_every_missing_capability_in_marker_order(tmp_path):
    source = 'import pytest\n\n@pytest.mark.requires("usr3", "fan_tach_bridge")\ndef test_gated():\n    assert False\n'
    result = run_pytest(tmp_path, source, capabilities="[]")
    assert "lacks capability: usr3, fan_tach_bridge" in result.stdout


@pytest.mark.parametrize("name", ["usr10", "USR1", " usr1"])
def test_an_unknown_name_in_a_marker_fails_collection_without_rig_toml(tmp_path, name):
    source = 'import pytest\n\n@pytest.mark.requires(%r)\ndef test_gated():\n    pass\n' % name
    result = run_pytest(tmp_path, source, capabilities=None, extra=("--collect-only",))
    assert result.returncode != 0
    assert "unknown capability name" in result.stderr + result.stdout
    assert "test_x.py::test_gated" in result.stderr + result.stdout


def test_a_known_name_collects_without_rig_toml(tmp_path):
    result = run_pytest(tmp_path, GATED, capabilities=None, extra=("--collect-only", "-q"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "test_x.py::test_gated" in result.stdout
