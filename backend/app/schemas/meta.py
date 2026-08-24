from pydantic import BaseModel


class MetaRead(BaseModel):
    """Instance-level settings a client needs before it can render a form."""

    version: str
    #: Default currency for new entries and for the conversion snapshot (§6).
    #: Stored per row at entry time, so changing this never restates history.
    reference_currency: str
