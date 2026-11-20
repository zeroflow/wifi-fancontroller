"""REG-03, D-38: right after the upgrade, the commit image exposes exactly the committed golden entity list.

Runs between test_11 (the upgrade) and test_12_serial_restore (file order: "golden" sorts before "serial"),
so it reads the entities of the image the release was upgraded to. The full list comes from a fresh API
session (every entity type, not the DutLink's subset) and is compared as a multiset with
hil/golden/entities-<rev>.json: any removed or added entity is a FAIL naming both by `type: name`.
reports/golden-dut-a.json always holds the device's list, so an intended change can be accepted with
`python -m hil golden from-run`; this test never writes the golden file.
"""

import pytest

from hil import config, golden

pytestmark = pytest.mark.image("commit")


def test_entities_match_the_golden_list(rig_config):
    cfg = rig_config.duts["A"]
    actual = golden.capture(cfg.host, rig_config.dut_api_key)
    path = golden.golden_file(cfg.rev)
    try:
        want = golden.load(path)
    except AssertionError as exc:
        golden.write_report(config.reports_dir(), cfg.rev, path, actual, [], [], error=str(exc))
        raise
    removed, added = golden.compare(want, actual)
    golden.write_report(config.reports_dir(), cfg.rev, path, actual, removed, added)
    assert actual, "no entities listed by DUT A (the golden list has %d)" % len(want)
    assert not removed and not added, golden.problems_text(removed, added, cfg.rev)
    print("entity list matches golden (%d entities)" % len(actual))
