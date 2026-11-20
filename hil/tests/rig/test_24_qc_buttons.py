"""QC-04: USR1-3 held by the supervisor appear pressed on the DUT's API (D-30, RIG-02).

For each button the rig.toml lists as wired (capability usrN), the supervisor holds that one
line; the DUT must then report that button ON and the other two OFF, and OFF again after
the release. One line at a time, every wait a signal wait with a deadline, and the line is
released in a finally block even when the test is stopped by its timeout. A button the
rig.toml does not list is skipped with a reason (HARN-02). The test does not flip a
reading that comes out reversed: that is a finding.
"""

import pytest

from hil import contract, entities, qc

pytestmark = pytest.mark.image("qc-auto")


@pytest.mark.parametrize(
    "n",
    [
        pytest.param(1, marks=pytest.mark.requires("usr1")),
        pytest.param(2, marks=pytest.mark.requires("usr2")),
        pytest.param(3, marks=pytest.mark.requires("usr3")),
    ],
)
def test_usr_button_reaches_dut(n, supervisor, dut_link):
    switch = contract.SWITCH["A"]["usr%d" % n]
    result = qc.measure_usr(supervisor, switch, dut_link, n)
    assert result["before"] is False, "%s was not seen OFF before the press; nothing was pressed" % entities.BUTTON_USR[n]
    problems = qc.evaluate_buttons(n, result["states"])
    assert not problems, "USR%d press not seen as expected:\n" % n + "\n".join(problems)
    assert result["released"] is False, "%s did not go OFF within %ss after the release" % (
        entities.BUTTON_USR[n],
        qc.USR_WAIT_S,
    )
    print("USR%d: pressed and released on the DUT API" % n)
