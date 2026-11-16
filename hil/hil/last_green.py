"""Last-green store (D-15): the image a green main run proved on hardware.

Layout of rig.toml's `last_green_dir`:  <sha256>.bin  and  manifest.json  (schema 1), both 0600.
A failed or cancelled run returns DUT A to this image, but only when it checks out completely;
every doubt means "not a valid store" and the caller uses the v1.6.0 baseline instead (fail closed).

promote() writes the image first and replaces manifest.json last with os.replace, the single
commit point, so an interrupted promotion leaves the previous store (or an invalid one), never a
mismatched pair that load() would accept. This module builds no flash command and never removes
the store directory itself. Stdlib only.
"""

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import RigError

# D-15 counts a "green main image": greens on claude/main or any other ref never update the store.
STORE_REF = "refs/heads/main"
SCHEMA = 1
MANIFEST = "manifest.json"
BUILD_ID_RE = re.compile(r"^3\.2\+hil\.[0-9a-f]{12}$")  # no .local suffix
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class StoredImage:
    path: Path
    sha256: str
    commit: str
    build_id: str
    chip: str
    offset: str
    ref: str
    run_id: str


def network_sha256(path):
    """sha256 of the bytes of hil/hil-network.yaml: an image stored before an SSID, PSK or key change is rejected."""
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        raise RigError("hil-network.yaml cannot be read") from None


def _sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _invalid(check):
    return None, "store invalid: %s" % check


def load(dut, net_sha):
    """(StoredImage, "") for a store that checks out, else (None, reason). Never raises for store content."""
    store = Path(dut.last_green_dir)
    if not store.is_dir():
        return None, "store missing"
    manifest_path = store / MANIFEST
    if not manifest_path.exists():
        return None, "store empty"
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _invalid("manifest is not valid JSON")
    if not isinstance(data, dict):
        return _invalid("manifest is not an object")
    if data.get("schema") != SCHEMA:
        return _invalid("schema is not %d" % SCHEMA)
    if data.get("ref") != STORE_REF:
        return _invalid("ref is not %s" % STORE_REF)
    if data.get("chip") != dut.chip:
        return _invalid("chip does not match rig.toml")
    try:
        offset_ok = int(data.get("offset"), 16) == int(dut.flash_offset, 16)
    except (TypeError, ValueError):
        offset_ok = False
    if not offset_ok:
        return _invalid("offset does not match rig.toml")
    build_id = data.get("build_id")
    if not isinstance(build_id, str) or not BUILD_ID_RE.match(build_id):
        return _invalid("build ID has an unexpected form")
    if not isinstance(net_sha, str) or data.get("network_sha256") != net_sha:
        return _invalid("network hash differs from hil-network.yaml")
    digest = data.get("sha256")
    if not isinstance(digest, str) or not SHA256_RE.match(digest):
        return _invalid("sha256 is not 64 hex digits")
    name = "%s.bin" % digest
    if data.get("file", name) != name:
        return _invalid("file name is not <sha256>.bin")
    image = store / name
    try:
        mode = image.lstat().st_mode
    except OSError:
        return _invalid("image file is missing")
    if not stat.S_ISREG(mode):
        return _invalid("image file is not a regular file")
    try:
        actual = _sha256_of(image)
    except OSError:
        return _invalid("image file cannot be read")
    if actual != digest:
        return _invalid("sha256 mismatch")
    stored = StoredImage(
        path=image,
        sha256=digest,
        commit=str(data.get("commit", "")),
        build_id=build_id,
        chip=data["chip"],
        offset=str(data["offset"]),
        ref=data["ref"],
        run_id=str(data.get("run_id", "")),
    )
    return stored, ""


def _fsync_dir(path):
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _write_private(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def promote(dut, manifest, ref, run_id, net_sha):
    """Store the verified commit image as the last green one. (True, build ID) or (False, reason)."""
    if ref != STORE_REF:
        return False, "ref is not %s" % STORE_REF
    if not BUILD_ID_RE.match(manifest.build_id):
        return False, "build ID is a local build or has an unexpected form"
    image = manifest.image("commit")
    store = Path(dut.last_green_dir)
    try:
        current, _reason = load(dut, net_sha)
        if current is not None and current.sha256 == image.sha256:
            return False, "already %s" % current.build_id
        store.mkdir(mode=0o700, exist_ok=True)
        final = store / ("%s.bin" % image.sha256)
        tmp = store / ("%s.bin.tmp" % image.sha256)
        _write_private(tmp, Path(image.path).read_bytes())
        os.replace(tmp, final)
        if _sha256_of(final) != image.sha256:
            final.unlink()
            return False, "copy mismatch"
        record = {
            "schema": SCHEMA,
            "commit": manifest.commit,
            "build_id": manifest.build_id,
            "sha256": image.sha256,
            "file": final.name,
            "chip": image.chip,
            "offset": image.offset,
            "ref": ref,
            "run_id": run_id,
            "network_sha256": net_sha,
            "promoted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        manifest_tmp = store / (MANIFEST + ".tmp")
        _write_private(manifest_tmp, (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8"))
        _fsync_dir(store)
        os.replace(manifest_tmp, store / MANIFEST)  # the single commit point
        _fsync_dir(store)
    except OSError as exc:
        return False, type(exc).__name__
    _sweep(store, final.name)
    return True, manifest.build_id


def _sweep(store, keep):
    """Delete every other image and any leftover temp file. Best effort: the promotion is already committed."""
    try:
        for entry in store.iterdir():
            if entry.name != keep and entry.name != MANIFEST and entry.suffix in (".bin", ".tmp"):
                if entry.is_file() or entry.is_symlink():
                    entry.unlink()
    except OSError:
        pass
