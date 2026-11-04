"""Manifest verification: the only route from a build to hardware (CI-01).

load_verified() raises RigError on any mismatch, before any button press. Schema 2
lists one entry per image (role commit, qc-auto, canary or broken). Only the commit image
is `final`: it is the one that may stay on DUT A or enter the last-green store (D-25).
The broken image (D-40) is an OTA-only file: no factory file, never final, never a heal image.
Every error names a field, never a hash value or a path outside the firmware directory.
"""

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import RigError

SCHEMA = 2
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
# The 12 hex digits are group 1, the optional ".local" marker of a local build is group 2.
ROLE_BUILD_ID_RE = {
    "commit": re.compile(r"^3\.2\+hil\.([0-9a-f]{12})(\.local)?$"),
    "qc-auto": re.compile(r"^3\.2\+qc\.([0-9a-f]{12})(\.local)?$"),
    "canary": re.compile(r"^3\.2\+canary\.([0-9a-f]{12})(\.local)?$"),
    "broken": re.compile(r"^3\.2\+broken\.([0-9a-f]{12})(\.local)?$"),
}
BUILD_ID_RE = ROLE_BUILD_ID_RE["commit"]
BARE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
FINAL_ROLE = "commit"


@dataclass(frozen=True)
class ManifestImage:
    """One verified image. `path`/`sha256` are the serial-flash file (commit only)."""

    path: Optional[Path]
    sha256: str
    chip: str
    offset: str
    role: str = "commit"
    rev: str = "3.2"
    build_id: str = ""
    final: bool = True
    framework: str = ""
    ota_path: Optional[Path] = None
    ota_sha256: str = ""
    fan_hz: Optional[int] = None


@dataclass(frozen=True)
class Manifest:
    commit: str
    build_id: str
    images: dict  # keyed by (role, rev)

    def image(self, role, rev=None):
        if rev is None:
            rev = next((r for (name, r) in self.images if name == "commit"), None)
        try:
            return self.images[(role, rev)]
        except KeyError:
            raise RigError("manifest has no image with role '%s' for rev %s" % (role, rev)) from None


def _bare_name(entry, key):
    name = entry.get(key)
    if not isinstance(name, str) or not BARE_NAME_RE.match(name) or ".." in name:
        raise RigError("manifest: image %s must be a bare file name" % key)
    return name


def _verified_file(fw_dir, entry, key, digest_key):
    """Path of the file named by entry[key] after its sha256 matched entry[digest_key]."""
    name = _bare_name(entry, key)
    path = fw_dir / name
    if not path.is_file():
        raise RigError("manifest: image %s %s is not in the firmware directory" % (key, name))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != entry.get(digest_key):
        raise RigError("manifest: %s of %s does not match the file" % (digest_key, name))
    return path, digest


def _build_id_parts(role, build_id):
    pattern = ROLE_BUILD_ID_RE.get(role)
    match = pattern.match(build_id) if pattern and isinstance(build_id, str) else None
    if not match:
        raise RigError("manifest: build_id of the %s image has an unexpected format" % role)
    return match.group(1), bool(match.group(2))


