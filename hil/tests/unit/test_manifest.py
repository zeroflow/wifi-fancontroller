"""manifest.load_verified: every mismatch is a RigError before any hardware is touched."""

import hashlib
import json
from types import SimpleNamespace

import pytest

from hil import RigError, manifest

COMMIT = "a" * 40
BUILD_ID = "3.2+hil." + "a" * 12
QC_ID = "3.2+qc." + "a" * 12
CANARY_ID = "3.2+canary." + "a" * 12
BROKEN_ID = "3.2+broken." + "a" * 12
DUT = SimpleNamespace(id="A", rev="3.2", chip="esp32s2", flash_offset="0x0")
IMAGE = b"synthetic image bytes"
COMMIT_OTA = b"synthetic commit ota bytes"
QC_OTA = b"synthetic qc-auto ota bytes"
CANARY_OTA = b"synthetic canary ota bytes"
BROKEN_OTA = b"synthetic broken ota bytes"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def commit_entry():
    return {
        "role": "commit",
        "rev": "3.2",
        "chip": "esp32s2",
        "offset": "0x0",
        "framework": "arduino",
        "build_id": BUILD_ID,
        "final": True,
        "esphome_name": "fancontroller-r3-2",
        "file": "firmware.factory.bin",
        "sha256": sha(IMAGE),
        "ota_file": "firmware.ota.bin",
        "ota_sha256": sha(COMMIT_OTA),
    }


def qc_entry():
    return {
        "role": "qc-auto",
        "rev": "3.2",
        "chip": "esp32s2",
        "offset": "0x0",
        "framework": "arduino",
        "build_id": QC_ID,
        "final": False,
        "esphome_name": "fancontroller-qc-r3-2",
        "ota_file": "qc-auto-3.2.ota.bin",
        "ota_sha256": sha(QC_OTA),
        "fan_hz": 25000,
    }


def canary_entry():
    return {
        "role": "canary",
        "rev": "3.2",
        "chip": "esp32s2",
        "offset": "0x0",
        "framework": "arduino",
        "build_id": CANARY_ID,
        "final": False,
        "esphome_name": "fancontroller-can-r3-2",
        "ota_file": "canary-3.2.ota.bin",
        "ota_sha256": sha(CANARY_OTA),
        "fan_hz": 25000,
    }


def broken_entry():
    return {
        "role": "broken",
        "rev": "3.2",
        "chip": "esp32s2",
        "offset": "0x0",
        "framework": "arduino",
        "build_id": BROKEN_ID,
        "final": False,
        "esphome_name": "fancontroller-brk-r3-2",
        "ota_file": "broken-3.2.ota.bin",
        "ota_sha256": sha(BROKEN_OTA),
        "fan_hz": 25000,
    }


FILES = {
    "firmware.factory.bin": IMAGE,
    "firmware.ota.bin": COMMIT_OTA,
    "qc-auto-3.2.ota.bin": QC_OTA,
    "canary-3.2.ota.bin": CANARY_OTA,
    "broken-3.2.ota.bin": BROKEN_OTA,
}


def write(tmp_path, top, entries):
    top = dict(top)
    top["images"] = entries
    (tmp_path / "manifest.json").write_text(json.dumps(top), encoding="utf-8")
    for name, data in FILES.items():
        (tmp_path / name).write_bytes(data)
    return tmp_path


def make(tmp_path, extra=(qc_entry,), top=None, **override):
    """A well-formed schema-2 firmware directory; overrides apply to the commit entry."""
    entry = commit_entry()
    entry.update(override)
    header = {"schema": 2, "commit": COMMIT, "build_id": BUILD_ID, "esphome_version": "2026.10.1"}
    header.update(top or {})
    return write(tmp_path, header, [entry] + [build() for build in extra])


def test_well_formed_manifest_is_accepted(tmp_path):
    verified = manifest.load_verified(make(tmp_path), COMMIT, DUT)
    assert verified.build_id == BUILD_ID
    assert verified.image("commit").path.name == "firmware.factory.bin"


