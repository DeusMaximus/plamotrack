"""Stable semantic error codes for the REST envelope (#25).

The contract: every `DomainError` raise names one of these. A code is
`<domain>.<condition>`, both segments snake_case — it describes the condition,
not the raise site or the Python class, so three "insufficient stock" raises
share one code. Codes are wire contract: renaming one is a breaking API change.

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

# --- request validation (FastAPI's 422 list shape) -------------------------
REQUEST_VALIDATION = "request.validation"


def all_codes() -> tuple[str, ...]:
    """Every code constant in this module, for the fixture-parity test."""
    return tuple(
        sorted(
            value for name, value in globals().items() if name.isupper() and isinstance(value, str)
        )
    )
