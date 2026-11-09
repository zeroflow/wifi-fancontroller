"""The golden entity list (REG-03, D-38): after the upgrade the commit image must expose exactly these entities.

The list is captured from the device, never derived from the YAML (build_image.entity_names misses light,
update and partition entities): every entity `list_entities_services()` returns, as `type: name`, where type
is the aioesphomeapi info class in snake case without the Info suffix (BinarySensorInfo -> binary_sensor).
Object ids and keys are not compared (object_id is documented as planned for removal).

The comparison is a multiset and ignores order: a duplicate on the device is an added entry, a duplicated
golden entry the device has once is a removed one. A run never writes the golden file. A changed entity list
fails until a human regenerates the file (`python -m hil golden from-run` or `golden capture`) and commits it
in the same commit as the firmware change.
"""

import asyncio
import json
import re
from collections import Counter
from pathlib import Path

from aioesphomeapi import APIClient, APIConnectionError

from . import RigError, contract
from .dut import API_CONNECT_S

SCHEMA = 1
GOLDEN_DIR = Path(__file__).resolve().parent.parent / "golden"
REPORT = "golden-dut-a.json"
CAPTURE_EXTRA_S = 10  # list_entities_services after the connect


def golden_file(rev):
    """hil/golden/entities-<rev>.json."""
    return GOLDEN_DIR / ("entities-%s.json" % rev)


def display_path(path):
    """The golden file as a repo-relative path (hil/golden/...) for messages and reports, never a host path."""
    path = Path(path)
    try:
        return str(Path("hil") / path.resolve().relative_to(GOLDEN_DIR.parent))
    except ValueError:
        return path.name


def entity_type(info):
    """BinarySensorInfo -> binary_sensor, TextSensorInfo -> text_sensor, FanInfo -> fan, UpdateInfo -> update."""
    name = type(info).__name__
    base = name[: -len("Info")] if name.endswith("Info") else name
    return re.sub(r"(?<!^)(?=[A-Z])", "_", base).lower()


def entries_of(infos):
    """(type, name) of every entity info, in the device's order."""
    return [(entity_type(info), info.name) for info in infos]


async def _list(host, noise_psk, deadline_s):
    client = APIClient(host, contract.API_PORT, None, noise_psk=noise_psk)
    try:
        async with asyncio.timeout(deadline_s):
            await client.connect(login=True)
            device = await client.device_info()
            infos, _services = await client.list_entities_services()
        return device, infos
    finally:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001 - a failed attempt must not leak the slot, nor mask its cause
            pass


def capture_device(host, noise_psk, deadline_s=API_CONNECT_S + CAPTURE_EXTRA_S):
    """(project_version, [(type, name)]) of the device, over one fresh API session that is closed again.

    An empty list is returned as is, so the comparison fails. No answer is a RigError.
    """
    try:
        device, infos = asyncio.run(_list(host, noise_psk, deadline_s))
    except (APIConnectionError, OSError, TimeoutError) as exc:
        raise RigError("golden: DUT A did not list its entities (%s)" % type(exc).__name__) from None
    return device.project_version, entries_of(infos)


def capture(host, noise_psk, deadline_s=API_CONNECT_S + CAPTURE_EXTRA_S):
    """Every entity of the device as [(type, name)] (the device's order)."""
    return capture_device(host, noise_psk, deadline_s)[1]


def load(path):
    """[(type, name)] of a golden file. Missing, unreadable, empty or another schema: AssertionError naming the file.

    An AssertionError, not a RigError: the golden file is test data in the product repo, so a broken one fails the test.
    """
    shown = display_path(path)
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise AssertionError("golden entity list %s is missing" % shown) from None
    except (OSError, ValueError) as exc:
        raise AssertionError("golden entity list %s is unreadable (%s)" % (shown, type(exc).__name__)) from None
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise AssertionError("golden entity list %s is not schema %d" % (shown, SCHEMA))
    entities = data.get("entities")
    if not isinstance(entities, list) or not entities:
        raise AssertionError("golden entity list %s has no entities" % shown)
    entries = []
    for entry in entities:
        if not isinstance(entry, dict) or not isinstance(entry.get("type"), str) or not isinstance(entry.get("name"), str):
            raise AssertionError("golden entity list %s has an entry without a type and a name: %r" % (shown, entry))
        entries.append((entry["type"], entry["name"]))
    return entries


def render(entries, rev):
    """The golden file's text: schema, rev and the entries sorted by (type, name), with a trailing newline."""
    data = {
        "schema": SCHEMA,
        "rev": str(rev),
        "entities": [{"type": t, "name": n} for t, n in sorted((str(t), str(n)) for t, n in entries)],
    }
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def dump(entries, path, rev):
    """Write the golden file (sorted, so two captures of the same device are byte-identical)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(entries, rev), encoding="utf-8")


def compare(golden, actual):
    """(removed, added) as sorted [(type, name)]: in the golden list and not on the device, and the reverse.

    A multiset comparison: each entry counts as often as it occurs.
    """
    want, have = Counter(map(tuple, golden)), Counter(map(tuple, actual))
    return sorted((want - have).elements()), sorted((have - want).elements())


def label(entry):
    return "%s: %s" % entry


def problems_text(removed, added, rev=None):
    """removed: sensor: X; added: light: Y, then how to accept an intended change (D-38)."""
    parts = []
    if removed:
        parts.append("removed: %s" % ", ".join(label(e) for e in removed))
    if added:
        parts.append("added: %s" % ", ".join(label(e) for e in added))
    out = "hil/golden/entities-%s.json" % (rev if rev else "<rev>")
    return (
        "entity list differs from the golden list: %s. If the change is intended, regenerate with "
        "`python -m hil golden from-run --report reports/%s --out %s` (or `python -m hil golden capture --dut A "
        "--out %s` from the device) and commit it with the firmware change (D-38)" % ("; ".join(parts), REPORT, out, out)
    )


def write_report(reports_dir, rev, golden_path, actual, removed, added, error=None):
    """reports/golden-dut-a.json: the golden file, the device's list, the diff, and a golden-file error if any."""
    reports_dir = Path(reports_dir)
    data = {
        "schema": SCHEMA,
        "rev": str(rev),
        "golden_file": display_path(golden_path),
        "actual": [{"type": t, "name": n} for t, n in sorted(actual)],
        "removed": [{"type": t, "name": n} for t, n in removed],
        "added": [{"type": t, "name": n} for t, n in added],
        "error": error,
    }
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / REPORT).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return data
