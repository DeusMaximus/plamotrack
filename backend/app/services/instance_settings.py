"""Instance settings: one row, one reader path, one writer path (§6.1, #23).

Every surface that needs a setting — REST, MCP, the browser via either, and the
CSV importer — reads the singleton row through here, so a change lands everywhere
at once. ``REFERENCE_CURRENCY`` in the environment is a first-run bootstrap: the
migration that creates the table seeds the row from it, and from then on the
database value is the instance's answer. The env var never overrides the row.

The validators are module-level functions raising plain ``ValueError`` on
purpose: the importer writes this table by direct ``setattr`` like every other
(rule 1's third writer), so its cell parsers in ``portability/spec.py`` call the
same predicates this service does. What the writers share is the validation,
never the mutation path.
"""

import re
import zoneinfo
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession

from app import error_codes
from app.exceptions import InvalidInputError
from app.models.enums import DateStyle, HourCycle
from app.models.settings import SINGLETON_ROW_ID, InstanceSettings
from app.schemas.settings import InstanceSettingsUpdate
from app.services.currency import require_currency_code
from app.services.write_gate import acquire_write_gate

#: Interface languages this build can actually render. `en-AU` is the canonical
#: source catalogue (§6.1); additional catalogues arrive through reviewed PRs and
#: extend this tuple when they meet the coverage bar. Deliberately a membership
#: test where `reference_currency` is only a shape test: an unknown currency is
#: still money the owner can spend, an unknown language is an interface nothing
#: can display.
#:
#: The catalogues themselves live in `frontend/src/i18n/` (#22), registered in
#: `manifest.json` there; `backend/tests/test_settings.py` asserts this tuple
#: equals that manifest's enabled tags, so enabling a language is one PR
#: touching both.
SUPPORTED_INTERFACE_LANGUAGES: tuple[str, ...] = ("en-AU",)

#: What a fresh instance's row holds, minus the reference currency — that half of
#: the bootstrap comes from the environment (`REFERENCE_CURRENCY`, default AUD)
#: and is seeded by the migration. UTC is deliberate for the time zone: the one
#: deterministic value every install shares, changed from Settings rather than
#: guessed from whichever container or browser happened to boot first.
DEFAULTS: dict[str, str] = {
    "interface_language": "en-AU",
    "formatting_locale": "en-AU",
    "time_zone": "UTC",
    "date_style": DateStyle.LOCALE.value,
    "hour_cycle": HourCycle.LOCALE.value,
}

# language(-Script)?(-REGION)?(-variant)* — the shape `Intl` formatters consume
# (UTS 35 unicode_language_id), which is narrower than raw BCP 47 in two ways
# that matter (PR #159 review, P3-2): the language subtag is 2–3 letters or a
# registered 5–8 (four-letter tags are reserved and `Intl` throws on them), and
# a variant may appear once — the duplicate check lives below, since a regex
# can't see it. Extension and private-use subtags (-u-…, -x-…) are refused:
# `-u-hc-` and `-u-ca-` would smuggle in a second hour-cycle or calendar setting
# that fights the explicit columns beside this one.
_LOCALE_RE = re.compile(
    r"^(?P<language>[A-Za-z]{2,3}|[A-Za-z]{5,8})"
    r"(?:-(?P<script>[A-Za-z]{4}))?"
    r"(?:-(?P<region>[A-Za-z]{2}|[0-9]{3}))?"
    r"(?P<variants>(?:-(?:[A-Za-z0-9]{5,8}|[0-9][A-Za-z0-9]{3}))*)$"
)


def canonical_locale(raw: str) -> str:
    """A well-formed BCP 47 tag in canonical casing, or a ValueError.

    `en-au`, `EN-AU` and `en-AU` are one locale; storing whichever casing was
    typed would make the same setting diff against itself in an import preview.
    """
    value = raw.strip()
    match = _LOCALE_RE.fullmatch(value)
    if match is None:
        raise ValueError(
            f"'{raw}' is not a locale tag — use a BCP 47 tag like en-AU, ja or zh-Hans-TW "
            "(extension subtags such as -u-… aren't accepted here)"
        )
    parts = [match["language"].lower()]
    if match["script"]:
        parts.append(match["script"].capitalize())
    if match["region"]:
        parts.append(match["region"].upper())
    if match["variants"]:
        variants = [part.lower() for part in match["variants"].strip("-").split("-")]
        if len(set(variants)) != len(variants):
            # BCP 47 forbids a repeated variant and `Intl` throws on one — a
            # stored tag the formatter refuses is not a formatting preference.
            raise ValueError(f"'{raw}' repeats a variant subtag — each may appear once")
        # Sorted because that is UTS 35's canonical order — `Intl` sorts them, the
        # order carries no meaning, and 'sl-rozaj-biske' / 'sl-biske-rozaj' must
        # not be storable as two different settings (found by the shared
        # locale-cases fixture the review asked for).
        parts.extend(sorted(variants))
    return "-".join(parts)


