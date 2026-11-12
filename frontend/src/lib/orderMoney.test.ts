/** The Orders row's money (§6, rule 4, design §13.4). Value axis for the
 *  converted sub-line: no lines, a line without a snapshot, snapshots in two
 *  currencies, a snapshot that merely restates the line, quantities above one,
 *  a zero snapshot — and the header currency, which says nothing about the
 *  lines (Codex #236 P3-3). For shipping: absent, recorded zero, a service
 *  without a cost, a cost without a service (P3-4). */

import { describe, expect, it } from "vitest";

import type { Order, OrderItem, OrderTotal } from "../api/types";
import { formatMoney } from "./format";
import {
  adjustmentLines,
  convertedTotal,
  orderTotal,
  paidLine,
  shippingLine,
} from "./orderMoney";

function line(
  currency: string,
  unit: number,
  snapshot: [number, string] | null,
  quantity = 1,
): OrderItem {
  return {
    currency_code: currency,
    unit_price_minor: unit,
    quantity,
    converted_price_minor: snapshot?.[0] ?? null,
    converted_currency_code: snapshot?.[1] ?? null,
  } as OrderItem;
}

function order(
  currency: string,
  items: OrderItem[],
  extra: Partial<Pick<Order, "shipping_cost_minor" | "delivery_service">> = {},
): Order {
  return {
    currency_code: currency,
    items,
    shipping_cost_minor: null,
    delivery_service: null,
    ...extra,
  } as Order;
}

/** One currency's share as the server derives it (`order.totals`). */
function total(currency: string, items: number, shipping = 0, adjustments = 0): OrderTotal {
  return {
    currency_code: currency,
    items_minor: items,
    shipping_minor: shipping,
    adjustments_minor: adjustments,
    paid_minor: items + shipping - adjustments,
  };
}

function totalled(
  currency: string,
  totals: OrderTotal[],
  adjustments: [label: string, amount: number][] = [],
): Order {
  return {
    currency_code: currency,
    totals,
    adjustments: adjustments.map(([label, amount_minor], index) => ({
      id: `adjustment-${index}`,
      label,
      amount_minor,
    })),
  } as Order;
}

describe("orderTotal", () => {
  it("is what was paid, per currency, in the order the server gives them", () => {
    const jpy = formatMoney(1000, "JPY"); // "JPY 1,000", with the formatter's own space
    expect(orderTotal(totalled("AUD", [total("JPY", 1000), total("AUD", 1000, 1200)]))).toBe(
      `${jpy} + $22.00`,
    );
  });

  it("is a dash when there is nothing to total", () => {
    expect(orderTotal(totalled("AUD", []))).toBe("—");
  });

  it("is the paid figure, never the shelf price, on an order with adjustments", () => {
    // The issue's own receipt (#350): $51.25 of kits, a $33.88 gift card.
    const paid = totalled("AUD", [total("AUD", 5125, 0, 3388)], [["Amazon gift card", 3388]]);
    expect(orderTotal(paid)).toBe("$17.37");
    // Paid in full by the card: a recorded zero is a total, not an absence.
    expect(orderTotal(totalled("AUD", [total("AUD", 5125, 0, 5125)], [["Gift card", 5125]]))).toBe(
      "$0.00",
    );
  });
});

