/** Home's pure rules (design §13.2, #233): which orders sit in which *In the
 *  mail* column, what a card says about an order's lines, and the day counter
 *  on a bench card. Pure over the API's shapes so the rules are tested here and
 *  the page only renders. The counts and the stage themselves are the
 *  server's (`GET /summary`, `Order.stage`) — nothing here decides a total. */

import type { ItemType, Kit, Order, OrderItem, OrderStage } from "../api/types";

/** The three columns, in pipeline order — the order stages that are not
 *  `received`. */
export const MAIL_STAGES = ["pre_ordered", "ordered", "in_transit"] as const satisfies readonly OrderStage[];
export type MailStage = (typeof MAIL_STAGES)[number];

/** Rows in the Backlog and Recently completed strips — the six most recent by
 *  the status clock (§13.2); the heading carries the true count. */
export const STRIP_LIMIT = 6;

/** Cards per mail column before "view all" takes over — the artboard's three. */
export const MAIL_CAP = 3;

/** The pending orders by column, in the order they arrived (the server's
 *  `recent` sort). A received order has no column and is dropped. */
export function bucketMail(orders: readonly Order[]): Record<MailStage, Order[]> {
  const buckets: Record<MailStage, Order[]> = { pre_ordered: [], ordered: [], in_transit: [] };
  for (const order of orders) {
    if (order.stage !== "received") buckets[order.stage].push(order);
  }
  return buckets;
}

/** "day N" on a bench card: day 1 at the start, and one more for every full
 *  24 hours since — elapsed periods, not calendar days, so the number can
 *  differ around local midnight and a DST change (the Kits page's elapsed
 *  columns measure the same way). A start in the future (a clock skew, a
 *  backdate typo) reads as day 1 rather than a negative. */
export function buildDay(startedAt: string, now: Date): number {
  const elapsed = Math.floor((now.getTime() - new Date(startedAt).getTime()) / 86_400_000);
  return Math.max(0, elapsed) + 1;
}

/** The date a Recently completed row shows: the build's own completion date
 *  when it has one (#94), else the moment it entered `complete`. */
export function completedOn(kit: Kit): string {
  return kit.build_completed_at ?? kit.status_updated_at;
}

export type LineSummary = {
  /** The kit's name, or the catalog item's when its list has loaded — null
   *  until then (the page falls back to the item type). */
  label: string | null;
  quantity: number;
  /** The wire type — what the page names the line by while a catalog name is
   *  still loading. */
  itemType: ItemType;
  /** Tagged *pre-order*: a pre-ordered line on an order that is not, as a
   *  whole, a pre-order (§13.2 — a mixed order sits under Ordered with the tag
   *  on the line). In the Pre-ordered column every line is one, so no tag. */
  preOrder: boolean;
};

export type MailCardLines = {
  headline: LineSummary | null;
  rest:
    | { kind: "none" }
    | { kind: "one"; line: LineSummary }
    | { kind: "many"; count: number };
};

function linePreOrder(item: OrderItem): boolean {
  return item.kits.length > 0 && item.kits.every((kit) => kit.status === "pre_ordered");
}

export function summarizeLine(
  item: OrderItem,
  order: Order,
  nameOf: (catalogId: string) => string | undefined,
): LineSummary {
  const catalog = item.item_type !== "kit";
  const label: string | null = catalog
    ? item.catalog_ref_id
      ? (nameOf(item.catalog_ref_id) ?? null)
      : null
    : (item.kits[0]?.name ?? null);
  return {
    label,
    quantity: item.quantity,
    itemType: item.item_type,
    preOrder: order.stage !== "pre_ordered" && linePreOrder(item),
  };
}

/** What a card says about the lines: the first line, then either nothing, the
 *  one other line by name, or how many more there are (the artboard: "and RG
 *  Gundam Epyon", "and 2 more lines"). */
export function mailCardLines(
  order: Order,
  nameOf: (catalogId: string) => string | undefined,
): MailCardLines {
  const [first, ...others] = order.items;
  const headline = first ? summarizeLine(first, order, nameOf) : null;
  if (others.length === 0) return { headline, rest: { kind: "none" } };
  if (others.length === 1) {
    return { headline, rest: { kind: "one", line: summarizeLine(others[0], order, nameOf) } };
  }
  return { headline, rest: { kind: "many", count: others.length } };
}

/** Whether any card would name a catalog line — the four catalog lists are
 *  fetched only then, so a kit-only mailbox costs the start page nothing. */
export function needsCatalogNames(orders: readonly Order[]): boolean {
  return orders.some((order) => {
    const named = order.items.length <= 2 ? order.items : order.items.slice(0, 1);
    return named.some((item) => item.item_type !== "kit");
  });
}
