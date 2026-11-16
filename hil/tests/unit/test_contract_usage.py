"""The supervisor contract is enforced from one place, and tests only use its constants."""

import ast
from pathlib import Path

from hil import contract
from hil.supervisor import Supervisor

TESTS = Path(__file__).resolve().parents[1]
# Built from the contract so that this file does not flag itself.
PREFIXES = tuple(contract.SERIAL_CONNECTED[d].removesuffix("Serial Connected") for d in "AB") + (
    contract.SUPERVISOR_RESTART,
)
USR3 = contract.SWITCH["A"]["usr3"]


def all_contract_names():
    names = [n for d in contract.BUTTON.values() for n in d.values()]
    names += [n for d in contract.SWITCH.values() for n in d.values()]
    names += list(contract.SERIAL_CONNECTED.values())
    names.append(contract.SUPERVISOR_RESTART)
    return names


def missing(name):
    return "entity '%s' missing on supervisor" % name


def test_required_entities_are_seventeen_without_duplicates():
    names = all_contract_names()
    assert len(names) == 17 and len(set(names)) == 17
    assert len(contract.REQUIRED_ENTITIES) == 17
    assert contract.REQUIRED_ENTITIES == set(names)


def test_no_test_file_contains_a_supervisor_entity_name_literal():
    offenders = []
    for path in sorted(TESTS.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                value = node.value
                if value in contract.REQUIRED_ENTITIES or value.startswith(PREFIXES):
                    offenders.append("%s:%d" % (path.relative_to(TESTS), node.lineno))
    assert not offenders, "supervisor names must come from hil.contract: " + ", ".join(offenders)


def test_prefix_lookalike_does_not_satisfy_the_contract():
    names = (set(contract.REQUIRED_ENTITIES) - {USR3}) | {USR3 + "0"}
    assert Supervisor.contract_problems(sorted(names)) == [missing(USR3)]


def test_empty_entity_list_reports_every_contract_name_sorted():
    problems = Supervisor.contract_problems([])
    assert problems == [missing(n) for n in sorted(contract.REQUIRED_ENTITIES)]
    assert len(problems) == 17


def test_missing_names_are_listed_in_sorted_order_whatever_the_input_order():
    names = sorted(contract.REQUIRED_ENTITIES)
    first = Supervisor.contract_problems(names[3:])
    second = Supervisor.contract_problems(list(reversed(names[3:])))
    assert first == second == [missing(n) for n in names[:3]]


def test_case_and_whitespace_differences_do_not_satisfy_the_contract():
    others = [n for n in contract.REQUIRED_ENTITIES if n != USR3]
    assert Supervisor.contract_problems(others + [USR3.lower()]) == [missing(USR3)]
    assert Supervisor.contract_problems(others + [USR3 + " "]) == [missing(USR3)]
    assert Supervisor.contract_problems(others + [" " + USR3]) == [missing(USR3)]
    assert Supervisor.contract_problems(others + [USR3]) == []


def test_a_contract_name_reported_twice_is_a_contract_error_naming_it():
    names = sorted(contract.REQUIRED_ENTITIES) + [USR3]
    assert Supervisor.contract_problems(names) == ["entity '%s' reported 2 times" % USR3]


def test_extra_non_contract_entities_are_allowed():
    names = sorted(contract.REQUIRED_ENTITIES) + ["Uptime", "WiFi Signal"]
    assert Supervisor.contract_problems(names) == []
