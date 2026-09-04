"""Stable semantic error codes for the REST envelope (#25) and the
import-preview diagnostics (#26).

The contract: every code below reaches the wire one of two ways — a
`DomainError` raise (the failed-response envelope) or a `Diagnostic`
construction (`schemas/portability.py`, inside a successful preview payload).
A code is `<domain>.<condition>`, both segments snake_case — it describes the
condition, not the emission site or the Python class, so three "insufficient
stock" raises share one code, and an invariant the importer mirrors from a live
writer reuses that writer's code (`order.receipt_in_future` is the same
condition whether it 422s an edit or errors a CSV row). Codes are wire
contract: renaming one is a breaking API change.

The browser renders known codes through the i18n catalogue (`api.<domain>.
<condition>` — always exactly that depth, so keep codes to two segments) and
falls back to the English `detail` for codes it doesn't know. The list below is
mirrored in `frontend/src/lib/__fixtures__/api-error-codes.json` together with
each code's guaranteed params; `tests/test_error_envelope.py` holds this module
and that fixture together, and the frontend catalogue suite holds the
translations to the fixture. Adding a code = a constant here + a fixture entry
+ an `api.*` catalogue entry.
"""

# --- not found (404) -------------------------------------------------------
KIT_NOT_FOUND = "kit.not_found"
ORDER_NOT_FOUND = "order.not_found"
RETAILER_NOT_FOUND = "retailer.not_found"
CATALOG_ITEM_NOT_FOUND = "catalog_item.not_found"
UPGRADE_APPLICATION_NOT_FOUND = "upgrade_application.not_found"
EXPORT_TABLE_UNKNOWN = "export.table_unknown"

# --- conflicts (409) -------------------------------------------------------
ORDER_ALREADY_RECEIVED = "order.already_received"
ORDER_ALREADY_SHIPPED = "order.already_shipped"
ORDER_NOT_RECEIVED = "order.not_received"
ORDER_NOT_SHIPPED = "order.not_shipped"
RETAILER_HAS_ORDERS = "retailer.has_orders"
CATALOG_ITEM_ON_ORDER_HISTORY = "catalog_item.on_order_history"
CATALOG_ITEM_HAS_APPLICATIONS = "catalog_item.has_applications"
KIT_ORDER_SPAWNED = "kit.order_spawned"
KIT_HAS_APPLICATIONS = "kit.has_applications"
ORDER_LINE_KITS_PROTECTED = "order_line.kits_protected"
ORDER_LINE_REF_DANGLING = "order_line.catalog_ref_dangling"
STOCK_INSUFFICIENT = "stock.insufficient"
STOCK_LIMIT_EXCEEDED = "stock.limit_exceeded"
NAME_DUPLICATE = "name.duplicate"
IMPORT_BLOCKED = "import.blocked"
IMPORT_PLAN_STALE = "import.plan_stale"

# --- invalid input (422) ---------------------------------------------------
FIELD_NOT_NULLABLE = "field.not_nullable"
FIELD_BLANK = "field.blank"
NAME_BLANK = "name.blank"
VALUE_OUT_OF_RANGE = "value.out_of_range"
ORDER_LINE_QUANTITY_TOO_SMALL = "order_line.quantity_too_small"
ORDER_LINE_QUANTITY_TOO_LARGE = "order_line.quantity_too_large"
ORDER_FANOUT_LIMIT = "order.fanout_limit"
ORDER_RECEIPT_IN_FUTURE = "order.receipt_in_future"
ORDER_SHIPMENT_IN_FUTURE = "order.shipment_in_future"
ORDER_UNRECEIVE_UNSUPPORTED = "order.unreceive_unsupported"
ORDER_UNSHIP_UNSUPPORTED = "order.unship_unsupported"
ORDER_LINES_OMITTED = "order.lines_omitted"
ORDER_LINE_NOT_ON_ORDER = "order_line.not_on_order"
ORDER_LINE_DUPLICATED = "order_line.duplicated"
ORDER_LINE_TYPE_IMMUTABLE = "order_line.item_type_immutable"
ORDER_LINE_NO_KIT_TO_CLONE = "order_line.no_kit_to_clone"
CATALOG_ITEM_CATEGORY_REQUIRED = "catalog_item.category_required"
CATALOG_ITEM_MANUFACTURER_REQUIRED = "catalog_item.manufacturer_required"
CATALOG_ITEM_CATEGORY_UNSUPPORTED = "catalog_item.category_unsupported"
CATALOG_ITEM_COST_PAIR_MISMATCH = "catalog_item.cost_pair_mismatch"
UPGRADE_APPLICATION_QUANTITY_INVALID = "upgrade_application.quantity_invalid"
SETTINGS_FIELD_REQUIRED = "settings.field_required"
SETTINGS_VALUE_INVALID = "settings.value_invalid"
IMPORT_ENCODING_INVALID = "import.encoding_invalid"
IMPORT_FILE_TOO_LARGE = "import.file_too_large"
IMPORT_FILE_UNSUPPORTED = "import.file_unsupported"
IMPORT_ARCHIVE_TOO_LARGE = "import.archive_too_large"
IMPORT_ARCHIVE_DAMAGED = "import.archive_damaged"
IMPORT_ARCHIVE_INVALID = "import.archive_invalid"
IMPORT_TABLE_UNKNOWN = "import.table_unknown"
IMPORT_VERSION_NEWER = "import.version_newer"
IMPORT_TOO_MANY_ROWS = "import.too_many_rows"
IMPORT_CONFIRM_REQUIRED = "import.confirm_required"
IMPORT_PREVIEW_REQUIRED = "import.preview_required"
IMPORT_CELL_INVALID = "import.cell_invalid"

