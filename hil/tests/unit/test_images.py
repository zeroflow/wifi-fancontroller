"""Static checks of the HIL image YAMLs (no esphome needed, runs in the hosted unit suite).

These tests change in the same commit as the YAMLs they cover. They read the files
with a loader that keeps ESPHome's custom tags (!include, !extend, !secret, !lambda)
as their plain value, so a package include shows up as the file name it names.

The build-time check on the RESOLVED configs (framework table, entity names, fan
frequency, canary pin swap) lives in hil/tools/build_image.py --check-configs.
"""

import re
import tomllib
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]
HIL = REPO / "hil"


class TagTolerantLoader(yaml.SafeLoader):
    """SafeLoader that maps every unknown !tag to the plain value it wraps."""


def _plain(loader, tag_suffix, node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    return loader.construct_mapping(node, deep=True)


TagTolerantLoader.add_multi_constructor("!", _plain)


def load(path):
    with open(path, "r", encoding="utf-8") as handle:
        return yaml.load(handle, Loader=TagTolerantLoader)  # noqa: S506 - tag-tolerant SafeLoader subclass


def by_id(entries, wanted):
    """The entry of an ESPHome list whose id (or !extend target) is `wanted`."""
    found = [entry for entry in entries if entry.get("id") == wanted]
    assert len(found) == 1, "expected exactly one entry with id %s, found %d" % (wanted, len(found))
    return found[0]


def test_qc_auto_layers_on_the_hil_wrapper_and_the_qc_module():
    data = load(HIL / "rev3.2.qc-auto.yaml")
    assert data["packages"]["hil"] == "rev3.2.hil.yaml"
    assert data["packages"]["qc"] == "qc-overrides.yaml"


def test_qc_auto_declares_the_arduino_framework_explicitly():
    data = load(HIL / "rev3.2.qc-auto.yaml")
    assert data["esp32"]["framework"]["type"] == "arduino"


def test_qc_auto_has_its_own_name_and_a_qc_version_prefix():
    data = load(HIL / "rev3.2.qc-auto.yaml")
    assert data["esphome"]["name"] == "fancontroller-qc-r3-2"
    assert data["esphome"]["project"]["version"].startswith("3.2+qc.")
    assert "${hil_commit}" in data["esphome"]["project"]["version"]


def test_the_commit_wrapper_keeps_its_own_name_and_version_prefix():
    data = load(HIL / "rev3.2.hil.yaml")
    assert data["esphome"]["project"]["version"].startswith("3.2+hil.")
    assert "name" not in data["esphome"]  # the name comes from the customer config


def test_qc_module_starts_without_the_first_boot_fan_start():
    data = load(HIL / "qc-overrides.yaml")
    assert by_id(data["globals"], "init_done")["initial_value"] == "true"


def test_qc_module_restores_every_fan_off():
    data = load(HIL / "qc-overrides.yaml")
    for number in (1, 2, 3, 4):
        assert by_id(data["fan"], "fan%d" % number)["restore_mode"] == "ALWAYS_OFF"
    assert len(data["fan"]) == 4


def test_qc_module_updates_the_hdc1080_every_five_seconds():
    data = load(HIL / "qc-overrides.yaml")
    assert by_id(data["sensor"], "temperature_sensor")["update_interval"] == "5s"


def test_qc_module_publishes_the_debug_text_sensors_and_the_safe_mode_button():
    data = load(HIL / "qc-overrides.yaml")
    assert "debug" in data
    sensor = [entry for entry in data["text_sensor"] if entry["platform"] == "debug"]
    assert len(sensor) == 1
    assert sensor[0]["device"]["name"] == "QC Device Info"
    assert sensor[0]["reset_reason"]["name"] == "QC Reset Reason"
    button = [entry for entry in data["button"] if entry["platform"] == "safe_mode"]
    assert [entry["name"] for entry in button] == ["QC Safe Mode Boot"]


def test_qc_module_overrides_no_fan_pwm_frequency():
    # D-27: the 25 kHz spike decides; until then the tests run the real configuration.
    data = load(HIL / "qc-overrides.yaml")
    assert "output" not in data
    text = "\n".join(line for line in (HIL / "qc-overrides.yaml").read_text(encoding="utf-8").splitlines()
                     if not line.lstrip().startswith("#"))
    assert "frequency" not in text


def test_no_hil_image_yaml_defines_a_top_level_safe_mode_block():
    # The base ota/safe_mode setup is part of what is tested; a HIL image must not replace it.
    files = sorted(HIL.glob("*.yaml"))
    assert files, "no hil/*.yaml found"
    for path in files:
        if path.name == "hil-network.yaml":
            continue
        data = load(path)
        assert isinstance(data, dict), path.name
        assert "safe_mode" not in data, "%s defines a top-level safe_mode block" % path.name


# ---- Task 2: the canary and the framework table -----------------------------------------------

# The project constraint (hil-rig CLAUDE.md): Rev 1.0 esp-idf, Rev 2.0-3.3 arduino, Rev 4.0 esp-idf.
PROJECT_FRAMEWORKS = {
    "1.0": "esp-idf",
    "2.0": "arduino",
    "3.0": "arduino",
    "3.1": "arduino",
    "3.2": "arduino",
    "3.3": "arduino",
    "4.0": "esp-idf",
}


def pin_of(output_entry):
    match = re.match(r"^GPIO([0-9]+)$", str(output_entry["pin"]))
    assert match, "unexpected pin %r" % output_entry["pin"]
    return int(match.group(1))


def framework_table():
    return tomllib.loads((HIL / "frameworks.toml").read_text(encoding="utf-8"))


def test_canary_layers_on_qc_auto_and_has_its_own_name_and_version():
    data = load(HIL / "rev3.2.canary.yaml")
    assert data["packages"]["qc"] == "rev3.2.qc-auto.yaml"
    assert data["esphome"]["name"] == "fancontroller-can-r3-2"
    assert data["esphome"]["project"]["version"].startswith("3.2+canary.")
    assert "${hil_commit}" in data["esphome"]["project"]["version"]


def test_canary_swaps_the_fan1_and_fan2_pins_against_the_hardware_package():
    hardware = load(REPO / "hardware-rev-3.1.yaml")
    base = {entry["id"]: pin_of(entry) for entry in hardware["output"] if entry.get("platform") == "ledc"}
    canary = {entry["id"]: pin_of(entry) for entry in load(HIL / "rev3.2.canary.yaml")["output"]}
    assert canary["pwm_fan1"] == base["pwm_fan2"]
    assert canary["pwm_fan2"] == base["pwm_fan1"]
    assert canary["pwm_fan1"] != base["pwm_fan1"]
    assert set(canary) == {"pwm_fan1", "pwm_fan2"}  # channels 3 and 4 stay as shipped


def test_canary_does_not_touch_the_framework():
    data = load(HIL / "rev3.2.canary.yaml")
    assert "esp32" not in data


def test_frameworks_table_equals_the_project_constraint_exactly():
    table = framework_table()
    assert table["schema"] == 1
    assert table["revisions"] == PROJECT_FRAMEWORKS


def test_every_explicit_framework_in_a_hil_yaml_equals_the_table_for_its_revision():
    revisions = framework_table()["revisions"]
    checked = 0
    for path in sorted(HIL.glob("rev*.yaml")):
        rev = re.match(r"^rev([0-9]+\.[0-9]+)\.", path.name).group(1)
        data = load(path)
        framework = (data.get("esp32") or {}).get("framework", {}).get("type")
        if framework is None:
            continue
        assert framework == revisions[rev], "%s declares %s, table says %s" % (path.name, framework, revisions[rev])
        checked += 1
    assert checked >= 1  # qc-auto declares one; a test that checks nothing would be vacuous



def test_esphome_names_fit_the_hostname_limit_with_the_mac_suffix():
    # The customer config sets name_add_mac_suffix; ESPHome allows 24 characters before the suffix.
    for filename in ("rev3.2.qc-auto.yaml", "rev3.2.canary.yaml"):
        name = load(HIL / filename)["esphome"]["name"]
        assert len(name) <= 24, "%s: esphome.name %s is %d characters" % (filename, name, len(name))
