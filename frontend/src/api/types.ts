/** Pipeline order. `backlog` = physically in hand, not started (the former
 * in_hand status was merged into it). */
export const KIT_STATUSES = [
  "pre_ordered",
  "ordered",
  "in_transit",
  "backlog",
  "building",
  "complete",
] as const;

export type KitStatus = (typeof KIT_STATUSES)[number];

/** Wire values; what the user reads comes from the catalogue via
 * `itemTypeLabel` in lib/labels.ts (the runtime list exists so tests can drive
 * every member through that lookup). */
export const ITEM_TYPES = ["kit", "tool", "consumable", "upgrade", "display"] as const;

export type ItemType = (typeof ITEM_TYPES)[number];
export type CatalogItemType = Exclude<ItemType, "kit">;

export interface Kit {
  id: string;
  name: string;
  grade: string;
  scale: string | null;
  kit_number: string | null;
  /** Free text like grade (#96); suggestions come from /kits/series. */
  series: string | null;
  status: KitStatus;
  status_updated_at: string;
  rating: number | null;
  /** Owned by the user (#94): a transition to building/complete stamps one only
   *  when it is null; both stay editable and are never overwritten by a drag. */
  build_started_at: string | null;
  build_completed_at: string | null;
  build_notes: string | null;
  order_item_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface KitCreate {
  name: string;
  grade: string;
  scale?: string | null;
  kit_number?: string | null;
  series?: string | null;
  status?: KitStatus;
  build_started_at?: string | null;
  build_completed_at?: string | null;
  build_notes?: string | null;
}

export interface KitUpdate {
  name?: string;
  grade?: string;
  scale?: string | null;
  kit_number?: string | null;
  series?: string | null;
  status?: KitStatus;
  rating?: number | null;
  /** Offset-aware ISO 8601; send only when the user touched the field — a date
   *  input cannot restate the stored instant losslessly (#93's lesson). */
  build_started_at?: string | null;
  build_completed_at?: string | null;
  build_notes?: string | null;
}

export interface Tool {
  id: string;
  name: string;
  category: string;
  quantity_on_hand: number;
  unit_cost_reference_minor: number | null;
  unit_cost_reference_currency: string | null;
  condition_notes: string | null;
}

export interface ToolCreate {
  name: string;
  category: string;
  quantity_on_hand?: number;
  unit_cost_reference_minor?: number | null;
  unit_cost_reference_currency?: string | null;
  condition_notes?: string | null;
}

export interface Consumable {
  id: string;
  name: string;
  category: string;
  quantity_on_hand: number;
  low_stock_threshold: number | null;
}

export interface ConsumableCreate {
  name: string;
  category: string;
  quantity_on_hand?: number;
  low_stock_threshold?: number | null;
}

export interface Upgrade {
  id: string;
  name: string;
  manufacturer: string;
  quantity_on_hand: number;
}

export interface UpgradeCreate {
  name: string;
  manufacturer: string;
  quantity_on_hand?: number;
}

/** Stands, bases, diorama scenery (§3.5a, #126).
 *
 * Quantity only — deliberately no link to the kits it's used with, because a stand
 * moves between kits freely and a recorded link would be wrong most of the time.
 * `manufacturer` is nullable here but required on Upgrade. */
export interface DisplayItem {
  id: string;
  name: string;
  category: string;
  /** Kit scale the piece suits, e.g. "1/144". Null = non-scale or not recorded. */
  scale: string | null;
  manufacturer: string | null;
  quantity_on_hand: number;
  notes: string | null;
}

export interface DisplayItemCreate {
  name: string;
  category: string;
  scale?: string | null;
  manufacturer?: string | null;
  quantity_on_hand?: number;
  notes?: string | null;
}

export interface UpgradeApplication {
  id: string;
  upgrade_id: string;
  kit_id: string;
  quantity_used: number;
  applied_at: string;
}

/** An application with its upgrade embedded — what the kit editor lists (#61). */
export interface UpgradeApplicationDetail extends UpgradeApplication {
  upgrade: Upgrade;
}

export interface CatalogSearchResult {
  item_type: CatalogItemType;
  id: string;
  name: string;
  category: string | null;
  manufacturer: string | null;
  /** Display items only. */
  scale: string | null;
  quantity_on_hand: number;
}

/** Result of a signed stock adjustment — `POST /catalog/{id}/adjust` (#55).
 *
 * `item_type` comes back because the caller doesn't state it: the service resolves
 * the id across every catalog table the same way the search does. */
export interface StockAdjustment {
  item_type: CatalogItemType;
  id: string;
  name: string;
  quantity_on_hand: number;
  reason: string | null;
}

export const PACKING_QUALITIES = ["excellent", "good", "average", "below_average", "poor"] as const;
export type PackingQuality = (typeof PACKING_QUALITIES)[number];

export const SHIPPING_SPEEDS = ["very_fast", "fast", "average", "slow", "very_slow"] as const;
export type ShippingSpeed = (typeof SHIPPING_SPEEDS)[number];

export const WOULD_ORDER_AGAIN = ["yes", "maybe", "no"] as const;
export type WouldOrderAgain = (typeof WOULD_ORDER_AGAIN)[number];

export interface Retailer {
  id: string;
  name: string;
  url: string | null;
  rating: number | null;
  packing_quality: PackingQuality | null;
  shipping_speed: ShippingSpeed | null;
  would_order_again: WouldOrderAgain | null;
  notes: string | null;
}

export interface RetailerCreate {
  name: string;
  url?: string | null;
  rating?: number | null;
  packing_quality?: PackingQuality | null;
  shipping_speed?: ShippingSpeed | null;
  would_order_again?: WouldOrderAgain | null;
  notes?: string | null;
}

export interface OrderItem {
  id: string;
  item_type: ItemType;
  catalog_ref_id: string | null;
  quantity: number;
  unit_price_minor: number;
  currency_code: string;
  /** Entry-time conversion snapshot, in `converted_currency_code`. Never recomputed. */
  converted_price_minor: number | null;
  converted_currency_code: string | null;
  spawned_kit_ids: string[];
  /** The spawned kits themselves. Hydrate the editor from these, never from a
   * separately cached kit list — that second cache going stale is how a warm page
   * reverted a kit somebody had just changed (#65). */
  kits: Kit[];
}

export interface Order {
  id: string;
  retailer_id: string;
  order_date: string;
  /** Retailer's reference for support contact — only unique per retailer. */
  order_number: string | null;
  delivery_service: string | null;
  tracking_number: string | null;
  tracking_url: string | null;
  shipping_cost_minor: number | null;
  currency_code: string;
  /** Null = not marked shipped. Never carries stock semantics (#95). */
  shipped_at: string | null;
  received_at: string | null;
  items: OrderItem[];
}

export interface OrderKitDetails {
  name: string;
  grade: string;
  scale?: string | null;
  kit_number?: string | null;
  status?: KitStatus;
}

export interface NewCatalogItem {
  name: string;
  /** Required for tools, consumables and display items; unused by upgrades. */
  category?: string | null;
  /** Required for upgrades; optional on display items. */
  manufacturer?: string | null;
  /** Display items only. */
  scale?: string | null;
  low_stock_threshold?: number | null;
}

export interface OrderItemCreate {
  item_type: ItemType;
  quantity: number;
  unit_price_minor: number;
  currency_code: string;
  /** Omit the code and the instance's reference currency is stamped in server-side.
   *  On an update, omitting the amount keeps the stored snapshot; an explicit null
   *  clears it. */
  converted_price_minor?: number | null;
  converted_currency_code?: string | null;
  kit?: OrderKitDetails | null;
  catalog_ref_id?: string | null;
  new_item?: NewCatalogItem | null;
}

export interface OrderCreate {
  retailer_id: string;
  order_date: string;
  order_number?: string | null;
  delivery_service?: string | null;
  tracking_number?: string | null;
  tracking_url?: string | null;
  shipping_cost_minor?: number | null;
  currency_code: string;
  received?: boolean;
  /** When the delivery actually arrived, for orders entered after the fact (#93).
   *  Offset-aware ISO 8601; requires `received: true`; omitted = now. */
  received_at?: string;
  /** When the retailer shipped it (#95). Needs no flag — a non-null instant is
   *  the assertion. On its own it lands spawned kits in_transit. */
  shipped_at?: string;
  items: OrderItemCreate[];
}

/** A line in an order edit: with id = update, without = new; omitted = removed. */
export interface OrderItemUpsert extends OrderItemCreate {
  id?: string;
}

export interface OrderUpdate {
  retailer_id?: string;
  order_date?: string;
  order_number?: string | null;
  delivery_service?: string | null;
  tracking_number?: string | null;
  tracking_url?: string | null;
  shipping_cost_minor?: number | null;
  currency_code?: string;
  /** Correction only: adjusts a receipt date already set (409 on a pending
   *  order — receiving goes through `receiveOrder`). Cannot be nulled. */
  received_at?: string;
  /** Correction only, the same shape (#95): 409 on a never-shipped order —
   *  shipping goes through `shipOrder`. Cannot be nulled. */
  shipped_at?: string;
  items?: OrderItemUpsert[];
}

/** Optional body for the receive call: omit entirely for "it arrived now". */
export interface OrderReceive {
  received_at?: string;
}

/** Optional body for the ship call: omit entirely for "it shipped now". */
export interface OrderShip {
  shipped_at?: string;
}

export interface ToolUpdate {
  name?: string;
  category?: string;
  quantity_on_hand?: number;
  unit_cost_reference_minor?: number | null;
  unit_cost_reference_currency?: string | null;
  condition_notes?: string | null;
}

export interface ConsumableUpdate {
  name?: string;
  category?: string;
  quantity_on_hand?: number;
  low_stock_threshold?: number | null;
}

export interface UpgradeUpdate {
  name?: string;
  manufacturer?: string;
  quantity_on_hand?: number;
}

export interface DisplayItemUpdate {
  name?: string;
  category?: string;
  scale?: string | null;
  manufacturer?: string | null;
  quantity_on_hand?: number;
  notes?: string | null;
}

export interface RetailerUpdate {
  name?: string;
  url?: string | null;
  rating?: number | null;
  packing_quality?: PackingQuality | null;
  shipping_speed?: ShippingSpeed | null;
  would_order_again?: WouldOrderAgain | null;
  notes?: string | null;
}

// --- import / export -----------------------------------------------------------
// Mirrors app/schemas/portability.py. The runtime lists exist so the catalogue
// tests can drive every member through its label lookup (the KIT_STATUSES
// precedent); ROW_ACTIONS is also the preview's display order.

export const IMPORT_MODES = ["merge", "add_only", "replace_all"] as const;

export type ImportMode = (typeof IMPORT_MODES)[number];

export const ROW_ACTIONS = ["create", "update", "unchanged", "skip", "error"] as const;

export type RowAction = (typeof ROW_ACTIONS)[number];

export interface FieldChange {
  field: string;
  before: string;
  after: string;
}

/** One import-preview finding on the #25 envelope shape (#26): a stable
 * `<domain>.<condition>` code, the structured params a translation may
 * interpolate, and the English fallback `detail`. Rendered through
 * `resolveDiagnostic` — catalogue for a known code, `detail` otherwise. */
export interface Diagnostic {
  code: string;
  params: Record<string, unknown>;
  detail: string;
}

export interface PlannedRow {
  row_number: number;
  action: RowAction;
  label: string;
  /** uuid of the matched row; the number 1 for the instance_settings singleton. */
  matched_id: string | number | null;
  /** Canonical matching identifier ("id", "name", "retailer_order_number", ...)
   * — mapped to a display phrase by `matchedByLabel`, never translated on the
   * wire. */
  matched_by: string | null;
  changes: FieldChange[];
  messages: Diagnostic[];
  /** Each problem stands alone; non-empty implies action === "error". */
  errors: Diagnostic[];
}

export interface TablePlan {
  table: string;
  counts: Record<RowAction, number>;
  rows: PlannedRow[];
}

export interface DerivedEffects {
  kits_spawned: number;
  /** Kits a reduced order-line quantity gives up. Destructive, and named by no row. */
  kits_removed: number;
  /** Pre-existing kits moved by an order this upload ships/receives (#119). */
  kits_advanced: number;
  stock_changes: number;
  stock_note: Diagnostic | null;
  rows_deleted: Record<string, number>;
}

export interface ManifestInfo {
  format: string | null;
  export_version: number | null;
  schema_version: string | null;
  app_version: string | null;
  exported_at: string | null;
}

export interface ImportPlan {
  plan_hash: string;
  mode: ImportMode;
  source: string;
  manifest: ManifestInfo | null;
  tables: TablePlan[];
  derived: DerivedEffects;
  warnings: Diagnostic[];
  blocking_errors: Diagnostic[];
}

export interface ImportResult {
  mode: ImportMode;
  source: string;
  created: number;
  updated: number;
  skipped: number;
  kits_spawned: number;
  kits_removed: number;
  kits_advanced: number;
  rows_deleted: Record<string, number>;
  warnings: Diagnostic[];
}

/** Instance-level settings the UI needs before it can render a form. */
export interface Meta {
  version: string;
  /** Default currency for new entries; each snapshot stores its own code. */
  reference_currency: string;
  /** The catalogue tags a PATCH /settings accepts for interface_language (#27).
   *  The browser's own manifest is held to the same set by the parity test. */
  supported_interface_languages: string[];
}

/** Intl.DateTimeFormat dateStyle values, plus "locale" = the locale's default.
 *  Runtime list so the catalogue tests can drive every member's option label. */
export const DATE_STYLES = ["locale", "short", "medium", "long", "full"] as const;

export type DateStyle = (typeof DATE_STYLES)[number];

/** Intl.DateTimeFormat hourCycle values in real-world use; "locale" defers. */
export const HOUR_CYCLES = ["locale", "h12", "h23"] as const;

export type HourCycle = (typeof HOUR_CYCLES)[number];

/** The instance-settings singleton (§6.1, #23) — one row, shared by every
 *  browser and agent. Mirrors backend/app/schemas/settings.py. */
export interface InstanceSettings {
  interface_language: string;
  formatting_locale: string;
  time_zone: string;
  date_style: DateStyle;
  hour_cycle: HourCycle;
  reference_currency: string;
  updated_at: string;
}

export interface InstanceSettingsUpdate {
  interface_language?: string;
  formatting_locale?: string;
  time_zone?: string;
  date_style?: DateStyle;
  hour_cycle?: HourCycle;
  reference_currency?: string;
}

/** `GET /auth/session` (§5.5 family 2, #188) — the SPA's bootstrap: whether the
 *  instance is claimed, whether this browser is the owner, the language/locale
 *  the setup and login screens render in, and (owner only) the CSRF token that
 *  travels back in `X-CSRF-Token` on every unsafe request. No version, no
 *  collection data. Mirrors backend/app/schemas/auth.py. */
export interface AuthSession {
  state: "unclaimed" | "anonymous" | "owner";
  interface_language: string;
  formatting_locale: string;
  csrf_token: string | null;
}
