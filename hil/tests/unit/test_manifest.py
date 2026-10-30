"""manifest.load_verified: every mismatch is a RigError before any hardware is touched."""

import hashlib
import json
from types import SimpleNamespace

import pytest

from hil import RigError, manifest

COMMIT = "a" * 40
BUILD_ID = "3.2+hil." + "a" * 12
DUT = SimpleNamespace(id="A", chip="esp32s2", flash_offset="0x0")
IMAGE = b"synthetic image bytes"


def make(tmp_path, **override):
    """Write a well-formed firmware directory, then apply overrides to the image entry."""
    entry = {
        "role": "commit",
        "file": "firmware.factory.bin",
        "sha256": hashlib.sha256(IMAGE).hexdigest(),
        "chip": "esp32s2",
        "offset": "0x0",
    }
    top = {"schema": 1, "commit": COMMIT, "build_id": BUILD_ID}
    for key, value in override.items():
        (top if key in top else entry)[key] = value
    top["images"] = [entry]
    (tmp_path / "manifest.json").write_text(json.dumps(top), encoding="utf-8")
    if "firmware.factory.bin" == entry["file"]:
        (tmp_path / entry["file"]).write_bytes(IMAGE)
    return tmp_path


def test_well_formed_manifest_is_accepted(tmp_path):
    verified = manifest.load_verified(make(tmp_path), COMMIT, DUT)
    assert verified.build_id == BUILD_ID
    assert verified.image("commit").path.name == "firmware.factory.bin"


def test_local_suffix_in_build_id_is_accepted(tmp_path):
    verified = manifest.load_verified(make(tmp_path, build_id=BUILD_ID + ".local"), COMMIT, DUT)
    assert verified.build_id.endswith(".local")


def test_commit_mismatch_is_rejected(tmp_path):
    with pytest.raises(RigError, match="does not match expected"):
        manifest.load_verified(make(tmp_path), "b" * 40, DUT)


def test_sha256_mismatch_is_rejected(tmp_path):
    with pytest.raises(RigError, match="sha256"):
        manifest.load_verified(make(tmp_path, sha256="0" * 64), COMMIT, DUT)


def test_chip_mismatch_is_rejected(tmp_path):
    with pytest.raises(RigError, match="chip"):
        manifest.load_verified(make(tmp_path, chip="esp32c6"), COMMIT, DUT)


def test_offset_mismatch_is_rejected(tmp_path):
    with pytest.raises(RigError, match="offset"):
        manifest.load_verified(make(tmp_path, offset="0x1000"), COMMIT, DUT)


@pytest.mark.parametrize("name", ["sub/firmware.factory.bin", "../firmware.factory.bin", "a..b.bin", "/etc/passwd"])
def test_file_name_with_path_separator_or_dotdot_is_rejected(tmp_path, name):
    with pytest.raises(RigError, match="bare file name"):
        manifest.load_verified(make(tmp_path, file=name), COMMIT, DUT)


def test_missing_image_file_is_rejected(tmp_path):
    with pytest.raises(RigError, match="not in the firmware directory"):
        manifest.load_verified(make(tmp_path, file="other.bin"), COMMIT, DUT)


@pytest.mark.parametrize("build_id", ["4.0+hil." + "a" * 12, "3.2+hil.devbuild", "3.2+hil." + "a" * 11, "3.2+hil." + "A" * 12])
def test_build_id_with_wrong_prefix_or_shape_is_rejected(tmp_path, build_id):
    with pytest.raises(RigError, match="build_id"):
        manifest.load_verified(make(tmp_path, build_id=build_id), COMMIT, DUT)
