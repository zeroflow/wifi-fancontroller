"""The one known-good choice for teardown and the preflight heal (D-15, D-44, review WR-03).

The last green main image when the last-green store checks out completely, else the v1.6.0
factory image plus NVS replay. Everything here reads runner-local files only (the root-owned
v1.6.0 image and NVS backup, the runner-owned store); nothing is downloaded (HARN-10). Every
check runs before the caller presses anything.

The last-green store keeps the commit's full factory image (bootloader, partition table, blank
otadata, app) and it is written at flash_offset 0x0, so a DUT whose otadata points at an OTA'd
broken app1 boots app0 again (D-44, clarified 2026-11-04).
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path

from . import RigError, config, last_green


@dataclass(frozen=True)
class KnownGood:
    source: str  # "last-green" or "v1.6.0"
    regions: list  # [(offset, Path)] written in one esptool call; region writes only, never an erase
    psk: object  # API key to confirm with: the HIL key, or None for the release image without encryption
    expected_build_id: object  # the stored build ID for last-green; None for v1.6.0 (any answer confirms)
    detail: str  # for v1.6.0, why the store was not used


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_known_good(dutcfg, with_nvs=True):
    """The v1.6.0 image must match rig.toml's sha256, and the NVS backup must have its size (before any press)."""
    try:
        digest = sha256_file(dutcfg.known_good_image)
    except OSError:
        raise RigError("known_good_image cannot be read") from None
    if digest != dutcfg.known_good_sha256:
        raise RigError("known_good_image sha256 does not match known_good_sha256")
    if with_nvs:
        try:
            size = Path(dutcfg.nvs_backup).stat().st_size
        except OSError:
            raise RigError("nvs_backup cannot be read") from None
        if size != int(dutcfg.nvs_size, 16):
            raise RigError("nvs_backup has %d bytes, nvs_size says %d" % (size, int(dutcfg.nvs_size, 16)))


def known_good_regions(dutcfg, with_nvs=True):
    regions = [(dutcfg.flash_offset, Path(dutcfg.known_good_image))]
    if with_nvs:
        regions.append((dutcfg.nvs_offset, Path(dutcfg.nvs_backup)))
    return regions


def known_good_psk(dutcfg, dut_key):
    """The release image has no API encryption; a known-good image that has it uses the HIL key."""
    return dut_key if dutcfg.known_good_api_encryption else None


def select(rig, dut_key, network_file=None):
    """The known-good image for DUT A. RigError (naming the reason) when neither source verifies.

    `network_file` defaults to config.NETWORK_FILE at call time: a stored image built before an SSID,
    PSK or key change is rejected by its network hash.
    """
    dutcfg = rig.duts["A"]
    network_file = config.NETWORK_FILE if network_file is None else network_file
    try:
        stored, reason = last_green.load(dutcfg, last_green.network_sha256(network_file))
    except RigError:
        stored, reason = None, "store invalid: hil-network.yaml cannot be read"
    if stored is not None:
        # A commit image carries the HIL WiFi and key in firmware: no NVS region.
        return KnownGood(
            source="last-green",
            regions=[(dutcfg.flash_offset, Path(stored.path))],
            psk=dut_key,
            expected_build_id=stored.build_id,
            detail=stored.build_id,
        )
    try:
        verify_known_good(dutcfg)
    except RigError as exc:
        raise RigError("%s (last-green: %s)" % (exc, reason)) from None
    return KnownGood(
        source="v1.6.0",
        regions=known_good_regions(dutcfg),
        psk=known_good_psk(dutcfg, dut_key),
        expected_build_id=None,
        detail=reason,
    )
