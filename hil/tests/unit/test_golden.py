"""The golden entity list (REG-03, D-38): type mapping, multiset compare, file I/O, the capture and rig test 12."""

import importlib.util
import json
import random
from pathlib import Path
from types import SimpleNamespace

import pytest
from aioesphomeapi import (
    APIConnectionError,
    BinarySensorInfo,
    ButtonInfo,
    FanInfo,
    LightInfo,
    SensorInfo,
    TextSensorInfo,
    UpdateInfo,
)

from hil import RigError, golden
from hil import __main__ as entry

RIG = Path(__file__).resolve().parents[1] / "rig"
HINT = "python -m hil golden from-run --report reports/golden-dut-a.json --out hil/golden/entities-3.2.json"
ENTRIES = [
    ("sensor", "Speed X"),
    ("fan", "Fan X"),
    ("binary_sensor", "USR1"),
    ("light", "Status LED"),
    ("button", "Restart"),
    ("update", "Firmware"),
    ("text_sensor", "Framework"),
]


# ---- entity_type ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "info, expected",
    [
        (BinarySensorInfo, "binary_sensor"),
        (TextSensorInfo, "text_sensor"),
        (FanInfo, "fan"),
        (UpdateInfo, "update"),
        (SensorInfo, "sensor"),
        (LightInfo, "light"),
        (ButtonInfo, "button"),
    ],
)
def test_entity_type_is_the_info_class_in_snake_case_without_the_suffix(info, expected):
    assert golden.entity_type(info(name="x")) == expected


def test_entries_keep_type_and_name_only():
    infos = [SensorInfo(name="Temp X", object_id="temperature", key=7), FanInfo(name="Fan X", key=9)]
    assert golden.entries_of(infos) == [("sensor", "Temp X"), ("fan", "Fan X")]


# ---- compare -------------------------------------------------------------------------------------


def test_identical_multisets_in_any_order_have_no_difference():
    shuffled = list(ENTRIES)
    random.Random(4).shuffle(shuffled)
    assert golden.compare(ENTRIES, shuffled) == ([], [])


def test_removed_and_added_are_sorted_lists_of_type_and_name():
    actual = [e for e in ENTRIES if e != ("light", "Status LED")] + [("sensor", "Invented"), ("fan", "Fan Y")]
    removed, added = golden.compare(ENTRIES, actual)
    assert removed == [("light", "Status LED")]
    assert added == [("fan", "Fan Y"), ("sensor", "Invented")]


def test_a_duplicate_on_the_device_is_an_added_entry():
    assert golden.compare(ENTRIES, ENTRIES + [("fan", "Fan X")]) == ([], [("fan", "Fan X")])


def test_a_duplicated_golden_entry_the_device_has_once_is_a_removed_entry():
    assert golden.compare(ENTRIES + [("fan", "Fan X")], ENTRIES) == ([("fan", "Fan X")], [])


def test_the_same_name_under_another_type_is_a_difference():
    removed, added = golden.compare([("sensor", "Fan X")], [("fan", "Fan X")])
    assert removed == [("sensor", "Fan X")] and added == [("fan", "Fan X")]


def test_an_empty_device_list_against_a_golden_list_removes_everything():
    removed, added = golden.compare(ENTRIES, [])
    assert removed == sorted(ENTRIES) and added == []


# ---- dump / load ---------------------------------------------------------------------------------


def test_dump_writes_schema_rev_and_sorted_entries_with_a_trailing_newline(tmp_path):
    path = tmp_path / "entities-3.2.json"
    golden.dump(ENTRIES, path, "3.2")
    text = path.read_text(encoding="utf-8")
    assert text.endswith("}\n") and not text.endswith("\n\n")
    data = json.loads(text)
    assert data["schema"] == 1 and data["rev"] == "3.2"
    assert data["entities"] == [{"type": t, "name": n} for t, n in sorted(ENTRIES)]
    assert list(data) == ["schema", "rev", "entities"]
    assert list(data["entities"][0]) == ["type", "name"]


def test_dump_of_a_shuffled_list_is_byte_identical_to_dump_of_the_sorted_list(tmp_path):
    shuffled = list(ENTRIES)
    random.Random(1).shuffle(shuffled)
    golden.dump(shuffled, tmp_path / "a.json", "3.2")
    golden.dump(sorted(ENTRIES), tmp_path / "b.json", "3.2")
    assert (tmp_path / "a.json").read_bytes() == (tmp_path / "b.json").read_bytes()


def test_load_returns_what_dump_wrote(tmp_path):
    golden.dump(ENTRIES, tmp_path / "g.json", "3.2")
    assert sorted(golden.load(tmp_path / "g.json")) == sorted(ENTRIES)


def test_load_of_a_missing_file_is_a_plain_assertion_naming_the_file(tmp_path):
    with pytest.raises(AssertionError, match="nope.json is missing") as info:
        golden.load(tmp_path / "nope.json")
    assert type(info.value) is AssertionError


