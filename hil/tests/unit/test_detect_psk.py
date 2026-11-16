"""detect_psk: the nvs command must work on the release image (plaintext API) as well as on a HIL image (no hardware)."""

import pytest

from hil import RigError
from hil.__main__ import detect_psk


class FakeDut:
    def __init__(self, accepts):
        self.accepts = accepts
        self.tried = []

    def probe(self, noise_psk):
        self.tried.append(noise_psk)
        if noise_psk not in self.accepts:
            raise OSError("wrong mode")
        return object()


def test_key_is_used_when_the_dut_has_encryption():
    dut = FakeDut(accepts=["k"])
    assert detect_psk(dut, "k") == "k"
    assert dut.tried == ["k"]


def test_plaintext_is_used_on_the_release_image():
    dut = FakeDut(accepts=[None])
    assert detect_psk(dut, "k") is None
    assert dut.tried == ["k", None]


def test_no_answer_is_a_rig_error():
    with pytest.raises(RigError):
        detect_psk(FakeDut(accepts=[]), "k")
