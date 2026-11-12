/** Which caches a write dirties (#233). The two shared dialogs and every page's
 *  delete handler call these rather than naming keys, so Home's summary counts
 *  are refetched by the same save that moves a kit or ships an order — a list
 *  page and Home read different queries over the same rows, and a key missing
 *  from one caller is a count that lags until a reload. */

import type { QueryClient } from "@tanstack/react-query";

/** A kit changed: the kit lists (every filter/sort/limit under the `kits`
 *  prefix), the per-status counts — and the orders, because an order's
 *  `stage` and the kit names on its lines are derived from its kits (§13.2):
 *  moving a spawned kit to `pre_ordered` moves its order's card to another
 *  column, and only a refetch shows it (Codex #237 P2). */
export const KIT_VIEW_KEYS = ["kits", "orders", "summary"] as const;

/** An order changed: the orders, the kits it spawned or advanced, the catalog
 *  stock a receipt applied, and the counts. */
export const ORDER_VIEW_KEYS = [
  "orders",
  "kits",
  "tools",
  "consumables",
  "upgrades",
  "display-items",
  "summary",
] as const;

async function invalidate(queryClient: QueryClient, keys: readonly string[]): Promise<void> {
  await Promise.all(keys.map((key) => queryClient.invalidateQueries({ queryKey: [key] })));
}

export function invalidateKitViews(queryClient: QueryClient): Promise<void> {
  return invalidate(queryClient, KIT_VIEW_KEYS);
}

export function invalidateOrderViews(queryClient: QueryClient): Promise<void> {
  return invalidate(queryClient, ORDER_VIEW_KEYS);
}
