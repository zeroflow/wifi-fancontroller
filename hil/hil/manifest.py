"""Manifest verification: the only route from a build to hardware (CI-01).

load_verified() raises RigError on any mismatch, before any button press.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from . import RigError

COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
BUILD_ID_RE = re.compile(r"^3\.2\+hil\.[0-9a-f]{12}(\.local)?$")
BARE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class ManifestImage:
    path: Path
    sha256: str
    chip: str
    offset: str


@dataclass(frozen=True)
class Manifest:
    commit: str
    build_id: str
    images: dict

    def image(self, role):
        try:
            return self.images[role]
        except KeyError:
            raise RigError("manifest has no image with role '%s'" % role) from None


def load_verified(fw_dir, expected_commit, dut):
    fw_dir = Path(fw_dir)
    if not expected_commit or not COMMIT_RE.match(expected_commit):
        raise RigError("expected commit (HIL_EXPECTED_COMMIT or GITHUB_SHA) is not 40 lowercase hex")
    try:
        data = json.loads((fw_dir / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise RigError("manifest.json is missing or not valid JSON") from None
    if not isinstance(data, dict) or data.get("schema") != 1:
        raise RigError("manifest: schema must be 1")
    commit = data.get("commit")
    if not isinstance(commit, str) or not COMMIT_RE.match(commit):
        raise RigError("manifest: commit is not 40 lowercase hex")
    if commit != expected_commit:
        raise RigError("manifest: commit %s does not match expected %s" % (commit[:12], expected_commit[:12]))
    build_id = data.get("build_id")
    if not isinstance(build_id, str) or not BUILD_ID_RE.match(build_id):
        raise RigError("manifest: build_id has an unexpected format")
    entries = data.get("images")
    commit_entries = [e for e in entries if isinstance(e, dict) and e.get("role") == "commit"] if isinstance(entries, list) else []
    if len(commit_entries) != 1:
        raise RigError("manifest: expected exactly one image with role 'commit'")
    entry = commit_entries[0]
    name = entry.get("file")
    if not isinstance(name, str) or not BARE_NAME_RE.match(name) or ".." in name:
        raise RigError("manifest: image file must be a bare file name")
    path = fw_dir / name
    if not path.is_file():
        raise RigError("manifest: image file %s is not in the firmware directory" % name)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != entry.get("sha256"):
        raise RigError("manifest: sha256 of %s does not match the file" % name)
    if entry.get("chip") != dut.chip:
        raise RigError("manifest: chip %s does not match DUT %s chip %s" % (entry.get("chip"), dut.id, dut.chip))
    try:
        offset_ok = int(entry.get("offset"), 16) == int(dut.flash_offset, 16)
    except (TypeError, ValueError):
        offset_ok = False
    if not offset_ok:
        raise RigError("manifest: flash offset does not match DUT %s flash_offset" % dut.id)
    image = ManifestImage(path=path, sha256=digest, chip=entry["chip"], offset=entry["offset"])
    return Manifest(commit=commit, build_id=build_id, images={"commit": image})
