"""The latest release as DUT A's baseline on the runner (REG-01, D-36, D-37; plan 03-10).

load_verified re-hashes the factory image against baseline.json (03-09 schema 1) and checks it
against rig.toml before anything is pressed; flash writes it with the NVS replay (region writes,
never an erase) and confirms DUT A rejoins without encryption on the release's version.
"""

import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from hil import FirmwareFailure, RigError, baseline, config
from hil import __main__ as cli

ASSET = "fancontroller-r3-2-esp32s2.factory.bin"
TAG = "v2026.11.0"
VERSION = "2026.11.0"
IMAGE = b"\xe9" + bytes(range(256)) * 16
NVS_SIZE = 0x6000


def dut_config(tmp_path, **changes):
    nvs = tmp_path / "nvs-dut-a.bin"
    if not nvs.exists():
        nvs.write_bytes(b"\x5a" * NVS_SIZE)
    cfg = config.DutConfig(
        id="A",
        rev="3.2",
        chip="esp32s2",
        host="192.0.2.20",
        mac="02:00:00:00:00:0a",
        flash_offset="0x0",
        known_good_image="/nonexistent/kg.bin",
        known_good_sha256="b" * 64,
        nvs_backup=str(nvs),
        nvs_offset="0x3A0000",
        nvs_size="0x%X" % NVS_SIZE,
        last_green_dir="/nonexistent/last-green",
        framework="arduino",
    )
    return replace(cfg, **changes)


def write_dir(directory, image=IMAGE, **changes):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / ASSET).write_bytes(image)
    digest = hashlib.sha256(image).hexdigest()
    data = {
        "asset": ASSET,
        "chip_family": "ESP32-S2",
        "digests": {"api": digest, "manifest": digest, "sidecar": digest},
        "offset": "0x0",
        "repo": "zeroflow/wifi-fancontroller",
        "rev": "3.2",
        "schema": 1,
        "sha256": digest,
        "tag": TAG,
        "version": VERSION,
    }
    for key, value in changes.items():
        if value is DELETE:
            data.pop(key, None)
        else:
            data[key] = value
    (directory / baseline.BASELINE_FILE).write_text(json.dumps(data), encoding="utf-8")
    return directory


DELETE = object()


# --- load_verified ---------------------------------------------------------------------------


def test_an_agreeing_directory_is_accepted(tmp_path):
    directory = write_dir(tmp_path / "hil-baseline")
    found = baseline.load_verified(directory, dut_config(tmp_path))
    assert found.tag == TAG
    assert found.rev == "3.2"
    assert found.path == directory / ASSET
    assert found.sha256 == hashlib.sha256(IMAGE).hexdigest()
    assert int(found.offset, 16) == 0
    assert found.version == VERSION
    assert set(found.digests) == {"api", "manifest", "sidecar"}


def test_a_calver_tag_is_accepted(tmp_path):
    """The latest release is v2026.11.0: CalVer is vX.Y.Z too."""
    directory = write_dir(tmp_path / "hil-baseline", tag="v2026.11.0")
    assert baseline.load_verified(directory, dut_config(tmp_path)).tag == "v2026.11.0"


def test_a_null_api_digest_is_accepted(tmp_path):
    digest = hashlib.sha256(IMAGE).hexdigest()
    directory = write_dir(tmp_path / "hil-baseline", digests={"api": None, "manifest": digest, "sidecar": digest})
    found = baseline.load_verified(directory, dut_config(tmp_path))
    assert found.digests["api"] is None


def test_a_flipped_byte_in_the_image_is_refused(tmp_path):
    directory = write_dir(tmp_path / "hil-baseline")
    data = bytearray(IMAGE)
    data[100] ^= 0x01
    (directory / ASSET).write_bytes(bytes(data))
    with pytest.raises(RigError, match=r"sha256 does not match the factory file") as info:
        baseline.load_verified(directory, dut_config(tmp_path))
    assert hashlib.sha256(IMAGE).hexdigest() not in str(info.value)