def load_verified(fw_dir, expected_commit, dut):
    fw_dir = Path(fw_dir)
    if not expected_commit or not COMMIT_RE.match(expected_commit):
        raise RigError("expected commit (HIL_EXPECTED_COMMIT or GITHUB_SHA) is not 40 lowercase hex")
    try:
        data = json.loads((fw_dir / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise RigError("manifest.json is missing or not valid JSON") from None
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise RigError("manifest: schema must be %d" % SCHEMA)
    commit = data.get("commit")
    if not isinstance(commit, str) or not COMMIT_RE.match(commit):
        raise RigError("manifest: commit is not 40 lowercase hex")
    if commit != expected_commit:
        raise RigError("manifest: commit %s does not match expected %s" % (commit[:12], expected_commit[:12]))
    build_id = data.get("build_id")
    if not isinstance(build_id, str) or not BUILD_ID_RE.match(build_id):
        raise RigError("manifest: build_id has an unexpected format")
    top_hex, top_local = _build_id_parts("commit", build_id)
    # IN-01: the 12 hex digits must be the commit under test, and a local build never runs in CI.
    if top_hex != expected_commit[:12]:
        raise RigError("manifest: build_id is not from commit %s" % expected_commit[:12])
    if top_local and os.environ.get("GITHUB_ACTIONS") == "true":
        raise RigError("manifest: a .local build is refused in CI")
    entries = data.get("images")
    if not isinstance(entries, list) or not entries:
        raise RigError("manifest: images must be a non-empty list")

    images = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise RigError("manifest: every image entry must be an object")
        role = entry.get("role")
        if role not in ROLE_BUILD_ID_RE:
            raise RigError("manifest: image role is not one of %s" % ", ".join(sorted(ROLE_BUILD_ID_RE)))
        rev = entry.get("rev")
        if not isinstance(rev, str) or not rev:
            raise RigError("manifest: image rev must be a non-empty string")
        if (role, rev) in images:
            raise RigError("manifest: duplicate image for role '%s' rev %s" % (role, rev))
        final = entry.get("final")
        if not isinstance(final, bool):
            raise RigError("manifest: image final must be true or false")
        if final != (role == FINAL_ROLE):
            raise RigError("manifest: only the commit image may be final, and it must be")
        entry_hex, entry_local = _build_id_parts(role, entry.get("build_id"))
        if entry_hex != top_hex or entry_local != top_local:
            raise RigError("manifest: build_id of the %s image is not from the commit's build" % role)
        if role == FINAL_ROLE and entry["build_id"] != build_id:
            raise RigError("manifest: build_id of the commit image differs from the top-level build_id")

        path, digest = None, ""
        if role == FINAL_ROLE:
            if "file" not in entry:
                raise RigError("manifest: the commit image has no file")
            path, digest = _verified_file(fw_dir, entry, "file", "sha256")
        elif "file" in entry or "sha256" in entry:
            raise RigError("manifest: only the commit image has a factory file")
        ota_path, ota_digest = _verified_file(fw_dir, entry, "ota_file", "ota_sha256")

        if rev == dut.rev:
            if entry.get("chip") != dut.chip:
                raise RigError("manifest: chip %s does not match DUT %s chip %s" % (entry.get("chip"), dut.id, dut.chip))
            if not isinstance(entry.get("offset"), str):
                raise RigError("manifest: image offset is missing")
            try:
                offset_ok = int(entry["offset"], 16) == int(dut.flash_offset, 16)
            except ValueError:
                offset_ok = False
            if not offset_ok:
                raise RigError("manifest: flash offset does not match DUT %s flash_offset" % dut.id)
        fan_hz = entry.get("fan_hz")
        if fan_hz is not None and (isinstance(fan_hz, bool) or not isinstance(fan_hz, int) or fan_hz <= 0):
            raise RigError("manifest: image fan_hz must be a positive integer")
        images[(role, rev)] = ManifestImage(
            path=path,
            sha256=digest,
            chip=entry.get("chip", ""),
            offset=entry.get("offset", ""),
            role=role,
            rev=rev,
            build_id=entry["build_id"],
            final=final,
            framework=entry.get("framework", ""),
            ota_path=ota_path,
            ota_sha256=ota_digest,
            fan_hz=fan_hz,
        )

    commit_images = [key for key in images if key[0] == FINAL_ROLE]
    dut_commit = [key for key in commit_images if key[1] == dut.rev]
    if len(commit_images) != 1 or len(dut_commit) != 1:
        raise RigError("manifest: expected exactly one image with role 'commit' for rev %s" % dut.rev)
    return Manifest(commit=commit, build_id=build_id, images=images)
