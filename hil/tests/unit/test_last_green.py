"""Last-green store (D-15): promotion gate, fail-closed load, interrupted promotion, config key. Temp dirs only."""

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from hil import RigError, config, last_green
from hil.manifest import Manifest, ManifestImage

BUILD_ID = "3.2+hil." + "a" * 12
OTHER_ID = "3.2+hil." + "b" * 12
NET_SHA = "c" * 64
MAIN = "refs/heads/main"
CLAUDE_MAIN = "refs/heads/claude/main"


@pytest.fixture
def store(tmp_path):
    return tmp_path / "store"


@pytest.fixture
def dut(store):
    return SimpleNamespace(chip="esp32s2", flash_offset="0x0", last_green_dir=str(store))


def make_manifest(tmp_path, build_id=BUILD_ID, payload=None, name="fw"):
    payload = payload if payload is not None else (build_id.encode() + b"-image-bytes") * 64
    folder = tmp_path / name
    folder.mkdir(exist_ok=True)
    path = folder / "firmware.factory.bin"
    path.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    image = ManifestImage(path=path, sha256=digest, chip="esp32s2", offset="0x0")
    return Manifest(commit="d" * 40, build_id=build_id, images={"commit": image})


def snapshot(store):
    return {p.name: p.read_bytes() for p in sorted(Path(store).iterdir())} if Path(store).is_dir() else None


def bins(store):
    return sorted(p.name for p in Path(store).glob("*.bin"))


def tamper(store, **changes):
    path = Path(store) / "manifest.json"
    data = json.loads(path.read_text())
    data.update(changes)
    path.write_text(json.dumps(data))


# ---- promote -------------------------------------------------------------------------------

def test_promote_on_main_writes_image_and_manifest_and_load_returns_it(tmp_path, dut, store):
    m = make_manifest(tmp_path)
    ok, detail = last_green.promote(dut, m, MAIN, "4242", NET_SHA)
    assert (ok, detail) == (True, BUILD_ID)
    sha = m.image("commit").sha256
    assert sorted(p.name for p in store.iterdir()) == sorted(["manifest.json", sha + ".bin"])
    for p in store.iterdir():
        assert stat.S_IMODE(p.stat().st_mode) == 0o600
    data = json.loads((store / "manifest.json").read_text())
    for key in ("schema", "commit", "build_id", "sha256", "chip", "offset", "ref", "run_id", "network_sha256", "promoted_at"):
        assert key in data, key
    assert data["schema"] == 1 and data["ref"] == MAIN and data["run_id"] == "4242"
    assert re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$", data["promoted_at"])
    stored, reason = last_green.load(dut, NET_SHA)
    assert reason == "" and stored.build_id == BUILD_ID and stored.sha256 == sha
    assert stored.path.read_bytes() == m.image("commit").path.read_bytes()
    assert (stored.commit, stored.chip, stored.offset, stored.ref, stored.run_id) == ("d" * 40, "esp32s2", "0x0", MAIN, "4242")


@pytest.mark.parametrize("ref", [CLAUDE_MAIN, "", "refs/heads/dev", "refs/pull/1/merge"])
def test_promote_refuses_other_refs_and_leaves_the_store_untouched(tmp_path, dut, store, ref):
    last_green.promote(dut, make_manifest(tmp_path, OTHER_ID, name="old"), MAIN, "1", NET_SHA)
    before = snapshot(store)
    ok, reason = last_green.promote(dut, make_manifest(tmp_path), ref, "2", NET_SHA)
    assert ok is False and reason == "ref is not refs/heads/main"
    assert snapshot(store) == before


def test_promote_refuses_a_local_build_and_leaves_no_store_behind(tmp_path, dut, store):
    ok, reason = last_green.promote(dut, make_manifest(tmp_path, BUILD_ID + ".local"), MAIN, "1", NET_SHA)
    assert ok is False and "local build" in reason
    assert not store.exists()


def test_promote_twice_with_the_same_image_says_already(tmp_path, dut, store):
    m = make_manifest(tmp_path)
    last_green.promote(dut, m, MAIN, "1", NET_SHA)
    before = snapshot(store)
    assert last_green.promote(dut, m, MAIN, "2", NET_SHA) == (False, "already " + BUILD_ID)
    assert snapshot(store) == before