def validate_interface_language(raw: str) -> str:
    value = canonical_locale(raw)
    if value not in SUPPORTED_INTERFACE_LANGUAGES:
        supported = ", ".join(SUPPORTED_INTERFACE_LANGUAGES)
        raise ValueError(
            f"'{raw}' is not an interface language this build ships — currently: {supported}"
        )
    return value


def validate_formatting_locale(raw: str) -> str:
    """Well-formedness only, no membership test: formatting is CLDR's job and the
    browser's `Intl` resolves any well-formed tag to its nearest supported locale,
    so refusing one here would strand a valid preference this list never heard of —
    the same reasoning `KNOWN_CURRENCIES` records for unrecognised currencies."""
    return canonical_locale(raw)


@lru_cache
def _zones_by_fold() -> dict[str, str]:
    return {name.lower(): name for name in sorted(zoneinfo.available_timezones())}


def validate_time_zone(raw: str) -> str:
    """The canonical IANA spelling, resolved case-insensitively — the same
    leniency the enum parsers extend to agents. Membership, not shape: a zone
    the tz database doesn't know is a value no formatter can apply."""
    value = raw.strip()
    found = _zones_by_fold().get(value.lower())
    if found is None:
        raise ValueError(
            f"'{raw}' is not an IANA time zone — use a name like Australia/Sydney or UTC"
        )
    return found


#: Field -> canonicaliser, for the string fields. The currency entry is the
#: shared §6 shape test itself (`require_currency_code` — ASCII, uppercased, no
#: membership test; PR #159 review, P2, is why there is exactly one copy). The
#: two enum fields are typed as their StrEnum in the schema and parsed by
#: `enum_parser` in the CSV spec, so membership is already settled before a
#: value reaches the row.
_VALIDATORS = {
    "interface_language": validate_interface_language,
    "formatting_locale": validate_formatting_locale,
    "time_zone": validate_time_zone,
    "reference_currency": require_currency_code,
}

_MISSING_ROW = (
    "the instance_settings row is missing — migrations create it; run `alembic upgrade head`"
)


async def get_instance_settings(session: AsyncSession) -> InstanceSettings:
    row = await session.get(InstanceSettings, SINGLETON_ROW_ID)
    if row is None:
        # Deployment breakage, not client error: a 500 is the honest status.
        raise RuntimeError(_MISSING_ROW)
    return row


async def reference_currency(session: AsyncSession) -> str:
    """The default currency for new entries (§6) — the write paths' one read."""
    return (await get_instance_settings(session)).reference_currency


async def update_instance_settings(
    session: AsyncSession, data: InstanceSettingsUpdate
) -> InstanceSettings:
    """Apply the supplied fields to the singleton row.

    Gate before the locked read (rule 7.1), and the row itself `FOR UPDATE`
    (rule 7): two concurrent PATCHes serialize, and the second works from what
    the first committed rather than overwriting it with a stale copy.
    """
    await acquire_write_gate(session)
    row = await session.get(InstanceSettings, SINGLETON_ROW_ID, with_for_update=True)
    if row is None:
        raise RuntimeError(_MISSING_ROW)
    for field in data.model_fields_set:
        value = getattr(data, field)
        if value is None:
            # Nothing here is nullable; an explicit null is an instruction the
            # row cannot hold, not shorthand for "reset" or "leave alone".
            raise InvalidInputError(
                f"{field} can't be cleared — every instance setting always has a value. "
                "Leave the field out to keep the current one.",
                code=error_codes.SETTINGS_FIELD_REQUIRED,
                params={"field": field},
            )
        validator = _VALIDATORS.get(field)
        if validator is not None:
            try:
                value = validator(value)
            except ValueError as exc:
                raise InvalidInputError(
                    str(exc),
                    code=error_codes.SETTINGS_VALUE_INVALID,
                    params={"field": field},
                ) from exc
        setattr(row, field, value)
    await session.flush()
    # The UPDATE's server-side onupdate expires `updated_at`; load it here, while
    # we can still await, or response serialization trips a sync lazy-load.
    await session.refresh(row)
    await session.commit()
    return row