@pytest.mark.parametrize(
    "changes, pattern",
    [
        ({"rev": "3.3"}, r"rev does not match rig\.toml dut\.a\.rev"),
        ({"asset": "../" + ASSET}, r"asset must be a bare file name"),
        ({"asset": "sub/" + ASSET}, r"asset must be a bare file name"),
        ({"asset": "/etc/" + ASSET}, r"asset must be a bare file name"),
        ({"offset": "0x1000"}, r"offset does not match rig\.toml dut\.a\.flash_offset"),
        ({"offset": "zero"}, r"offset is not hex"),
        ({"offset": 0}, r"offset is not hex"),
        ({"chip_family": "ESP32-C6"}, r"chip_family does not match rig\.toml dut\.a\.chip"),
        ({"chip_family": "ESP32"}, r"chip_family does not match rig\.toml dut\.a\.chip"),
        ({"schema": 2}, r"schema must be 1"),
        ({"tag": "1.6.0"}, r"tag is not vX\.Y\.Z"),
        ({"tag": "v1.6"}, r"tag is not vX\.Y\.Z"),
        ({"tag": "v1.6.0-rc1"}, r"tag is not vX\.Y\.Z"),
        ({"tag": "v1.6.0\n"}, r"tag is not vX\.Y\.Z"),
        ({"version": ""}, r"version is missing or empty"),
        ({"version": DELETE}, r"version is missing or empty"),
        ({"sha256": "C" * 64}, r"sha256 is not 64 lowercase hex digits"),
        ({"digests": {"api": None, "manifest": "0" * 64, "sidecar": None}}, r"digests\.manifest does not match sha256"),
        ({"digests": {"api": "0" * 64}}, r"digests\.api does not match sha256"),
        ({"digests": "all agree"}, r"digests is not an object"),
    ],
)
def test_a_field_that_disagrees_is_refused_naming_the_key(tmp_path, changes, pattern):
    directory = write_dir(tmp_path / "hil-baseline", **changes)
    with pytest.raises(RigError, match=pattern):
        baseline.load_verified(directory, dut_config(tmp_path))


def test_the_sidecar_and_manifest_digests_must_be_present(tmp_path):
    digest = hashlib.sha256(IMAGE).hexdigest()
    directory = write_dir(tmp_path / "hil-baseline", digests={"api": digest, "manifest": digest})
    with pytest.raises(RigError, match=r"digests\.sidecar does not match sha256"):
        baseline.load_verified(directory, dut_config(tmp_path))


def test_a_missing_directory_or_file_is_refused(tmp_path):
    with pytest.raises(RigError, match=r"baseline\.json cannot be read"):
        baseline.load_verified(tmp_path / "absent", dut_config(tmp_path))
    directory = write_dir(tmp_path / "hil-baseline")
    (directory / ASSET).unlink()
    with pytest.raises(RigError, match=r"asset is not in the baseline directory"):
        baseline.load_verified(directory, dut_config(tmp_path))


def test_a_broken_baseline_json_is_refused(tmp_path):
    directory = tmp_path / "hil-baseline"
    directory.mkdir()
    (directory / baseline.BASELINE_FILE).write_text("{", encoding="utf-8")
    with pytest.raises(RigError, match=r"baseline\.json is not valid JSON"):
        baseline.load_verified(directory, dut_config(tmp_path))
    (directory / baseline.BASELINE_FILE).write_text("[]", encoding="utf-8")
    with pytest.raises(RigError, match=r"baseline\.json is not an object"):
        baseline.load_verified(directory, dut_config(tmp_path))


def test_the_chip_family_table_names_both_chips():
    assert baseline.CHIP_FAMILY == {"ESP32-S2": "esp32s2", "ESP32-C6": "esp32c6"}


# --- flash -----------------------------------------------------------------------------------


class FakeDut:
    """Records the regions written and answers wait_running like a DUT that rejoins, or never does."""

    id = "A"

    def __init__(self, answer=VERSION, failure=None, durations=(71.5,)):
        self.answer = answer
        self.failure = failure
        self.durations = list(durations)
        self.events = []
        self.last_reset_mark = None

    def flash_regions(self, regions, report_name=None):
        self.events.append(("flash_regions", [(str(o), str(p)) for o, p in regions], report_name))
        self.last_reset_mark = "reset_1"
        return SimpleNamespace(durations_s=list(self.durations), attempts=len(self.durations), ok=True)

    def wait_running(self, noise_psk, since_mark, deadline_s=90):
        self.events.append(("wait_running", noise_psk, since_mark, deadline_s))
        if self.failure is not None:
            raise self.failure
        return SimpleNamespace(project_version=self.answer)


def verified(tmp_path):
    return baseline.load_verified(write_dir(tmp_path / "hil-baseline"), dut_config(tmp_path))


def timings():
    return json.loads((config.reports_dir() / "timings.json").read_text(encoding="utf-8"))


