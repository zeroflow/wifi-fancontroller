"""Supervisor contract: the only module that holds supervisor names and ports.

Change these together with the hil-rig README section "Supervisor contract" in
the same step (HARN-01). Every other module takes names from here.
"""

API_PORT = 6053
BRIDGE_PORT = {"A": 6638, "B": 6639}
BUTTON = {
    "A": {"reset": "DUT A Reset", "bootloader": "DUT A Bootloader"},
    "B": {"reset": "DUT B Reset", "bootloader": "DUT B Bootloader"},
}
SWITCH = {
    d: {
        "en": f"DUT {d} EN",
        "boot": f"DUT {d} BOOT",
        "usr1": f"DUT {d} USR1",
        "usr2": f"DUT {d} USR2",
        "usr3": f"DUT {d} USR3",
    }
    for d in "AB"
}
SERIAL_CONNECTED = {"A": "DUT A Serial Connected", "B": "DUT B Serial Connected"}
SUPERVISOR_RESTART = "Supervisor Restart"
BRIDGE_BAUD = 115200
BRIDGE_MAX_CLIENTS = 2

REQUIRED_ENTITIES = frozenset(
    {n for d in BUTTON.values() for n in d.values()}
    | {n for d in SWITCH.values() for n in d.values()}
    | set(SERIAL_CONNECTED.values())
    | {SUPERVISOR_RESTART}
)