@pytest.mark.parametrize(
    "content, words",
    [
        ({"schema": 1, "rev": "3.2", "entities": []}, "has no entities"),
        ({"schema": 1, "rev": "3.2"}, "has no entities"),
        ({"schema": 2, "rev": "3.2", "entities": [{"type": "fan", "name": "Fan X"}]}, "is not schema 1"),
        ([], "is not schema 1"),
        ({"schema": 1, "entities": [{"type": "fan"}]}, "without a type and a name"),
        ("{not json", "is unreadable"),
    ],
)
def test_load_of_an_empty_or_foreign_file_is_a_plain_assertion_naming_the_file(tmp_path, content, words):
    path = tmp_path / "entities-3.2.json"
    path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
    with pytest.raises(AssertionError, match="entities-3.2.json") as info:
        golden.load(path)
    assert words in str(info.value)
    assert type(info.value) is AssertionError


def test_the_golden_file_of_a_revision_lives_in_hil_golden():
    assert golden.golden_file("3.2") == golden.GOLDEN_DIR / "entities-3.2.json"
    assert golden.GOLDEN_DIR == Path(__file__).resolve().parents[2] / "golden"
    assert golden.display_path(golden.golden_file("3.2")) == "hil/golden/entities-3.2.json"


def test_a_path_outside_the_repo_is_shown_by_its_name_only(tmp_path):
    assert golden.display_path(tmp_path / "x" / "entities-3.2.json") == "entities-3.2.json"


# ---- problems_text -------------------------------------------------------------------------------


def test_problems_text_lists_removed_and_added_and_how_to_accept_the_change():
    text = golden.problems_text([("sensor", "X")], [("light", "Y")], "3.2")
    assert "removed: sensor: X; added: light: Y" in text
    assert HINT in text
    assert "python -m hil golden capture --dut A" in text
    assert "commit it with the firmware change (D-38)" in text


def test_problems_text_with_only_one_side_names_only_that_side():
    text = golden.problems_text([("sensor", "X"), ("sensor", "Z")], [], "3.2")
    assert "removed: sensor: X, sensor: Z." in text and "added:" not in text


# ---- capture ---------------------------------------------------------------------------------------


class FakeClient:
    instances = []
    infos = []
    fail = None

    def __init__(self, host, port, password, noise_psk=None):
        self.args = (host, port, password, noise_psk)
        self.disconnected = False
        FakeClient.instances.append(self)

    async def connect(self, login=False):
        if FakeClient.fail is not None:
            raise FakeClient.fail

    async def device_info(self):
        return SimpleNamespace(project_version="3.2+hil.aaaaaaaaaaaa")

    async def list_entities_services(self):
        return list(FakeClient.infos), []

    async def disconnect(self):
        self.disconnected = True


@pytest.fixture
def fake_client(monkeypatch):
    FakeClient.instances, FakeClient.infos, FakeClient.fail = [], [], None
    monkeypatch.setattr(golden, "APIClient", FakeClient)
    return FakeClient


def test_capture_lists_every_entity_type_and_closes_its_session(fake_client):
    fake_client.infos = [LightInfo(name="Status LED"), UpdateInfo(name="Firmware"), FanInfo(name="Fan X")]
    assert golden.capture("192.0.2.10", "key") == [("light", "Status LED"), ("update", "Firmware"), ("fan", "Fan X")]
    (client,) = fake_client.instances
    assert client.args == ("192.0.2.10", 6053, None, "key")
    assert client.disconnected


def test_capture_device_returns_the_version_it_listed_from(fake_client):
    fake_client.infos = [FanInfo(name="Fan X")]
    assert golden.capture_device("192.0.2.10", "key") == ("3.2+hil.aaaaaaaaaaaa", [("fan", "Fan X")])


def test_an_empty_device_list_is_returned_as_is_so_the_comparison_fails(fake_client):
    assert golden.capture("192.0.2.10", "key") == []


@pytest.mark.parametrize("exc", [APIConnectionError("x"), OSError("x"), TimeoutError()])
def test_no_answer_is_a_rig_error_and_the_session_is_still_closed(fake_client, exc):
    fake_client.fail = exc
    with pytest.raises(RigError, match=r"golden: DUT A did not list its entities \(%s\)" % type(exc).__name__):
        golden.capture("192.0.2.10", "key")
    assert fake_client.instances[0].disconnected


def test_the_capture_deadline_is_the_api_connect_plus_ten_seconds():
    from hil import dut

    assert golden.capture.__defaults__ == (dut.API_CONNECT_S + 10,)


# ---- CLI guard (RESEARCH Pitfall 20) ---------------------------------------------------------------


