"""The login failure budget (§5.6, brute force; §5.8 T8; M6-3, #188).

One instance, one owner, one budget: every failed `POST /auth/login` or
`POST /auth/setup` — whatever address it came from — doubles a delay during
which further attempts are refused with 429 and `Retry-After`, up to a ceiling.
A **delay, not a lockout**: the ceiling means an attacker can slow the owner
down for at most `MAX_DELAY` at a time and never lock them out, while the
doubling makes an online guess cost minutes per attempt within a dozen tries.
A successful login resets it.

In-process state, correct while the API runs one worker (it does — the
Dockerfile pins it). More workers would need a shared store; that is where the
decision lives, not here. The per-IP `limit_req` at the ingress is item 8's.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field

#: The first failure's delay, in seconds; each further consecutive failure doubles it.
BASE_DELAY = 1.0
#: The ceiling — five minutes. Reached after nine consecutive failures.
MAX_DELAY = 300.0


@dataclass
class FailureBudget:
    clock: Callable[[], float] = field(default=time.monotonic, repr=False)
    failures: int = 0
    locked_until: float = 0.0

    def retry_after(self) -> int | None:
        """Whole seconds until the next attempt is allowed, or None when it is
        allowed now. Rounded up: a `Retry-After` that says 0 while the gate is
        still shut would invite an immediate retry that is refused again."""
        remaining = self.locked_until - self.clock()
        if remaining <= 0:
            return None
        return max(1, math.ceil(remaining))

    def record_failure(self) -> float:
        """One more consecutive failure; returns the delay now in force."""
        self.failures += 1
        delay = min(BASE_DELAY * (2 ** (self.failures - 1)), MAX_DELAY)
        self.locked_until = self.clock() + delay
        return delay

    def reset(self) -> None:
        self.failures = 0
        self.locked_until = 0.0
