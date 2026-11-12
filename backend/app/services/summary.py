"""The collection at a glance (design §13.2, #233): how many kits sit in each
pipeline status and how many orders in each stage — Home's headings, and the
`get_summary` MCP tool. One function for both surfaces (rule 1), so the count in a
heading is the total the list page behind its *view all* link shows: the kit
counts group the same column `GET /kits?status=` filters on, and the order counts
apply `order_stage` to the same rows `GET /orders` serves with their `stage`.

Two statements, one snapshot (rule 7.2): the kit counts and the order stages are
read under `REPEATABLE READ`, so a receive committing between them cannot show
a kit already in the backlog beside its order still in the mail. A read, so no
write gate; a personal collection is a few hundred orders, and the rows are
loaded the way `list_orders` loads them — the stage is derived from the kits and
dates, never stored, so it is not something SQL can count on its own.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Kit, KitStatus, Order, OrderItem
from app.schemas.summary import KitCounts, OrderCounts, SummaryRead
from app.services.order_stage import ORDER_STAGES, order_stage
from app.services.read_snapshot import begin_read_snapshot


async def collection_summary(session: AsyncSession) -> SummaryRead:
    await begin_read_snapshot(session)
    kit_counts = {status.value: 0 for status in KitStatus}
    for status, count in await session.execute(
        select(Kit.status, func.count()).group_by(Kit.status)
    ):
        kit_counts[KitStatus(status).value] = count
    order_counts = {stage: 0 for stage in ORDER_STAGES}
    orders = await session.scalars(
        select(Order).options(selectinload(Order.items).selectinload(OrderItem.kits))
    )
    for order in orders:
        order_counts[order_stage(order)] += 1
    return SummaryRead(kits=KitCounts(**kit_counts), orders=OrderCounts(**order_counts))