@pytest.mark.parametrize(
    "version, commit, ok",
    [
        ("3.2+hil.0123456789ab", "", True),
        ("3.2+hil.0123456789ab", "0123456789abcdef0123456789abcdef01234567", True),
        ("3.2+hil.0123456789ab", "ffffffffffffffffffffffffffffffffffffffff", False),
        ("3.2+qc.0123456789ab", "", False),
        ("3.2+canary.0123456789ab", "", False),
        ("2026.11.0", "", False),
        ("3.3+hil.0123456789ab", "", False),
    ],
)
def test_only_the_commit_image_of_the_revision_and_commit_may_be_captured(version, commit, ok):
    problem = entry.capture_source_problem(version, "3.2", commit)
    assert (problem is None) is ok
    if not ok:
        assert version in problem


def test_the_golden_cli_has_capture_and_check():
    parser = entry.build_parser()
    args = parser.parse_args(["golden", "capture", "--dut", "A", "--out", "x.json"])
    assert (args.command, args.golden_command, args.out) == ("golden", "capture", "x.json")
    args = parser.parse_args(["golden", "check", "--dut", "A"])
    assert (args.golden_command, args.file) == ("check", None)


# ---- rig test 12 with fakes ------------------------------------------------------------------------


def load_rig_module():
    spec = importlib.util.spec_from_file_location("golden_rig_under_test", RIG / "test_12_golden_entities.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.setenv("HIL_REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(golden, "GOLDEN_DIR", tmp_path / "golden")
    cfg = SimpleNamespace(host="192.0.2.10", rev="3.2")
    return SimpleNamespace(
        config=SimpleNamespace(duts={"A": cfg}, dut_api_key="key"),
        reports=tmp_path / "reports",
        module=load_rig_module(),
    )


def report(rig):
    return json.loads((rig.reports / golden.REPORT).read_text(encoding="utf-8"))


def test_rig_test_12_passes_on_a_match_and_reports_the_list(rig, monkeypatch, capsys):
    golden.dump(ENTRIES, golden.golden_file("3.2"), "3.2")
    monkeypatch.setattr(golden, "capture", lambda host, key: list(reversed(ENTRIES)))
    rig.module.test_entities_match_the_golden_list(rig.config)
    assert "entity list matches golden (7 entities)" in capsys.readouterr().out
    data = report(rig)
    assert data["removed"] == [] and data["added"] == [] and data["error"] is None
    assert data["actual"] == [{"type": t, "name": n} for t, n in sorted(ENTRIES)]


def test_rig_test_12_fails_with_both_sides_named_and_never_writes_the_golden_file(rig, monkeypatch):
    path = golden.golden_file("3.2")
    golden.dump(ENTRIES, path, "3.2")
    before = path.read_bytes()
    actual = [e for e in ENTRIES if e != ("light", "Status LED")] + [("sensor", "HIL Invented Sensor")]
    monkeypatch.setattr(golden, "capture", lambda host, key: actual)
    with pytest.raises(AssertionError) as info:
        rig.module.test_entities_match_the_golden_list(rig.config)
    assert "removed: light: Status LED; added: sensor: HIL Invented Sensor" in str(info.value)
    assert HINT in str(info.value)
    assert path.read_bytes() == before
    data = report(rig)
    assert data["removed"] == [{"type": "light", "name": "Status LED"}]
    assert data["added"] == [{"type": "sensor", "name": "HIL Invented Sensor"}]


def test_rig_test_12_fails_on_an_empty_device_list(rig, monkeypatch):
    golden.dump(ENTRIES, golden.golden_file("3.2"), "3.2")
    monkeypatch.setattr(golden, "capture", lambda host, key: [])
    with pytest.raises(AssertionError, match="no entities listed by DUT A"):
        rig.module.test_entities_match_the_golden_list(rig.config)


def test_rig_test_12_fails_without_a_golden_file_and_still_reports_the_device_list(rig, monkeypatch):
    monkeypatch.setattr(golden, "capture", lambda host, key: ENTRIES)
    with pytest.raises(AssertionError, match="entities-3.2.json is missing"):
        rig.module.test_entities_match_the_golden_list(rig.config)
    data = report(rig)
    assert "is missing" in data["error"] and len(data["actual"]) == len(ENTRIES)


def test_rig_test_12_runs_on_the_commit_image_and_reads_the_revisions_file():
    text = (RIG / "test_12_golden_entities.py").read_text(encoding="utf-8")
    assert 'pytest.mark.image("commit")' in text
    assert "golden.compare" in text and "golden.golden_file(cfg.rev)" in text
    assert "golden.dump" not in text  # a run never writes the golden file (D-38, T-03-27)


def test_the_committed_golden_file_is_schema_1_sorted_and_named_for_its_revision():
    for path in sorted(Path(__file__).resolve().parents[2].joinpath("golden").glob("entities-*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = golden.load(path)
        assert path.name == "entities-%s.json" % data["rev"]
        assert path.read_text(encoding="utf-8") == golden.render(entries, data["rev"])
