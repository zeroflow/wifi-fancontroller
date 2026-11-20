"""known_good.select: one known-good choice for teardown and the preflight heal (D-15, D-44, review WR-03)."""

import socket
from pathlib import Path

import pytest
from test_teardown import BUILD_ID, rig, seed_store, stored_image  # noqa: F401 - rig is a fixture

from hil import RigError, config, known_good, teardown


def test_a_verified_store_gives_last_green_with_one_region_the_hil_key_and_its_build_id(rig):  # noqa: F811
    store = seed_store(rig)
    kg = known_good.select(rig.cfg, "hil-key")
    assert kg.source == "last-green"
    assert kg.regions == [("0x0", stored_image(store))]
    assert kg.psk == "hil-key"
    assert kg.expected_build_id == BUILD_ID


def test_the_last_green_region_is_the_whole_factory_image_at_flash_offset_0x0(rig):  # noqa: F811
    """D-44 clarified: bootloader, partition table, blank otadata and app in one write at 0x0."""
    seed_store(rig)
    kg = known_good.select(rig.cfg, "hil-key")
    assert [offset for offset, _path in kg.regions] == [rig.dutcfg.flash_offset] == ["0x0"]


def test_without_a_store_v160_with_the_nvs_region_the_known_good_psk_and_no_build_id(rig):  # noqa: F811
    kg = known_good.select(rig.cfg, "hil-key")
    assert kg.source == "v1.6.0"
    assert kg.regions == [("0x0", Path(rig.kg)), ("0x3A0000", Path(rig.nvs))]
    assert kg.psk is None and kg.expected_build_id is None
    assert kg.detail == "store missing"


def test_a_v160_image_with_api_encryption_uses_the_hil_key(rig):  # noqa: F811
    rig.dutcfg.known_good_api_encryption = True
    assert known_good.select(rig.cfg, "hil-key").psk == "hil-key"


def test_a_store_with_another_network_hash_falls_back_to_v160_and_says_why(rig):  # noqa: F811
    seed_store(rig)
    config.NETWORK_FILE.write_text('hil_dut_api_key: "another-key-0123456"\n', encoding="utf-8")
    kg = known_good.select(rig.cfg, "hil-key")
    assert kg.source == "v1.6.0"
    assert kg.detail == "store invalid: network hash differs from hil-network.yaml"


def test_a_v160_image_that_does_not_verify_raises_naming_the_reason(rig):  # noqa: F811
    rig.dutcfg.known_good_sha256 = "0" * 64
    with pytest.raises(RigError) as raised:
        known_good.select(rig.cfg, "hil-key")
    assert "known_good_image sha256 does not match known_good_sha256" in str(raised.value)
    assert "store missing" in str(raised.value)


def test_a_nvs_backup_of_the_wrong_size_raises_naming_it(rig):  # noqa: F811
    rig.nvs.write_bytes(b"\x01" * 10)
    with pytest.raises(RigError, match="nvs_backup has 10 bytes"):
        known_good.select(rig.cfg, "hil-key")


def test_select_never_opens_a_network_connection(rig, monkeypatch):  # noqa: F811
    """HARN-10: the heal and teardown images are runner-local files; nothing is downloaded."""

    def refuse(*_a, **_k):
        raise AssertionError("known_good.select opened a network connection")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    seed_store(rig)
    assert known_good.select(rig.cfg, "hil-key").source == "last-green"


def test_teardown_keeps_the_moved_helpers_importable():
    assert teardown.verify_known_good is known_good.verify_known_good
    assert teardown.known_good_regions is known_good.known_good_regions
    assert teardown.known_good_psk is known_good.known_good_psk
    assert teardown.sha256_file is known_good.sha256_file
