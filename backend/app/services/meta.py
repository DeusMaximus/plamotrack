"""Instance identity and settings, assembled once for both wrappers (rule 1).

`get_meta` first shipped calling the REST route handler directly, which inverted
the binding: REST and MCP are both thin wrappers over a service, and MCP is not a
consumer of the REST layer (#130 review, round 2, P3-6). The reference currency
moved from cached environment config into the instance-settings row with #23, so
this now takes a session — but the construction living here is still what keeps
the two surfaces one function apart from their transports.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.schemas.meta import MetaRead
from app.services import instance_settings


async def instance_meta(session: AsyncSession) -> MetaRead:
    return MetaRead(
        version=__version__,
        reference_currency=await instance_settings.reference_currency(session),
    )