def test_second_promotion_leaves_exactly_one_image(tmp_path, dut, store):
    last_green.promote(dut, make_manifest(tmp_path, BUILD_ID, name="one"), MAIN, "1", NET_SHA)
    m2 = make_manifest(tmp_path, OTHER_ID, name="two")
    assert last_green.promote(dut, m2, MAIN, "2", NET_SHA) == (True, OTHER_ID)
    assert bins(store) == [m2.image("commit").sha256 + ".bin"]
    assert last_green.load(dut, NET_SHA)[0].build_id == OTHER_ID


def test_promote_after_a_network_change_replaces_the_stale_store(tmp_path, dut, store):
    m = make_manifest(tmp_path)
    last_green.promote(dut, m, MAIN, "1", NET_SHA)
    assert last_green.load(dut, "e" * 64)[1] == "store invalid: network hash differs from hil-network.yaml"
    assert last_green.promote(dut, m, MAIN, "2", "e" * 64) == (True, BUILD_ID)
    assert last_green.load(dut, "e" * 64)[0] is not None


def test_an_oserror_becomes_a_reason_naming_the_error_class(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a directory")
    dut = SimpleNamespace(chip="esp32s2", flash_offset="0x0", last_green_dir=str(blocker / "store"))
    ok, reason = last_green.promote(dut, make_manifest(tmp_path), MAIN, "1", NET_SHA)
    assert ok is False and reason in ("NotADirectoryError", "FileNotFoundError", "OSError")


# ---- load ----------------------------------------------------------------------------------

def test_load_of_a_missing_directory(dut):
    assert last_green.load(dut, NET_SHA) == (None, "store missing")


def test_load_of_a_directory_without_manifest(dut, store):
    store.mkdir()
    (store / "stray.bin").write_bytes(b"x")
    assert last_green.load(dut, NET_SHA) == (None, "store empty")


@pytest.fixture
def promoted(tmp_path, dut, store):
    m = make_manifest(tmp_path)
    last_green.promote(dut, m, MAIN, "1", NET_SHA)
    return m


def test_malformed_json_is_invalid(promoted, dut, store):
    (store / "manifest.json").write_text("{not json")
    assert last_green.load(dut, NET_SHA)[1].startswith("store invalid: ")


@pytest.mark.parametrize(
    "changes, needle",
    [
        ({"schema": 2}, "schema"),
        ({"ref": CLAUDE_MAIN}, "ref"),
        ({"ref": ""}, "ref"),
        ({"chip": "esp32c6"}, "chip"),
        ({"offset": "0x10000"}, "offset"),
        ({"offset": "zz"}, "offset"),
        ({"build_id": "3.2+hil.xyz"}, "build ID"),
        ({"build_id": BUILD_ID + ".local"}, "build ID"),
        ({"build_id": "3.2"}, "build ID"),
        ({"network_sha256": "f" * 64}, "network hash"),
        ({"sha256": "../etc/passwd"}, "sha256"),
        ({"sha256": "a" * 64, "file": "a" * 64 + ".bin"}, "image file is missing"),
        ({"file": "other.bin"}, "file name"),
        ({"file": "../x.bin"}, "file name"),
        ({"file": ".."}, "file name"),
        ({"file": "sub/x.bin"}, "file name"),
    ],
)
def test_each_manifest_check_rejects_with_a_named_reason(promoted, dut, store, changes, needle):
    tamper(store, **changes)
    image, reason = last_green.load(dut, NET_SHA)
    assert image is None and reason.startswith("store invalid: ") and needle in reason


def test_a_missing_image_file_is_invalid(promoted, dut, store):
    (store / (promoted.image("commit").sha256 + ".bin")).unlink()
    assert last_green.load(dut, NET_SHA) == (None, "store invalid: image file is missing")


def test_one_flipped_byte_is_a_sha256_mismatch(promoted, dut, store):
    path = store / (promoted.image("commit").sha256 + ".bin")
    data = bytearray(path.read_bytes())
    data[100] ^= 0xFF
    path.write_bytes(data)
    assert last_green.load(dut, NET_SHA) == (None, "store invalid: sha256 mismatch")


def test_a_symlinked_image_is_refused(promoted, dut, store, tmp_path):
    path = store / (promoted.image("commit").sha256 + ".bin")
    target = tmp_path / "elsewhere.bin"
    target.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(target)
    assert last_green.load(dut, NET_SHA)[1] == "store invalid: image file is not a regular file"


def test_chip_and_offset_come_from_rig_toml(promoted, store):
    other = SimpleNamespace(chip="esp32s2", flash_offset="0x1000", last_green_dir=str(store))
    assert last_green.load(other, NET_SHA)[1] == "store invalid: offset does not match rig.toml"


# ---- interrupted promotion ---------------------------------------------------------------------

def test_interrupted_promotion_still_loads_the_previous_image(tmp_path, dut, store, monkeypatch):
    last_green.promote(dut, make_manifest(tmp_path, BUILD_ID, name="one"), MAIN, "1", NET_SHA)
    m2 = make_manifest(tmp_path, OTHER_ID, name="two")
    real = os.replace

    def crash_on_manifest(src, dst):
        if str(dst).endswith("manifest.json"):
            raise OSError("power cut")
        return real(src, dst)

    monkeypatch.setattr(last_green.os, "replace", crash_on_manifest)
    ok, reason = last_green.promote(dut, m2, MAIN, "2", NET_SHA)
    assert (ok, reason) == (False, "OSError")
    assert (store / "manifest.json.tmp").exists() and len(bins(store)) == 2  # new image written, manifest not switched
    assert last_green.load(dut, NET_SHA)[0].build_id == BUILD_ID
    monkeypatch.setattr(last_green.os, "replace", real)
    assert last_green.promote(dut, m2, MAIN, "3", NET_SHA) == (True, OTHER_ID)
    assert bins(store) == [m2.image("commit").sha256 + ".bin"]
    assert not list(store.glob("*.tmp"))
    assert last_green.load(dut, NET_SHA)[0].build_id == OTHER_ID


def test_new_manifest_pointing_at_a_half_written_image_is_never_accepted(promoted, dut, store):
    sha = promoted.image("commit").sha256
    (store / (sha + ".bin")).write_bytes(b"half")
    assert last_green.load(dut, NET_SHA)[1] == "store invalid: sha256 mismatch"


# ---- constant and helpers ----------------------------------------------------------------------

def test_store_ref_is_main_and_is_the_only_ref_literal():
    assert last_green.STORE_REF == "refs/heads/main"
    source = Path(last_green.__file__).read_text(encoding="utf-8")
    assert len(re.findall(r"refs/", source)) == 1


def test_network_sha256_hashes_the_bytes_of_the_file(tmp_path):
    path = tmp_path / "hil-network.yaml"
    path.write_bytes(b'hil_dut_api_key: "x"\n')
    assert last_green.network_sha256(path) == hashlib.sha256(b'hil_dut_api_key: "x"\n').hexdigest()
    with pytest.raises(RigError):
        last_green.network_sha256(tmp_path / "missing.yaml")


# ---- config ------------------------------------------------------------------------------------

def rig_toml(last_green_line):
    return """
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
%s
""" % ("b" * 64, last_green_line)


def load_config(tmp_path, line):
    cfg = tmp_path / "rig.toml"
    cfg.write_text(rig_toml(line), encoding="utf-8")
    net = tmp_path / "hil-network.yaml"
    net.write_text('hil_dut_api_key: "dut-key-0123456789"\n', encoding="utf-8")
    return config.load(env={"HIL_RIG_CONFIG": str(cfg), "HIL_SUPERVISOR_KEY": "sv-key-0123456789"}, network_file=net)


def test_config_accepts_an_absolute_last_green_dir(tmp_path):
    cfg = load_config(tmp_path, 'last_green_dir = "/var/lib/hil/last-green/dut-a"')
    assert cfg.duts["A"].last_green_dir == "/var/lib/hil/last-green/dut-a"


@pytest.mark.parametrize("line", ["", 'last_green_dir = "relative/dir"', 'last_green_dir = ""', "last_green_dir = 5"])
def test_config_refuses_a_missing_or_relative_last_green_dir_naming_the_key(tmp_path, line):
    with pytest.raises(RigError, match="last_green_dir"):
        load_config(tmp_path, line)


def test_a_missing_store_directory_is_not_a_config_error(tmp_path):
    load_config(tmp_path, 'last_green_dir = "/nonexistent/last-green"')
