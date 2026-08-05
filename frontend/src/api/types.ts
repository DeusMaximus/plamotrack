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
  unit_cost_reference: string | null;
  condition_notes: string | null;
}

export interface ToolCreate {
  name: string;
  category: string;
  quantity_on_hand?: number;
  unit_cost_reference?: string | null;
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
  converted_price_aud_minor: number | null;
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
  converted_price_aud_minor?: number | null;
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
  unit_cost_reference?: string | null;
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
