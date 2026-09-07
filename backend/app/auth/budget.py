"""The login failure budgets (§5.6, brute force; §5.8 T8; M6-3, #188; revised
for the 0.3.0 security scan, #221 item 4).

Two budgets, both in-process — correct while the API runs one worker, as it
does (the Dockerfile pins it); more workers would need a shared store, and that
is where the decision lives, not here. The per-address `limit_req` at the
ingress is item 8's and bounds each address before either of these runs.

- **A ladder per (action, client address).** Every failed `POST /auth/login`,
  `POST /auth/setup` or `POST /auth/oidc/start` from one address doubles a
  delay during which that address's further attempts at that action are
  refused with 429 and `Retry-After`, up to a ceiling. A delay, not a lockout,
  and *the guesser's own*: an attacker's failures shut the attacker's address
  and never the owner's. The instance-wide ladder this replaced could be held
  at its ceiling by one wrong password every five minutes, which kept a
  signed-out owner out for as long as the caller cared to continue (the scan's
  item 4). A ladder decays: after `DECAY_AFTER` of quiet its count restarts
  from one, so a fat-fingered owner is not still at the ceiling an hour later.
  A successful login resets it. The table is bounded (`MAX_TRACKED`): when it
  is full, idle ladders go first, then the least recently failed — a
  wide-enough flood can evict its own ladders, which costs it the exponential
  delay but not the two bounds below it.
- **One verification budget for the instance.** A password or setup-token
  check costs Argon2 work on the single worker, so at most
  `VERIFICATIONS_PER_MINUTE` are performed instance-wide, whatever addresses
  they come from; beyond that an attempt is refused with a short `Retry-After`
  *before* the work is done. This bounds what a distributed guesser can make
  the worker do, and it can delay the owner only while such a flood is under
  way, by seconds — it never excludes a correct credential on the strength of
  someone else's failures.

The refusal budget the pre-routing guard's audit recorder reads (`RefusalBudget`,
#210 / #221 item 3) lives here too: the same in-process shape, keyed the same
way, for the same reason.
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
#: A ladder whose last failure is older than this restarts from one.
DECAY_AFTER = 2 * MAX_DELAY
#: Ladders kept at once, across every action and address.
MAX_TRACKED = 4096
#: Password / setup-token verifications the instance performs per minute, at
#: most, whoever asks: Argon2 is deliberately slow, and one worker serves it.
VERIFICATIONS_PER_MINUTE = 30


@dataclass
class FailureBudget:
    """One ladder: consecutive failures from one address at one action."""

    clock: Callable[[], float] = field(default=time.monotonic, repr=False)
    failures: int = 0
    locked_until: float = 0.0
    last_failure: float = -math.inf

    def retry_after(self) -> int | None:
        """Whole seconds until the next attempt is allowed, or None when it is
        allowed now. Rounded up: a `Retry-After` that says 0 while the gate is
        still shut would invite an immediate retry that is refused again."""
        remaining = self.locked_until - self.clock()
        if remaining <= 0:
            return None
        return max(1, math.ceil(remaining))

    def record_failure(self) -> float:
        """One more consecutive failure; returns the delay now in force. A
        failure after `DECAY_AFTER` of quiet starts the ladder over."""
        now = self.clock()
        if now - self.last_failure > DECAY_AFTER:
            self.failures = 0
        self.failures += 1
        self.last_failure = now
        delay = min(BASE_DELAY * (2 ** (self.failures - 1)), MAX_DELAY)
        self.locked_until = now + delay
        return delay

    def reset(self) -> None:
        self.failures = 0
        self.locked_until = 0.0
        self.last_failure = -math.inf

    def idle(self, now: float) -> bool:
        """Open and decayed: nothing about this ladder is worth remembering."""
        return self.locked_until <= now and now - self.last_failure > DECAY_AFTER


@dataclass
class VerificationBudget:
    """A token bucket over the instance's credential verifications: `capacity`
    tokens, refilled at `capacity` per minute, one per verification."""

    clock: Callable[[], float] = field(default=time.monotonic, repr=False)
    capacity: int = VERIFICATIONS_PER_MINUTE
    tokens: float = field(default=float(VERIFICATIONS_PER_MINUTE))
    refilled_at: float = field(default=-math.inf)

    def _refill(self) -> float:
        now = self.clock()
        if self.refilled_at > -math.inf:
            self.tokens = min(self.capacity, self.tokens + (now - self.refilled_at) * self.rate)
        self.refilled_at = now
        return now

    @property
    def rate(self) -> float:
        """Tokens per second."""
        return self.capacity / 60.0

    def take(self) -> int | None:
        """Spend one token, or say how many whole seconds until one is back."""
        self._refill()
        if self.tokens >= 1:
            self.tokens -= 1
            return None
        return max(1, math.ceil((1 - self.tokens) / self.rate))

    def reset(self) -> None:
        self.tokens = float(self.capacity)
        self.refilled_at = -math.inf


class FailureBudgets:
    """The process's budgets: a ladder per (action, address) and the one
    verification bucket. `app.state` holds a single instance."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.verification = VerificationBudget(clock=clock)
        self._ladders: dict[tuple[str, str | None], FailureBudget] = {}

    def ladder(self, target: str, address: str | None) -> FailureBudget:
        """The ladder for `address` at `target`, created on first use."""
        key = (target, address)
        found = self._ladders.get(key)
        if found is not None:
            return found
        if len(self._ladders) >= MAX_TRACKED:
            self._evict()
        ladder = FailureBudget(clock=self.clock)
        self._ladders[key] = ladder
        return ladder

    def _evict(self) -> None:
        now = self.clock()
        idle = [key for key, ladder in self._ladders.items() if ladder.idle(now)]
        if idle:
            for key in idle:
                del self._ladders[key]
            return
        oldest = min(self._ladders, key=lambda key: self._ladders[key].last_failure)
        del self._ladders[oldest]

    @property
    def tracked(self) -> int:
        return len(self._ladders)

    def reset(self) -> None:
        """Forget everything — tests, and a host-side recovery that wants the
        running process's memory cleared."""
        self._ladders.clear()
        self.verification.reset()


