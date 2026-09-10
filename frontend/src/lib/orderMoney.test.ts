/** The Orders row's money (§6, rule 4, design §13.4). Value axis for the
 *  converted sub-line: no lines, a line without a snapshot, snapshots in two
 *  currencies, a snapshot that merely restates the line, quantities above one,
 *  a zero snapshot — and the header currency, which says nothing about the
 *  lines (Codex #236 P3-3). For shipping: absent, recorded zero, a service
 *  without a cost, a cost without a service (P3-4). */

import { describe, expect, it } from "vitest";

import type { Order, OrderItem } from "../api/types";
import { formatMoney } from "./format";
import { convertedTotal, orderTotal, shippingLine } from "./orderMoney";

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

describe("orderTotal", () => {
  it("sums the lines by their own currency and adds shipping in the order's", () => {
    const jpy = formatMoney(1000, "JPY"); // "JPY 1,000", with the formatter's own space
    expect(orderTotal(order("AUD", [line("JPY", 1000, null), line("AUD", 500, null, 2)]))).toBe(
      `${jpy} + $10.00`,
    );
    expect(
      orderTotal(order("AUD", [line("JPY", 1000, null)], { shipping_cost_minor: 1200 })),
    ).toBe(`${jpy} + $12.00`);
  });

  it("is a dash without lines, and a zero shipping adds no term", () => {
    expect(orderTotal(order("AUD", []))).toBe("—");
    expect(orderTotal(order("AUD", [line("JPY", 1000, null)], { shipping_cost_minor: 0 }))).toBe(
      formatMoney(1000, "JPY"),
    );
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
