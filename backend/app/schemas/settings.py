from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import DateStyle, HourCycle


class InstanceSettingsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    interface_language: str
    formatting_locale: str
    time_zone: str
    date_style: DateStyle
    hour_cycle: HourCycle
    reference_currency: str
    updated_at: datetime


class InstanceSettingsUpdate(BaseModel):
    """PATCH payload — only supplied fields change (§6.1).

    Every field is optional-to-omit but none is nullable on the row: the service
    reads `model_fields_set`, so an explicit null is a refused instruction rather
    than "leave it alone". String fields stay plain strings here — canonical
    casing and membership (supported language, real IANA zone, currency shape)
    live in services/instance_settings.py, where the CSV importer can share the
    same predicates (rule 1: the guards are shared, never the mutation path).
    """

    model_config = ConfigDict(extra="forbid")

    interface_language: str | None = None
    formatting_locale: str | None = None
    time_zone: str | None = None
    date_style: DateStyle | None = None
    hour_cycle: HourCycle | None = None
    reference_currency: str | None = None
