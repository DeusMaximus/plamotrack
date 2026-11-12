"""An order's **stage** in the pipeline (design §13.2, #233): where it sits on
Home's *In the mail* board and what the Orders page filters by.

One predicate, read by three things that must agree — the `stage` field every
order row carries (`schemas/orders.py::OrderRead`), the per-stage counts in
`services/summary.py`, and through those the browser, which computes nothing of
its own (rule 1: the counts in Home's headings are the totals the list pages
show, so one definition, on the server). A leaf module, because the read schema
imports it and `services/orders.py` imports the read schema.

The rules, in precedence order:

- **received** — `received_at` is set. Whatever else the row says, the box is here.
- **in_transit** — `shipped_at` is set and the box is not here yet.
- **pre_ordered** — nothing shipped, and *every* kit the order spawned is still
  `pre_ordered` — and there is at least one. Derived from the kits, never stored
  (#95): the distinction stops mattering the moment the order ships, and a kit
  moved by hand out of `pre_ordered` moves the order out with it.
- **ordered** — everything else: a pending order with an ordered kit, a mixed one
  (the pre-ordered line carries a tag on Home), or one with no kit lines at all
  (paint and tools carry no signal, by decision).
"""

from typing import Literal, Protocol

from app.models.enums import KitStatus

OrderStage = Literal["pre_ordered", "ordered", "in_transit", "received"]
ORDER_STAGES: tuple[OrderStage, ...] = ("pre_ordered", "ordered", "in_transit", "received")


class _KitLike(Protocol):
    status: KitStatus


class _LineLike(Protocol):
    kits: list  # of _KitLike


class _OrderLike(Protocol):
    """What the predicate reads — satisfied by the ORM `Order` (items and kits
    eager-loaded, as `get_order` and `list_orders` do) and by `OrderRead`."""

    received_at: object
    shipped_at: object
    items: list  # of _LineLike


def order_stage(order: _OrderLike) -> OrderStage:
    if order.received_at is not None:
        return "received"
    if order.shipped_at is not None:
        return "in_transit"
    kits = [kit for item in order.items for kit in item.kits]
    if kits and all(kit.status == KitStatus.PRE_ORDERED for kit in kits):
        return "pre_ordered"
    return "ordered"
