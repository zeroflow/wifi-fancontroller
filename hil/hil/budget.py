"""Reset budget per DUT, and the two rig errors that keep the rig's own doing out of the FAIL verdict (HARN-12).

ESPHome counts boots that do not stay up: after `num_attempts` (10 by default) boots without a
clean 60 s (boot_is_good_after) or an orderly shutdown the next boot is safe mode, which has no
API. Every EN reset, flash reset and reboot the harness causes adds a boot, so the harness keeps
its own count below the firmware's limit and refuses to press Reset once it is reached, instead
of driving the DUT into safe mode and calling that a firmware fault. The numbers are policy (below
the firmware's 10), not ESPHome facts, and shown in reports/budget-dut-a.json so they can be tuned.

Both exceptions are RigError subclasses: the Collector maps every RigError to RIG ERROR, never FAIL.
"""

import time
from collections import Counter

from . import RigError

RESET_BUDGET_LIMIT = 8  # boots in a row, each less than RESET_DECAY_S after the previous one
RESET_DECAY_S = 70  # a boot that stayed up this long clears the streak (firmware: 60 s boot_is_good_after)

CAUSES = ("flash_reset", "en_reset", "ota_reboot", "safe_mode_reboot", "observed_reboot")


class ResetBudgetExhausted(RigError):
    """One more reset would push the DUT towards ESPHome safe mode: the press is refused, nothing was pressed."""


class SafeModeError(RigError):
    """The DUT booted into ESPHome safe mode (no API): a rig/boot-count condition, never a firmware FAIL."""


class ResetBudget:
    def __init__(self, limit=RESET_BUDGET_LIMIT, decay_s=RESET_DECAY_S, clock=time.monotonic, label="DUT A"):
        self.limit = limit
        self.decay_s = decay_s
        self._clock = clock
        self._label = label
        self._t0 = clock()
        self._boots = []  # (seconds since the budget was created, cause), every boot recorded
        self._streak = []  # (clock time, cause) of the boots in the current streak

    def record(self, cause, orderly=False):
        """A boot the harness caused or saw.

        An orderly boot (OTA reboot, the safe-mode button) clears the firmware's counter, so the
        streak starts again with this boot. A boot more than decay_s after the previous one means
        the previous one stayed up: the streak starts again with this boot as well.
        """
        if cause not in CAUSES:
            raise ValueError("unknown boot cause: %s" % cause)
        now = self._clock()
        if orderly or not self._streak or now - self._streak[-1][0] >= self.decay_s:
            self._streak = []
        self._streak.append((now, cause))
        self._boots.append((now - self._t0, cause))

    def streak(self):
        """Boots in a row, each less than decay_s after the previous one; 0 once the last boot stayed up."""
        if not self._streak or self._clock() - self._streak[-1][0] >= self.decay_s:
            return 0
        return len(self._streak)

    def _causes(self):
        counts = Counter(cause for _t, cause in self._streak)
        return ", ".join("%s x%d" % (cause, counts[cause]) for cause in dict.fromkeys(c for _t, c in self._streak))

    def before_reset(self):
        """Raise ResetBudgetExhausted when one more boot would exceed the limit; call it before pressing."""
        used = self.streak()
        if used + 1 > self.limit:
            raise ResetBudgetExhausted(
                "%s reset budget exhausted: %d/%d boots less than %d s apart (%s)"
                % (self._label, used, self.limit, self.decay_s, self._causes())
            )

    def report(self):
        return {
            "limit": self.limit,
            "decay_s": self.decay_s,
            "used": len(self._boots),
            "streak": self.streak(),
            "boots": [{"cause": cause, "t": round(t, 1)} for t, cause in self._boots],
        }
