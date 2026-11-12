from pydantic import BaseModel


class KitCounts(BaseModel):
    """Kits per pipeline status — one field per `KitStatus` member, in pipeline
    order, every one present (a status nobody is in reads 0, not absent)."""

    pre_ordered: int
    ordered: int
    in_transit: int
    backlog: int
    building: int
    complete: int


class OrderCounts(BaseModel):
    """Orders per stage — one field per `services/order_stage.py::ORDER_STAGES`
    member. The first three are Home's *In the mail* columns; `received` is the
    rest of the purchase history."""

    pre_ordered: int
    ordered: int
    in_transit: int
    received: int


class SummaryRead(BaseModel):
    """The collection at a glance (§13.2): what Home's headings show and what an
    agent reads before asking for rows. Served by `GET /summary` and the
    `get_summary` MCP tool from one function (rule 1)."""

    kits: KitCounts
    orders: OrderCounts
