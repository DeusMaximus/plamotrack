/** What a list page's filters and search keep (design §13.4): the whole list is
 *  loaded and narrowed in the browser. Pure, and in one place, because two
 *  things read them on a phone (§13.7) — the page, for the rows it shows, and
 *  the filter sheet, for the "Show 5 kits" on its button before anything is
 *  applied. One function each, so the button cannot promise a list the page
 *  then does not show. */

import type { Kit, KitStatus, Order, OrderStage } from "../api/types";

export type KitFilters = { status: KitStatus | ""; series: string; search: string };

export function filterKits(kits: readonly Kit[], { status, series, search }: KitFilters): Kit[] {
  let rows = [...kits];
  if (status) rows = rows.filter((kit) => kit.status === status);
  if (series) rows = rows.filter((kit) => kit.series === series);
  const needle = search.trim().toLowerCase();
  if (needle) {
    rows = rows.filter(
      (kit) =>
        kit.name.toLowerCase().includes(needle) ||
        (kit.kit_number ?? "").toLowerCase().includes(needle),
    );
  }
  return rows;
}

export type OrderFilters = { stage: OrderStage | ""; retailer: string; search: string };

/** `retailerName` is the page's id → name map: the search reads the retailer's
 *  name, which the order row does not carry. */
export function filterOrders(
  orders: readonly Order[],
  { stage, retailer, search }: OrderFilters,
  retailerName: ReadonlyMap<string, string>,
): Order[] {
  let rows = [...orders];
  if (stage) rows = rows.filter((order) => order.stage === stage);
  if (retailer) rows = rows.filter((order) => order.retailer_id === retailer);
  const needle = search.trim().toLowerCase();
  if (needle) {
    rows = rows.filter((order) =>
      [retailerName.get(order.retailer_id), order.order_number, order.tracking_number]
        .filter((value): value is string => Boolean(value))
        .some((value) => value.toLowerCase().includes(needle)),
    );
  }
  return rows;
}