describe("adjustmentLines and paidLine", () => {
  it("lists what came off in entry order, as negatives in the order's currency", () => {
    const paid = totalled(
      "AUD",
      [total("JPY", 9000), total("AUD", 5125, 500, 3888)],
      [
        ["Promo", 500],
        ["Amazon gift card", 3388],
      ],
    );
    expect(adjustmentLines(paid)).toEqual([
      { id: "adjustment-0", label: "Promo", amount: formatMoney(-500, "AUD") },
      { id: "adjustment-1", label: "Amazon gift card", amount: formatMoney(-3388, "AUD") },
    ]);
    expect(adjustmentLines(paid)[1].amount).toMatch(/33\.88/);
    expect(adjustmentLines(paid)[1].amount).not.toBe(formatMoney(3388, "AUD"));
    expect(paidLine(paid)).toBe(`${formatMoney(9000, "JPY")} + $17.37`);
  });

  it("a yen order's adjustments are whole yen", () => {
    const paid = totalled("JPY", [total("JPY", 9000, 0, 1500)], [["Coupon", 1500]]);
    expect(adjustmentLines(paid)[0].amount).toBe(formatMoney(-1500, "JPY"));
    expect(paidLine(paid)).toBe(formatMoney(7500, "JPY"));
  });

  it("says nothing on an order without adjustments", () => {
    const plain = totalled("AUD", [total("AUD", 1000, 1200)]);
    expect(adjustmentLines(plain)).toEqual([]);
    expect(paidLine(plain)).toBeNull();
  });
});

describe("convertedTotal", () => {
  it("is the stored snapshots summed, quantities included", () => {
    expect(convertedTotal(order("JPY", [line("JPY", 1000, [1234, "AUD"])]))).toBe("$12.34");
    expect(
      convertedTotal(
        order("JPY", [line("JPY", 1000, [1234, "AUD"], 2), line("JPY", 100, [100, "AUD"])]),
      ),
    ).toBe("$25.68");
  });

  it("shows a stored conversion whatever the header currency says", () => {
    // The header is the shipping/default currency; the line is what was converted.
    expect(convertedTotal(order("AUD", [line("JPY", 1000, [1234, "AUD"])]))).toBe("$12.34");
  });

  it("shows a same-currency snapshot whose amount differs from the line", () => {
    // A recorded fact (§6): the currencies match, the amounts do not (Codex #236 round 2, P3-8).
    expect(convertedTotal(order("AUD", [line("AUD", 1000, [1234, "AUD"])]))).toBe("$12.34");
    expect(
      convertedTotal(order("AUD", [line("AUD", 1000, [1000, "AUD"]), line("AUD", 50, [60, "AUD"])])),
    ).toBe("$10.60");
  });

  it("says nothing when the snapshots merely restate the lines", () => {
    expect(
      convertedTotal(order("AUD", [line("AUD", 1000, [1000, "AUD"]), line("AUD", 50, [50, "AUD"])])),
    ).toBeNull();
  });

  it("says nothing without lines, with a line lacking a snapshot, or with snapshots in two currencies", () => {
    expect(convertedTotal(order("JPY", []))).toBeNull();
    expect(
      convertedTotal(order("JPY", [line("JPY", 1000, [1234, "AUD"]), line("JPY", 500, null)])),
    ).toBeNull();
    expect(
      convertedTotal(
        order("JPY", [line("JPY", 1000, [1234, "AUD"]), line("JPY", 500, [300, "EUR"])]),
      ),
    ).toBeNull();
  });

  it("keeps a zero snapshot — a recorded value, not a missing one", () => {
    expect(convertedTotal(order("JPY", [line("JPY", 1000, [0, "AUD"])]))).toBe("$0.00");
  });
});

describe("shippingLine", () => {
  it("is absent when neither a cost nor a service was recorded", () => {
    expect(shippingLine(order("AUD", []))).toBeNull();
  });

  it("renders an explicitly free shipping with its service", () => {
    expect(
      shippingLine(order("AUD", [], { shipping_cost_minor: 0, delivery_service: "Free Post" })),
    ).toEqual({ service: "Free Post", amount: "$0.00" });
    expect(shippingLine(order("AUD", [], { shipping_cost_minor: 0 }))).toEqual({
      service: null,
      amount: "$0.00",
    });
  });

  it("never reads an unrecorded cost as a zero", () => {
    expect(shippingLine(order("AUD", [], { delivery_service: "Free Post" }))).toEqual({
      service: "Free Post",
      amount: null,
    });
    expect(shippingLine(order("AUD", [], { shipping_cost_minor: 1200 }))).toEqual({
      service: null,
      amount: "$12.00",
    });
  });
});
