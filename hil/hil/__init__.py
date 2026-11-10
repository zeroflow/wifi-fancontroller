"""Hardware-in-the-loop harness for the WiFi Fan Controller firmware.

Run with ``python -m hil run`` from the ``hil/`` directory. The harness flashes
the image named by a verified manifest to DUT A through the rig supervisor and
checks that the board reports the matching build ID over its encrypted API.
"""


class RigError(Exception):
    """A rig or tooling fault, never a firmware verdict.

    Messages name configuration keys and entity names, never secret values.
    """


class FirmwareFailure(AssertionError):
    """A device-side outcome of the firmware under test: a failed OTA, the wrong image after an OTA.

    An AssertionError, so pytest reports it as a failure and the verdict is FAIL (D-26),
    unlike RigError, which stays a rig or tooling fault (RIG ERROR). Messages name
    roles and build IDs, never keys.
    """