# --- the refusal budget (audit volume; #210, #221 item 3) ---------------------------

#: Refusal rows one address may add to the audit table per window.
REFUSALS_PER_ADDRESS = 10
#: Refusal rows the whole instance may add per window, whatever the addresses.
REFUSALS_PER_WINDOW = 60
#: The window, in seconds.
REFUSAL_WINDOW = 60.0


class RefusalBudget:
    """Bounds the rows the pre-routing Host/Origin guard's recorder writes.

    A refusal is refused whether or not it is recorded — the budget decides only
    whether this one earns its own audit row. Within a window each address gets
    `REFUSALS_PER_ADDRESS` rows and the instance `REFUSALS_PER_WINDOW`; every
    refusal past either bound is counted, and the count is written as one
    `ingress.refusals_suppressed` row on the first recorded refusal of the next
    window — so a flood costs the database at most the bound plus one row per
    minute, and the first rows of it keep their address and path. The
    per-address map is emptied at each window and can hold no more entries than
    the instance-wide bound admits, so it is bounded too.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.window_started = clock()
        self.total = 0
        #: Refusals this window has left unrecorded so far.
        self.suppressed = 0
        #: Counts of rolled-over windows, not yet written.
        self._pending_summary = 0
        self._per_address: dict[str | None, int] = {}

    def admit(self, address: str | None) -> tuple[bool, int]:
        """Whether this refusal earns a row, and the count a rolled-over window
        left unrecorded (0 when none) — written with this row when it is
        admitted; carried forward otherwise."""
        now = self.clock()
        if now - self.window_started >= REFUSAL_WINDOW:
            self.window_started = now
            self.total = 0
            self._per_address.clear()
            self._pending_summary += self.suppressed
            self.suppressed = 0
        if self.total >= REFUSALS_PER_WINDOW or self._per_address.get(address, 0) >= (
            REFUSALS_PER_ADDRESS
        ):
            self.suppressed += 1
            return False, 0
        self.total += 1
        self._per_address[address] = self._per_address.get(address, 0) + 1
        summary, self._pending_summary = self._pending_summary, 0
        return True, summary
