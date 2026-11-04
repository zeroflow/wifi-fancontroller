"""DUT entity names: the only module that holds them.

Change these together with the product's hardware packages (hardware-rev-3.1.yaml,
hil/qc-overrides.yaml) in the same step. Every other module, and every test, takes
names from here (tests/unit/test_contract_usage.py enforces it), so a renamed entity
is one edit, e.g. FAN_SPEED[1] is "Fan 1 Speed" in the shipped hardware package.
The supervisor's names are a different contract and live in hil/contract.py.
"""

CHANNELS = (1, 2, 3, 4)

FAN = {n: "Fan %d" % n for n in CHANNELS}
FAN_SPEED = {n: "Fan %d Speed" % n for n in CHANNELS}
TEMPERATURE = "Temperature"
HUMIDITY = "Humidity"
BUTTON_USR = {n: "Button USR%d" % n for n in (1, 2, 3)}

# Added by hil/qc-overrides.yaml, present on the qc-auto and canary images only.
QC_DEVICE_INFO = "QC Device Info"
QC_RESET_REASON = "QC Reset Reason"
QC_SAFE_MODE = "QC Safe Mode Boot"

QC_ENTITIES = frozenset(
    set(FAN.values())
    | set(FAN_SPEED.values())
    | {TEMPERATURE, HUMIDITY}
    | set(BUTTON_USR.values())
    | {QC_DEVICE_INFO, QC_RESET_REASON, QC_SAFE_MODE}
)
