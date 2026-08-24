"""Instance identity and settings, assembled once for both wrappers (rule 1).

`get_meta` first shipped calling the REST route handler directly, which inverted
the binding: REST and MCP are both thin wrappers over a service, and MCP is not a
consumer of the REST layer (#130 review, round 2, P3-6). Plain config reads, so no
session and nothing async — but the construction living here is what keeps the two
surfaces one function apart from their transports.
"""

from app import __version__
from app.config import get_settings
from app.schemas.meta import MetaRead


def instance_meta() -> MetaRead:
    return MetaRead(version=__version__, reference_currency=get_settings().reference_currency)
