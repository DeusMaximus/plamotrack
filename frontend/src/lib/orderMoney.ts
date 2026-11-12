/** What an order row says about money (§6, rule 4): what was paid, the lines'
 *  entry-time conversion snapshots summed beneath it, and the shipping,
 *  adjustment and paid lines that close the expanded lines box (§13.4, #350).
 *  Pure over the API's `Order`, so the rules are tested here and the page only
 *  renders. */

import type { Order } from "../api/types";
import { formatMoney } from "./format";

/** What was paid for the order, per currency, joined — or a dash for an order
 *  with nothing to total. The server's figures (`order.totals`, #350): lines by
 *  their own currency, shipping and adjustments in the order's, so the page
 *  adds nothing up and cannot disagree with what an agent reads. Without
 *  adjustments this is the lines and shipping, as it always was. */
export function orderTotal(order: Order): string {
  return (
    order.totals.map((total) => formatMoney(total.paid_minor, total.currency_code)).join(" + ") ||
    "—"
  );
}

export type AdjustmentLine = {
  id: string;
  label: string;
  /** The deduction in the order's currency, formatted as the negative it is. */
  amount: string;
};

/** The adjustment rows of the expanded lines box (#350): what came off, in the
 *  order they were entered, each in the order's own currency. */
export function adjustmentLines(order: Order): AdjustmentLine[] {
  return order.adjustments.map((adjustment) => ({
    id: adjustment.id,
    label: adjustment.label,
    amount: formatMoney(-adjustment.amount_minor, order.currency_code),
  }));
}

/** The line that closes the money in the expanded box: what was paid, shown
 *  only on an order with adjustments. Without any, the lines and shipping above
 *  it already say so, and a row restating the list's own total is noise. */
export function paidLine(order: Order): string | null {
  return order.adjustments.length === 0 ? null : orderTotal(order);
}

/** The lines' entry-time conversion snapshots summed: shown under the order's own
 *  total when every line carries one in a single currency, unless the sub-line
 *  would merely restate the total above — every line bought in that currency
 *  *and* the snapshots summing to the lines' own subtotal. The header's currency
 *  is the shipping's and decides nothing (Codex #236 P3-3); a same-currency
 *  snapshot whose amount differs is a recorded fact and shows (round 2, P3-8).
 *  Shipping has no snapshot, so it is the lines, and the sub-line says nothing
 *  when a line lacks one rather than showing a partial sum. */
export function convertedTotal(order: Order): string | null {
  if (order.items.length === 0) return null;
  const codes = new Set(order.items.map((item) => item.converted_currency_code));
  if (codes.size !== 1) return null;
  const [code] = codes;
  if (!code) return null;
  let minor = 0;
  let subtotal = 0;
  for (const item of order.items) {
    if (item.converted_price_minor === null) return null;
    minor += item.quantity * item.converted_price_minor;
    subtotal += item.quantity * item.unit_price_minor;
  }
  const restatesTheLines =
    order.items.every((item) => item.currency_code === code) && minor === subtotal;
  return restatesTheLines ? null : formatMoney(minor, code);
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