# --- import-preview diagnostics (#26) ---------------------------------------
# Emitted as `Diagnostic` objects inside the 200 preview payload rather than
# raised, except where noted. Row errors, row messages, plan warnings, blocking
# errors and the stock note all draw from here; codes the importer shares with
# a live writer (quantity bounds, future dates, un-ship) are listed above and
# not repeated.

# archive/upload stage — how the zip and its manifest read
IMPORT_MEMBER_DUPLICATED = "import.member_duplicated"
IMPORT_MANIFEST_AMBIGUOUS = "import.manifest_ambiguous"
IMPORT_MANIFEST_UNREADABLE = "import.manifest_unreadable"
IMPORT_MANIFEST_METADATA_UNREADABLE = "import.manifest_metadata_unreadable"
IMPORT_MANIFEST_NOT_OBJECT = "import.manifest_not_object"
IMPORT_MANIFEST_MISSING = "import.manifest_missing"
IMPORT_MEMBER_UNRECOGNISED = "import.member_unrecognised"
IMPORT_NO_TABLE_DATA = "import.no_table_data"
IMPORT_MANIFEST_FILE_ABSENT = "import.manifest_file_absent"
IMPORT_MANIFEST_FILE_AMBIGUOUS = "import.manifest_file_ambiguous"
IMPORT_MANIFEST_TABLE_MISMATCH = "import.manifest_table_mismatch"
IMPORT_MANIFEST_ROWS_MISMATCH = "import.manifest_rows_mismatch"
IMPORT_MEMBER_UNDECLARED = "import.member_undeclared"
IMPORT_FORMAT_FOREIGN = "import.format_foreign"
IMPORT_SCHEMA_DRIFT = "import.schema_drift"

# row parsing and identity
IMPORT_COLUMN_UNKNOWN = "import.column_unknown"
IMPORT_CELL_REQUIRED = "import.cell_required"
IMPORT_MATCH_AMBIGUOUS = "import.match_ambiguous"
IMPORT_ORDER_MATCH_AMBIGUOUS = "import.order_match_ambiguous"
IMPORT_ID_DUPLICATED = "import.id_duplicated"
IMPORT_TARGET_DUPLICATED = "import.target_duplicated"
IMPORT_NATURAL_KEY_DUPLICATED = "import.natural_key_duplicated"
IMPORT_VALUE_REQUIRED_FOR_CREATE = "import.value_required_for_create"
IMPORT_SINGLETON_MISSING = "import.singleton_missing"

# references
IMPORT_REF_OVERWRITE_UNRESOLVED = "import.ref_overwrite_unresolved"
IMPORT_REF_NOT_IN_UPLOAD = "import.ref_not_in_upload"
IMPORT_REF_UNMATCHED = "import.ref_unmatched"
IMPORT_REF_DANGLING = "import.ref_dangling"
IMPORT_REF_IGNORED_KIT_LINE = "import.ref_ignored_kit_line"
IMPORT_STUB_CREATED = "import.stub_created"
IMPORT_STUB_CREATED_UNSTOCKED = "import.stub_created_unstocked"

# cell semantics
IMPORT_KEPT_STORED = "import.kept_stored"
IMPORT_STATUS_STAMP_GENERATED = "import.status_stamp_generated"
IMPORT_CURRENCY_UNKNOWN = "import.currency_unknown"
IMPORT_CURRENCY_WITHOUT_AMOUNT = "import.currency_without_amount"
IMPORT_MONEY_AMBIGUOUS = "import.money_ambiguous"
IMPORT_KIT_NAME_EXISTS = "import.kit_name_exists"
IMPORT_CATEGORY_FOLDED = "import.category_folded"

