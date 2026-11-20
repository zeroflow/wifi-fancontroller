"""Capability vocabulary and test selection (HARN-02, D-33).

The vocabulary below is public and equals the hil-rig Runner contract. What a given DUT
can actually be tested for (its capability list, its framework) lives only in the runner's
rig.toml and is never written down in this repository. A test names what it needs with
`@pytest.mark.requires(...)`; rig.toml decides whether it runs. A missing capability is a
visible skip with a reason, never a pass.

Names compare exactly: "usr10", "USR1" and " usr1" are errors, not near matches.
"""

VOCABULARY = ("fan_tach_bridge", "hdc1080", "usr1", "usr2", "usr3")
FRAMEWORKS = ("arduino", "esp-idf")


def unknown(names):
    """The names that are not in VOCABULARY, in input order (exact string comparison)."""
    return [name for name in names if not isinstance(name, str) or name not in VOCABULARY]


def missing(dut_cfg, required):
    """The required names `dut_cfg` lacks, in the order the marker lists them, each once."""
    have = dut_cfg.capabilities
    out = []
    for name in required:
        if name not in have and name not in out:
            out.append(name)
    return out


def skip_reason(dut_id, missing_names):
    return "DUT %s (rig.toml) lacks capability: %s" % (dut_id, ", ".join(missing_names))


def select_dut(rig, required):
    """Sorted ids of the DUTs whose capabilities include every required name.

    Phase 2 fixtures use DUT A only; Phase 4 picks from this list.
    """
    return sorted(dut_id for dut_id, cfg in rig.duts.items() if not missing(cfg, required))