def test_commit_plus_qc_auto_is_accepted(tmp_path):
    verified = manifest.load_verified(make(tmp_path), COMMIT, DUT)
    assert sorted(verified.images) == [("commit", "3.2"), ("qc-auto", "3.2")]


def test_commit_only_is_accepted(tmp_path):
    verified = manifest.load_verified(make(tmp_path, extra=()), COMMIT, DUT)
    assert sorted(verified.images) == [("commit", "3.2")]


def test_all_three_roles_are_accepted(tmp_path):
    verified = manifest.load_verified(make(tmp_path, extra=(qc_entry, canary_entry)), COMMIT, DUT)
    assert sorted(role for role, _rev in verified.images) == ["canary", "commit", "qc-auto"]


def test_schema_1_is_refused(tmp_path):
    with pytest.raises(RigError, match="schema must be 2"):
        manifest.load_verified(make(tmp_path, top={"schema": 1}), COMMIT, DUT)


def test_local_suffix_in_build_id_is_accepted_on_every_role(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    local = {"build_id": BUILD_ID + ".local"}
    root = write(
        tmp_path,
        {"schema": 2, "commit": COMMIT, "build_id": BUILD_ID + ".local", "esphome_version": "x"},
        [dict(commit_entry(), **local), dict(qc_entry(), build_id=QC_ID + ".local")],
    )
    verified = manifest.load_verified(root, COMMIT, DUT)
    assert verified.build_id.endswith(".local")
    assert verified.image("qc-auto").build_id.endswith(".local")


def test_commit_mismatch_is_rejected(tmp_path):
    with pytest.raises(RigError, match="does not match expected"):
        manifest.load_verified(make(tmp_path), "b" * 40, DUT)


def test_sha256_mismatch_is_rejected(tmp_path):
    with pytest.raises(RigError, match="sha256"):
        manifest.load_verified(make(tmp_path, sha256="0" * 64), COMMIT, DUT)


def test_ota_sha256_mismatch_is_rejected(tmp_path):
    root = write(
        tmp_path,
        {"schema": 2, "commit": COMMIT, "build_id": BUILD_ID, "esphome_version": "x"},
        [commit_entry(), dict(qc_entry(), ota_sha256="0" * 64)],
    )
    with pytest.raises(RigError, match="ota_sha256"):
        manifest.load_verified(root, COMMIT, DUT)


def test_a_tampered_ota_file_is_rejected(tmp_path):
    root = make(tmp_path)
    (root / "qc-auto-3.2.ota.bin").write_bytes(b"swapped after the build")
    with pytest.raises(RigError, match="ota_sha256"):
        manifest.load_verified(root, COMMIT, DUT)


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


@pytest.mark.parametrize("name", ["../x", "a/b", "..", "a..b.ota.bin"])
def test_ota_file_name_with_path_separator_or_dotdot_is_rejected(tmp_path, name):
    root = write(
        tmp_path,
        {"schema": 2, "commit": COMMIT, "build_id": BUILD_ID, "esphome_version": "x"},
        [commit_entry(), dict(qc_entry(), ota_file=name)],
    )
    with pytest.raises(RigError, match="bare file name"):
        manifest.load_verified(root, COMMIT, DUT)


def test_missing_image_file_is_rejected(tmp_path):
    with pytest.raises(RigError, match="not in the firmware directory"):
        manifest.load_verified(make(tmp_path, file="other.bin"), COMMIT, DUT)


@pytest.mark.parametrize("build_id", ["4.0+hil." + "a" * 12, "3.2+hil.devbuild", "3.2+hil." + "a" * 11, "3.2+hil." + "A" * 12])
def test_build_id_with_wrong_prefix_or_shape_is_rejected(tmp_path, build_id):
    with pytest.raises(RigError, match="build_id"):
        manifest.load_verified(make(tmp_path, build_id=build_id, top={"build_id": build_id}), COMMIT, DUT)


def test_unknown_role_is_rejected(tmp_path):
    root = write(
        tmp_path,
        {"schema": 2, "commit": COMMIT, "build_id": BUILD_ID, "esphome_version": "x"},
        [commit_entry(), dict(qc_entry(), role="mystery")],
    )
    with pytest.raises(RigError, match="role"):
        manifest.load_verified(root, COMMIT, DUT)


def test_duplicate_role_and_rev_is_rejected(tmp_path):
    root = write(
        tmp_path,
        {"schema": 2, "commit": COMMIT, "build_id": BUILD_ID, "esphome_version": "x"},
        [commit_entry(), qc_entry(), qc_entry()],
    )
    with pytest.raises(RigError, match="duplicate"):
        manifest.load_verified(root, COMMIT, DUT)


def test_final_true_on_qc_auto_is_rejected(tmp_path):
    root = write(
        tmp_path,
        {"schema": 2, "commit": COMMIT, "build_id": BUILD_ID, "esphome_version": "x"},
        [commit_entry(), dict(qc_entry(), final=True)],
    )
    with pytest.raises(RigError, match="final"):
        manifest.load_verified(root, COMMIT, DUT)


def test_final_true_on_canary_is_rejected(tmp_path):
    root = write(
        tmp_path,
        {"schema": 2, "commit": COMMIT, "build_id": BUILD_ID, "esphome_version": "x"},
        [commit_entry(), dict(canary_entry(), final=True)],
    )
    with pytest.raises(RigError, match="final"):
        manifest.load_verified(root, COMMIT, DUT)


def test_final_false_on_commit_is_rejected(tmp_path):
    with pytest.raises(RigError, match="final"):
        manifest.load_verified(make(tmp_path, final=False), COMMIT, DUT)


def test_final_must_be_a_bool(tmp_path):
    with pytest.raises(RigError, match="final"):
        manifest.load_verified(make(tmp_path, final="yes"), COMMIT, DUT)


def test_qc_auto_build_id_with_a_different_commit_part_is_rejected(tmp_path):
    root = write(
        tmp_path,
        {"schema": 2, "commit": COMMIT, "build_id": BUILD_ID, "esphome_version": "x"},
        [commit_entry(), dict(qc_entry(), build_id="3.2+qc." + "b" * 12)],
    )
    with pytest.raises(RigError, match="build_id"):
        manifest.load_verified(root, COMMIT, DUT)


def test_qc_auto_build_id_with_the_commit_prefix_is_rejected(tmp_path):
    root = write(
        tmp_path,
        {"schema": 2, "commit": COMMIT, "build_id": BUILD_ID, "esphome_version": "x"},
        [commit_entry(), dict(qc_entry(), build_id=BUILD_ID)],
    )
    with pytest.raises(RigError, match="build_id"):
        manifest.load_verified(root, COMMIT, DUT)


def test_two_commit_entries_are_rejected(tmp_path):
    root = write(
        tmp_path,
        {"schema": 2, "commit": COMMIT, "build_id": BUILD_ID, "esphome_version": "x"},
        [commit_entry(), commit_entry()],
    )
    with pytest.raises(RigError, match="duplicate|exactly one"):
        manifest.load_verified(root, COMMIT, DUT)


def test_commit_entry_without_a_factory_file_is_rejected(tmp_path):
    entry = commit_entry()
    del entry["file"], entry["sha256"]
    root = write(tmp_path, {"schema": 2, "commit": COMMIT, "build_id": BUILD_ID, "esphome_version": "x"}, [entry])
    with pytest.raises(RigError, match="file"):
        manifest.load_verified(root, COMMIT, DUT)


def test_no_commit_entry_is_rejected(tmp_path):
    root = write(tmp_path, {"schema": 2, "commit": COMMIT, "build_id": BUILD_ID, "esphome_version": "x"}, [qc_entry()])
    with pytest.raises(RigError, match="exactly one"):
        manifest.load_verified(root, COMMIT, DUT)


def test_error_text_never_carries_a_hash(tmp_path):
    with pytest.raises(RigError) as info:
        manifest.load_verified(make(tmp_path, sha256="0" * 64), COMMIT, DUT)
    assert "0" * 16 not in str(info.value) and sha(IMAGE)[:16] not in str(info.value)


def test_qc_auto_image_carries_ota_path_and_fan_hz(tmp_path):
    verified = manifest.load_verified(make(tmp_path), COMMIT, DUT)
    image = verified.image("qc-auto")
    assert image.ota_path.name == "qc-auto-3.2.ota.bin"
    assert image.fan_hz == 25000
    assert image.final is False
    assert image.path is None and image.sha256 == ""
    assert image.ota_sha256 == sha(QC_OTA)
    assert image.build_id == QC_ID and image.framework == "arduino"


def test_commit_image_is_final_and_has_both_files(tmp_path):
    image = manifest.load_verified(make(tmp_path), COMMIT, DUT).image("commit")
    assert image.final is True and image.rev == "3.2" and image.role == "commit"
    assert image.path.name == "firmware.factory.bin" and image.ota_path.name == "firmware.ota.bin"


def test_image_with_an_explicit_rev(tmp_path):
    verified = manifest.load_verified(make(tmp_path), COMMIT, DUT)
    assert verified.image("qc-auto", "3.2").role == "qc-auto"


def test_image_lookup_miss_names_role_and_rev(tmp_path):
    verified = manifest.load_verified(make(tmp_path, extra=()), COMMIT, DUT)
    with pytest.raises(RigError, match="no image with role 'canary' for rev 3.2"):
        verified.image("canary")


def test_chip_of_a_qc_auto_entry_for_the_dut_rev_is_checked_too(tmp_path):
    root = write(
        tmp_path,
        {"schema": 2, "commit": COMMIT, "build_id": BUILD_ID, "esphome_version": "x"},
        [commit_entry(), dict(qc_entry(), chip="esp32c6")],
    )
    with pytest.raises(RigError, match="chip"):
        manifest.load_verified(root, COMMIT, DUT)


def test_a_factory_file_on_a_qc_auto_entry_is_rejected(tmp_path):
    root = write(
        tmp_path,
        {"schema": 2, "commit": COMMIT, "build_id": BUILD_ID, "esphome_version": "x"},
        [commit_entry(), dict(qc_entry(), file="firmware.factory.bin", sha256=sha(IMAGE))],
    )
    with pytest.raises(RigError, match="only the commit image has a factory file"):
        manifest.load_verified(root, COMMIT, DUT)


def test_all_four_roles_are_accepted(tmp_path):
    verified = manifest.load_verified(make(tmp_path, extra=(qc_entry, canary_entry, broken_entry)), COMMIT, DUT)
    assert sorted(role for role, _rev in verified.images) == ["broken", "canary", "commit", "qc-auto"]


def test_broken_role_is_accepted_as_an_ota_only_non_final_image(tmp_path):
    image = manifest.load_verified(make(tmp_path, extra=(qc_entry, broken_entry)), COMMIT, DUT).image("broken")
    assert image.role == "broken" and image.final is False
    assert image.path is None and image.sha256 == ""
    assert image.ota_path.name == "broken-3.2.ota.bin" and image.ota_sha256 == sha(BROKEN_OTA)
    assert image.build_id == BROKEN_ID and image.framework == "arduino"


def test_the_broken_image_is_never_the_final_role(tmp_path):
    assert manifest.FINAL_ROLE == "commit"
    root = write(
        tmp_path,
        {"schema": 2, "commit": COMMIT, "build_id": BUILD_ID, "esphome_version": "x"},
        [commit_entry(), dict(broken_entry(), final=True)],
    )
    with pytest.raises(RigError, match="only the commit image may be final"):
        manifest.load_verified(root, COMMIT, DUT)


def test_a_factory_file_on_a_broken_entry_is_refused(tmp_path):
    root = write(
        tmp_path,
        {"schema": 2, "commit": COMMIT, "build_id": BUILD_ID, "esphome_version": "x"},
        [commit_entry(), dict(broken_entry(), file="firmware.factory.bin", sha256=sha(IMAGE))],
    )
    with pytest.raises(RigError, match="only the commit image has a factory file"):
        manifest.load_verified(root, COMMIT, DUT)


@pytest.mark.parametrize("build_id", [QC_ID, BUILD_ID, "3.2+broken." + "b" * 12, "3.2+broken.devbuild"])
def test_a_broken_entry_needs_its_own_build_id_from_the_same_commit(tmp_path, build_id):
    root = write(
        tmp_path,
        {"schema": 2, "commit": COMMIT, "build_id": BUILD_ID, "esphome_version": "x"},
        [commit_entry(), dict(broken_entry(), build_id=build_id)],
    )
    with pytest.raises(RigError, match="build_id"):
        manifest.load_verified(root, COMMIT, DUT)


def test_a_broken_entry_without_an_ota_file_is_refused(tmp_path):
    entry = broken_entry()
    del entry["ota_file"]
    root = write(
        tmp_path,
        {"schema": 2, "commit": COMMIT, "build_id": BUILD_ID, "esphome_version": "x"},
        [commit_entry(), entry],
    )
    with pytest.raises(RigError, match="ota_file"):
        manifest.load_verified(root, COMMIT, DUT)


# ---- IN-01: every build ID is tied to the commit under test, and a local build never reaches CI ----


def all_ids_from(hex12, local=""):
    """A manifest whose build IDs all carry `hex12` (the commit field stays COMMIT)."""
    ids = {
        "commit": "3.2+hil." + hex12 + local,
        "qc-auto": "3.2+qc." + hex12 + local,
        "canary": "3.2+canary." + hex12 + local,
        "broken": "3.2+broken." + hex12 + local,
    }
    entries = [dict(build(), build_id=ids[build()["role"]]) for build in
               (commit_entry, qc_entry, canary_entry, broken_entry)]
    return {"schema": 2, "commit": COMMIT, "build_id": ids["commit"], "esphome_version": "x"}, entries


def test_a_build_id_from_another_commit_is_refused_even_when_all_ids_agree(tmp_path):
    header, entries = all_ids_from("b" * 12)
    with pytest.raises(RigError, match="manifest: build_id is not from commit " + "a" * 12):
        manifest.load_verified(write(tmp_path, header, entries), COMMIT, DUT)


def test_a_build_id_from_the_commit_is_accepted(tmp_path):
    header, entries = all_ids_from(COMMIT[:12])
    verified = manifest.load_verified(write(tmp_path, header, entries), COMMIT, DUT)
    assert verified.build_id == BUILD_ID


def test_a_local_build_is_refused_in_ci(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    header, entries = all_ids_from(COMMIT[:12], ".local")
    with pytest.raises(RigError, match="manifest: a .local build is refused in CI"):
        manifest.load_verified(write(tmp_path, header, entries), COMMIT, DUT)


def test_a_local_build_is_accepted_outside_ci(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    header, entries = all_ids_from(COMMIT[:12], ".local")
    verified = manifest.load_verified(write(tmp_path, header, entries), COMMIT, DUT)
    assert verified.build_id.endswith(".local")


def test_a_clean_build_is_accepted_in_ci(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    header, entries = all_ids_from(COMMIT[:12])
    assert manifest.load_verified(write(tmp_path, header, entries), COMMIT, DUT).build_id == BUILD_ID


def test_a_missing_offset_is_reported_as_missing_not_as_a_mismatch(tmp_path):
    entry = commit_entry()
    del entry["offset"]
    root = write(tmp_path, {"schema": 2, "commit": COMMIT, "build_id": BUILD_ID, "esphome_version": "x"}, [entry])
    with pytest.raises(RigError, match="manifest: image offset is missing"):
        manifest.load_verified(root, COMMIT, DUT)


def test_a_non_string_offset_is_reported_as_missing(tmp_path):
    root = write(tmp_path, {"schema": 2, "commit": COMMIT, "build_id": BUILD_ID, "esphome_version": "x"},
                 [dict(commit_entry(), offset=0)])
    with pytest.raises(RigError, match="manifest: image offset is missing"):
        manifest.load_verified(root, COMMIT, DUT)
