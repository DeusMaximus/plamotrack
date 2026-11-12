"""What an order cost, and what was paid for it (#350).

Derived on the way out and never stored: an order's lines hold what the shop
charged for each thing, its shipping what the post cost, and its adjustments what
came off at the checkout — a discount, a voucher, a gift card. `paid` is those
three combined, so an edit to any of them cannot leave a stale total behind.

One definition, read by three things that must agree (rule 1): the `totals` every
order row carries (`schemas/orders.py::OrderRead`), the ceiling `create_order` and
`update_order` hold adjustments to, and the same ceiling in the CSV importer's
preview (`portability/invariants.py`). A leaf module, because the read schema
imports it and `services/orders.py` imports the read schema.

**Per currency, because an order is.** A line carries its own `currency_code`
(§6), so an order bought partly in yen and partly in dollars has two totals and
no honest way to add them. Shipping and adjustments are in the order's own
currency, so only that currency's total has them.

**The ceiling.** Adjustments never exceed the lines in the order's currency plus
its shipping, so `paid_minor` is never negative. Lines in another currency do not
count toward it: nothing here converts, and a deduction in dollars cannot come
off a price in yen.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class CurrencyTotal:
    """One currency's share of an order. `shipping_minor` and `adjustments_minor`
    are zero in every currency but the order's own."""

    currency_code: str
    items_minor: int
    shipping_minor: int
    adjustments_minor: int

    @property
    def paid_minor(self) -> int:
        return self.items_minor + self.shipping_minor - self.adjustments_minor


class _LineLike(Protocol):
    currency_code: str
    quantity: int
    unit_price_minor: int


class _AdjustmentLike(Protocol):
    amount_minor: int


class _OrderLike(Protocol):
    """What the totals read — satisfied by the ORM `Order` (lines and adjustments
    eager-loaded, as `get_order` and `list_orders` do) and by `OrderRead`."""

    currency_code: str
    shipping_cost_minor: int | None
    items: list  # of _LineLike
    adjustments: list  # of _AdjustmentLike


def totals(
    *,
    currency_code: str,
    shipping_cost_minor: int | None,
    lines: Iterable[tuple[str, int, int]],
    adjustments: Iterable[int],
) -> list[CurrencyTotal]:
    """An order's totals from its bare numbers: `lines` as `(currency, quantity,
    unit price)`, `adjustments` as amounts in the order's currency.

    One entry per currency, in the order the lines first name them. The order's
    own currency joins at the end when no line is in it and it still has
    something to say — a shipping cost above zero, or an adjustment. A recorded
    zero for shipping is not something to say: free post adds no currency.
    """
    items: dict[str, int] = {}
    for line_currency, quantity, unit_price_minor in lines:
        items[line_currency] = items.get(line_currency, 0) + quantity * unit_price_minor
    shipping = shipping_cost_minor or 0
    deducted = sum(adjustments)
    if currency_code not in items and (shipping or deducted):
        items[currency_code] = 0
    return [
        CurrencyTotal(
            currency_code=code,
            items_minor=minor,
            shipping_minor=shipping if code == currency_code else 0,
            adjustments_minor=deducted if code == currency_code else 0,
        )
        for code, minor in items.items()
    ]


def order_totals(order: _OrderLike) -> list[CurrencyTotal]:
    return totals(
        currency_code=order.currency_code,
        shipping_cost_minor=order.shipping_cost_minor,
        lines=((item.currency_code, item.quantity, item.unit_price_minor) for item in order.items),
        adjustments=(adjustment.amount_minor for adjustment in order.adjustments),
    )


@dataclass(frozen=True)
class Overrun:
    """Adjustments that come to more than they could have come off."""

    currency_code: str
    adjustments_minor: int
    #: The order's lines in `currency_code` plus its shipping: the most an
    #: adjustment in that currency can take off.
    ceiling_minor: int


def adjustment_overrun(
    *,
    currency_code: str,
    shipping_cost_minor: int | None,
    lines: Iterable[tuple[str, int, int]],
    adjustments: Iterable[int],
) -> Overrun | None:
    """The one rule about an order's adjustments taken together, or None when it
    holds. Every writer asks this of the order **as it will be stored**, since a
    cheaper line, a dropped shipping cost or a changed order currency breaks it as
    surely as a larger adjustment does.
    """
    own = next(
        (
            total
            for total in totals(
                currency_code=currency_code,
                shipping_cost_minor=shipping_cost_minor,
                lines=lines,
                adjustments=adjustments,
            )
            if total.currency_code == currency_code
        ),
        None,
    )
    if own is None or own.paid_minor >= 0:
        return None
    return Overrun(
        currency_code=currency_code,
        adjustments_minor=own.adjustments_minor,
        ceiling_minor=own.items_minor + own.shipping_minor,
    )


def order_adjustment_overrun(order: _OrderLike) -> Overrun | None:
    return adjustment_overrun(
        currency_code=order.currency_code,
        shipping_cost_minor=order.shipping_cost_minor,
        lines=((item.currency_code, item.quantity, item.unit_price_minor) for item in order.items),
        adjustments=(adjustment.amount_minor for adjustment in order.adjustments),
    )