# the §3.9 dispatch — spawns, removals, advances, and their refusals
IMPORT_SPAWN_SOURCE_MISSING = "import.spawn_source_missing"
IMPORT_KIT_MOVE_TO_CATALOG_LINE = "import.kit_move_to_catalog_line"
IMPORT_KIT_MOVE_QUANTITY_UNSTATED = "import.kit_move_quantity_unstated"
IMPORT_KIT_MOVE_UNRECONCILED = "import.kit_move_unreconciled"
IMPORT_KITS_OVERSUPPLIED = "import.kits_oversupplied"
IMPORT_KITS_NOT_REMOVABLE = "import.kits_not_removable"
IMPORT_KITS_SPAWN_PLANNED = "import.kits_spawn_planned"
IMPORT_KITS_REMOVAL_PLANNED = "import.kits_removal_planned"
IMPORT_KITS_SHIP_ADVANCE = "import.kits_ship_advance"
IMPORT_KITS_RECEIVE_ADVANCE = "import.kits_receive_advance"
IMPORT_PROVENANCE_PROTECTED = "import.provenance_protected"

# order invariants (#44) surfaced as row diagnostics
ORDER_LINE_ORDER_IMMUTABLE = "order_line.order_immutable"
IMPORT_CATALOG_REF_UNRESOLVED = "import.catalog_ref_unresolved"
IMPORT_LINE_JOINS_RECEIVED = "import.line_joins_received"
IMPORT_RECEIPT_UNACCOUNTED = "import.receipt_unaccounted"
IMPORT_UNRECEIVE_UNACCOUNTED = "import.unreceive_unaccounted"

# plan-level
IMPORT_ROWS_UNREADABLE = "import.rows_unreadable"
IMPORT_STOCK_NOTE = "import.stock_note"

# starter sheet
IMPORT_RECEIPT_CONFLICT = "import.receipt_conflict"

# --- ingress refusals (before routing — app/ingress.py, §5.6) ----------------
# 421: the Host header names nothing the instance answers to. 403: an unsafe
# request's Origin (or Referer) fails the three-way rule. `params.setting` is
# the .env key that fixes it, so the sentence can point at it.
INGRESS_HOST_NOT_ALLOWED = "ingress.host_not_allowed"
INGRESS_ORIGIN_NOT_ALLOWED = "ingress.origin_not_allowed"

# --- authorization refusals (the route-policy dependency — app/auth, §5.5) ----
# 401: no credential, or a presented one that fails, on a route that needs one.
# 403: an authenticated principal whose scope is insufficient. Raised by the
# authorization dependency; no params (the sentence names no value).
AUTH_UNAUTHENTICATED = "auth.unauthenticated"
AUTH_FORBIDDEN = "auth.forbidden"

# --- local owner authentication (M6-3, #188 — §5.5 families 2–3, §5.6) --------
# 401 `login_failed` / `setup_token_invalid`: the presented secret is wrong (one
# body for every failure kind, T11). 410 `setup_claimed`: the instance already
# has an owner. 429 `too_many_attempts`: the failure budget is shut, `params.
# retry_after` in seconds. 403 `csrf_failed` / `origin_required`: a cookie-borne
# unsafe request without the session-bound token, or without an Origin/Referer.
# 422 `password_too_short` / `password_too_long`: `params.min` / `params.max`.
AUTH_LOGIN_FAILED = "auth.login_failed"
AUTH_SETUP_TOKEN_INVALID = "auth.setup_token_invalid"
AUTH_SETUP_CLAIMED = "auth.setup_claimed"
AUTH_TOO_MANY_ATTEMPTS = "auth.too_many_attempts"
AUTH_CSRF_FAILED = "auth.csrf_failed"
AUTH_ORIGIN_REQUIRED = "auth.origin_required"
AUTH_PASSWORD_TOO_SHORT = "auth.password_too_short"
AUTH_PASSWORD_TOO_LONG = "auth.password_too_long"

# --- personal access tokens (M6-4, #189 — §5.5 family 6, §5.6) -----------------
# 401 `bearer_invalid`: an `Authorization` header was presented and failed —
# unknown, wrong secret, expired, revoked, malformed, or not a bearer at all; one
# body for every kind (T11). 404 `token_not_found`: no token with that id. 422
# `token_scope_invalid`: the requested scopes are empty, unknown, or include
# `instance:admin` (no admin tokens in M6). 422 `token_expiry_in_past`: the
# requested expiry has already passed.
AUTH_BEARER_INVALID = "auth.bearer_invalid"
AUTH_TOKEN_NOT_FOUND = "auth.token_not_found"
AUTH_TOKEN_SCOPE_INVALID = "auth.token_scope_invalid"
AUTH_TOKEN_EXPIRY_IN_PAST = "auth.token_expiry_in_past"

# --- request validation (FastAPI's 422 list shape) -------------------------
REQUEST_VALIDATION = "request.validation"

# --- parser-stage failures (the 400 the framework raises before any schema
# --- or service runs: multipart with no boundary, an unreadable body) -------
REQUEST_BODY_INVALID = "request.body_invalid"


def all_codes() -> tuple[str, ...]:
    """Every code constant in this module, for the fixture-parity test."""
    return tuple(
        sorted(
            value for name, value in globals().items() if name.isupper() and isinstance(value, str)
        )
    )