def test_flash_writes_the_image_and_the_nvs_backup_and_confirms_without_encryption(tmp_path):
    found = verified(tmp_path)
    cfg = dut_config(tmp_path)
    dut = FakeDut()
    version, rejoin_s = baseline.flash(dut, found, cfg)
    assert version == VERSION
    assert rejoin_s >= 0
    kind, regions, report_name = dut.events[0]
    assert kind == "flash_regions"
    assert [int(offset, 16) for offset, _ in regions] == [0, 0x3A0000]
    assert regions[0][1] == str(found.path)
    assert regions[1][1] == cfg.nvs_backup
    assert report_name == "baseline-flash-dut-a.json"
    # D-04: the release image has no API encryption; the boot to wait for starts at the flash's reset.
    assert dut.events[1][:3] == ("wait_running", None, "reset_1")
    assert timings()["baseline_flash"] == 71.5


def test_flash_without_nvs_writes_the_image_only_and_does_not_wait(tmp_path):
    found = verified(tmp_path)
    dut = FakeDut()
    assert baseline.flash(dut, found, dut_config(tmp_path), with_nvs=False) == (None, None)
    assert len(dut.events) == 1
    assert [int(offset, 16) for offset, _ in dut.events[0][1]] == [0]


def test_the_nvs_backup_is_checked_before_anything_is_pressed(tmp_path):
    found = verified(tmp_path)
    dut = FakeDut()
    with pytest.raises(RigError, match=r"nvs_backup cannot be read"):
        baseline.flash(dut, found, dut_config(tmp_path, nvs_backup=str(tmp_path / "absent.bin")))
    short = tmp_path / "short.bin"
    short.write_bytes(b"\x00" * 16)
    with pytest.raises(RigError, match=r"nvs_backup has 16 bytes, nvs_size says %d" % NVS_SIZE):
        baseline.flash(dut, found, dut_config(tmp_path, nvs_backup=str(short)))
    assert dut.events == []


def test_an_image_changed_after_load_verified_is_never_flashed(tmp_path):
    found = verified(tmp_path)
    found.path.write_bytes(IMAGE + b"\x00")
    dut = FakeDut()
    with pytest.raises(RigError, match=r"sha256 does not match the factory file"):
        baseline.flash(dut, found, dut_config(tmp_path))
    assert dut.events == []


@pytest.mark.parametrize(
    "failure",
    [
        RigError("DUT A API did not answer within 90s (last: APIConnectionError)"),
        FirmwareFailure("DUT A booted after reset_1 (ROM boot banner seen) but its API did not answer within 90s"),
    ],
)
def test_a_dut_that_never_rejoins_is_a_rig_error(tmp_path, failure):
    """The release is not the firmware under test: no rejoin is the rig's fault, never FAIL."""
    found = verified(tmp_path)
    with pytest.raises(RigError, match=r"^DUT A did not rejoin on the release baseline v2026\.11\.0 within 90 s") as info:
        baseline.flash(FakeDut(failure=failure), found, dut_config(tmp_path))
    assert not isinstance(info.value, FirmwareFailure)


def test_a_dut_on_another_version_is_a_rig_error(tmp_path):
    found = verified(tmp_path)
    with pytest.raises(RigError, match=r"reports project_version 3\.2, not the baseline's 2026\.11\.0"):
        baseline.flash(FakeDut(answer="3.2"), found, dut_config(tmp_path))


def test_the_report_names_tag_asset_digest_and_times(tmp_path):
    found = verified(tmp_path)
    cfg = dut_config(tmp_path)
    reports = config.reports_dir()
    reports.mkdir(parents=True, exist_ok=True)
    (reports / baseline.FLASH_REPORT).write_text(json.dumps({"durations_s": [70.0, 1.5]}), encoding="utf-8")
    data = baseline.write_report(reports, found, cfg, VERSION, 6.04)
    on_disk = json.loads((reports / "baseline-dut-a.json").read_text(encoding="utf-8"))
    assert on_disk == data
    assert data["tag"] == TAG
    assert data["asset"] == ASSET
    assert data["sha256"] == found.sha256
    assert data["digests_compared"] == ["api", "manifest", "sidecar"]
    assert data["flash_s"] == 71.5
    assert data["rejoin_s"] == 6.0
    assert data["version"] == VERSION
    assert data["nvs_replayed"] is True


def test_the_report_counts_only_the_digests_that_were_compared(tmp_path):
    digest = hashlib.sha256(IMAGE).hexdigest()
    directory = write_dir(tmp_path / "hil-baseline", digests={"api": None, "manifest": digest, "sidecar": digest})
    found = baseline.load_verified(directory, dut_config(tmp_path))
    data = baseline.write_report(config.reports_dir(), found, dut_config(tmp_path), None, None, nvs_replayed=False)
    assert data["digests_compared"] == ["manifest", "sidecar"]
    assert data["flash_s"] is None
    assert data["nvs_replayed"] is False


