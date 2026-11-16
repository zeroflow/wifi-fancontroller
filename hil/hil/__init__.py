"""Hardware-in-the-loop harness for the WiFi Fan Controller firmware.

Run with ``python -m hil run`` from the ``hil/`` directory. The harness flashes
the image named by a verified manifest to DUT A through the rig supervisor and
checks that the board reports the matching build ID over its encrypted API.
"""


class RigError(Exception):
    """A rig or tooling fault, never a firmware verdict.

    Messages name configuration keys and entity names, never secret values.
    """
