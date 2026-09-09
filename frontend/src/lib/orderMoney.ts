/** What an order row says about money (§6, rule 4): the order's own total, the
 *  lines' entry-time conversion snapshots summed beneath it, and the shipping
 *  line that closes the expanded lines box (§13.4). Pure over the API's `Order`,
 *  so the rules are tested here and the page only renders. */

import type { Order } from "../api/types";
import { formatMoney } from "./format";

/** The order's total per currency — lines by their own currency, shipping in
 *  the order's — joined, or a dash for an order without lines. */
export function orderTotal(order: Order): string {
  const byCurrency = new Map<string, number>();
  for (const item of order.items) {
    byCurrency.set(
      item.currency_code,
      (byCurrency.get(item.currency_code) ?? 0) + item.quantity * item.unit_price_minor,
    );
  }
  if (order.shipping_cost_minor) {
    byCurrency.set(
      order.currency_code,
      (byCurrency.get(order.currency_code) ?? 0) + order.shipping_cost_minor,
    );
  }
  return (
    [...byCurrency].map(([currency, minor]) => formatMoney(minor, currency)).join(" + ") || "—"
  );
}

/** The lines' entry-time conversion snapshots summed: shown under the order's own
 *  total when every line carries one in a single currency, and at least one line
 *  was bought in another — the header's currency is the shipping's and says
 *  nothing about the lines the total shows (Codex #236 P3-3). Shipping has no
 *  snapshot, so it is the lines, and the sub-line says nothing when a line lacks
 *  one rather than showing a partial sum. */
export function convertedTotal(order: Order): string | null {
  if (order.items.length === 0) return null;
  const codes = new Set(order.items.map((item) => item.converted_currency_code));
  if (codes.size !== 1) return null;
  const [code] = codes;
  if (!code) return null;
  // Every line already in the snapshot currency: the total above says the same.
  if (order.items.every((item) => item.currency_code === code)) return null;
  let minor = 0;
  for (const item of order.items) {
    if (item.converted_price_minor === null) return null;
    minor += item.quantity * item.converted_price_minor;
  }
  return formatMoney(minor, code);
}

export type ShippingLine = {
  /** The delivery service, when one was recorded. */
  service: string | null;
  /** The cost in the order's currency, formatted; null when none was recorded. */
  amount: string | null;
};

/** The shipping line of the expanded lines box, or null when the order
 *  recorded neither a cost nor a service. A recorded zero — free post — is a
 *  line with its amount; an unrecorded cost is never read as one (Codex #236
 *  P3-4: a truthiness test collapsed the zero into absence). */
export function shippingLine(order: Order): ShippingLine | null {
  if (order.shipping_cost_minor === null && order.delivery_service === null) return null;
  return {
    service: order.delivery_service,
    amount:
      order.shipping_cost_minor === null
        ? null
        : formatMoney(order.shipping_cost_minor, order.currency_code),
  };
}
