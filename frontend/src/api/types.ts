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

export type ItemType = "kit" | "tool" | "consumable" | "upgrade";
export type CatalogItemType = Exclude<ItemType, "kit">;

export interface Kit {
  id: string;
  name: string;
  grade: string;
  scale: string | null;
  kit_number: string | null;
  status: KitStatus;
  status_updated_at: string;
  rating: number | null;
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
  status?: KitStatus;
  build_notes?: string | null;
}

export interface KitUpdate {
  name?: string;
  grade?: string;
  scale?: string | null;
  kit_number?: string | null;
  status?: KitStatus;
  rating?: number | null;
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

export interface UpgradeApplication {
  id: string;
  upgrade_id: string;
  kit_id: string;
  quantity_used: number;
  applied_at: string;
}

export interface CatalogSearchResult {
  item_type: CatalogItemType;
  id: string;
  name: string;
  category: string | null;
  manufacturer: string | null;
  quantity_on_hand: number;
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
  category?: string | null;
  manufacturer?: string | null;
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
  items?: OrderItemUpsert[];
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
// Mirrors app/schemas/portability.py.

export type ImportMode = "merge" | "add_only" | "replace_all";

export type RowAction = "create" | "update" | "unchanged" | "skip" | "error";

export interface FieldChange {
  field: string;
  before: string;
  after: string;
}

export interface PlannedRow {
  row_number: number;
  action: RowAction;
  label: string;
  matched_id: string | null;
  matched_by: string | null;
  changes: FieldChange[];
  messages: string[];
  error: string | null;
}

export interface TablePlan {
  table: string;
  counts: Record<RowAction, number>;
  rows: PlannedRow[];
}

export interface DerivedEffects {
  kits_spawned: number;
  stock_changes: number;
  stock_note: string;
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
  warnings: string[];
  blocking_errors: string[];
}

export interface ImportResult {
  mode: ImportMode;
  source: string;
  created: number;
  updated: number;
  skipped: number;
  kits_spawned: number;
  rows_deleted: Record<string, number>;
  warnings: string[];
}

/** Instance-level settings the UI needs before it can render a form. */
export interface Meta {
  version: string;
  /** Default currency for new entries; each snapshot stores its own code. */
  reference_currency: string;
}