# --- config.baseline_dir ---------------------------------------------------------------------


def test_baseline_dir_needs_the_variable():
    with pytest.raises(RigError, match=r"^HIL_BASELINE_DIR is not set$"):
        config.baseline_dir({})
    assert str(config.baseline_dir({"HIL_BASELINE_DIR": "../hil-baseline"})) == "../hil-baseline"


# --- python -m hil baseline ------------------------------------------------------------------


class FakeSupervisor:
    def __init__(self):
        self.events = []

    def release_all(self):
        self.events.append("release_all")

    def close(self):
        self.events.append("close")


def cli_rig(tmp_path, monkeypatch, dut):
    cfg = dut_config(tmp_path)
    rig = SimpleNamespace(duts={"A": cfg}, dut_api_key="hil-key", supervisor_host="192.0.2.10", supervisor_key="sv")
    supervisor = FakeSupervisor()
    monkeypatch.setattr(cli, "load_rig", lambda: rig)
    monkeypatch.setattr(cli, "_rig_dut", lambda _rig: (supervisor, dut))
    return supervisor


def test_cli_flashes_confirms_prints_and_reports(tmp_path, monkeypatch, capsys):
    directory = write_dir(tmp_path / "hil-baseline")
    monkeypatch.setenv("HIL_BASELINE_DIR", str(directory))
    dut = FakeDut()
    supervisor = cli_rig(tmp_path, monkeypatch, dut)
    reports = config.reports_dir()
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "baseline-dut-a.json").write_text('{"tag": "stale"}', encoding="utf-8")
    assert cli.main(["baseline", "--dut", "A"]) == 0
    out = capsys.readouterr().out
    assert any(
        line.startswith("baseline v2026.11.0: flashed in 71.5 s, API answered after ") and line.endswith(
            "project_version 2026.11.0"
        )
        for line in out.splitlines()
    ), out
    assert supervisor.events == ["release_all", "release_all", "close"]
    assert json.loads((reports / "baseline-dut-a.json").read_text(encoding="utf-8"))["tag"] == TAG


def test_cli_dir_flag_overrides_the_variable(tmp_path, monkeypatch, capsys):
    directory = write_dir(tmp_path / "elsewhere")
    monkeypatch.delenv("HIL_BASELINE_DIR", raising=False)
    cli_rig(tmp_path, monkeypatch, FakeDut())
    assert cli.main(["baseline", "--dut", "A", "--dir", str(directory)]) == 0


def test_cli_without_nvs_writes_the_image_only(tmp_path, monkeypatch, capsys):
    directory = write_dir(tmp_path / "hil-baseline")
    dut = FakeDut()
    cli_rig(tmp_path, monkeypatch, dut)
    assert cli.main(["baseline", "--dut", "A", "--dir", str(directory), "--no-nvs"]) == 0
    assert [e[0] for e in dut.events] == ["flash_regions"]
    assert "without NVS" in capsys.readouterr().out


def test_cli_refuses_a_tampered_directory_before_any_press(tmp_path, monkeypatch, capsys):
    directory = write_dir(tmp_path / "hil-baseline")
    (directory / ASSET).write_bytes(IMAGE + b"!")
    dut = FakeDut()
    supervisor = cli_rig(tmp_path, monkeypatch, dut)
    assert cli.main(["baseline", "--dut", "A", "--dir", str(directory)]) == 3
    assert "RIG ERROR: baseline.json: sha256 does not match the factory file" in capsys.readouterr().out
    assert dut.events == []
    assert "release_all" not in supervisor.events


def test_cli_releases_the_lines_when_the_dut_never_rejoins(tmp_path, monkeypatch, capsys):
    directory = write_dir(tmp_path / "hil-baseline")
    dut = FakeDut(failure=RigError("DUT A API did not answer within 90s (last: TimeoutError)"))
    supervisor = cli_rig(tmp_path, monkeypatch, dut)
    assert cli.main(["baseline", "--dut", "A", "--dir", str(directory)]) == 3
    assert "RIG ERROR: DUT A did not rejoin on the release baseline v2026.11.0" in capsys.readouterr().out
    assert supervisor.events == ["release_all", "release_all", "close"]
    assert not (config.reports_dir() / "baseline-dut-a.json").exists()


def test_run_deletes_the_baseline_reports_of_an_earlier_run():
    assert "baseline-dut-a.json" in cli.STALE_REPORTS
    assert "baseline-flash-dut-a.json" in cli.STALE_REPORTS
