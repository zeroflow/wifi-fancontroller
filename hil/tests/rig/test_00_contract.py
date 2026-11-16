"""Contract conformance, re-proved on every run (HARN-01, RIG-03). Collected first by name."""

from hil import contract


def test_supervisor_exposes_contract(supervisor):
    problems = supervisor.contract_problems(supervisor.entity_name_list())
    assert not problems, "\n".join(problems)


def test_switches_released(supervisor):
    names = [name for lines in contract.SWITCH.values() for name in lines.values()]
    still_on = [name for name in names if supervisor.switch_is_on(name) is not False]
    assert not still_on, "switches not reported OFF after release_all: " + ", ".join(sorted(still_on))
