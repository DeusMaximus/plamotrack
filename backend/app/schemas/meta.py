from pydantic import BaseModel


class MetaRead(BaseModel):
    """Instance-level settings a client needs before it can render a form."""

    version: str
    #: Default currency for new entries and for the conversion snapshot (§6).
    #: Stored per row at entry time, so changing this never restates history.
    reference_currency: str
    #: The interface languages this build can actually serve (#27) — the
    #: catalogue tags a PATCH /settings will accept for `interface_language`,
    #: in the backend's canonical order. Advertised so a client can offer a
    #: selector without hardcoding the list; the frontend's own manifest is
    #: held to the same set by the parity test.
    supported_interface_languages: list[str]
