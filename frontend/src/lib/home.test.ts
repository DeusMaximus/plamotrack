/** Home's pure rules (#233): the mail columns, the card's line summary, the
 *  day counter. Value axis on the lines: none, one, two, three; kit and
 *  catalog; a catalog name loaded or not; pre-ordered lines on a pre-order, a
 *  mixed order and an ordered one. And the dates a build prints, shared with
 *  the server's sorts (#247). */
import { describe, expect, it } from "vitest";

import type { Kit, Order, OrderItem, OrderStage } from "../api/types";
import {
  MAIL_STAGES,
  bucketMail,
  buildDay,
  completedOn,
  mailCardLines,
  needsCatalogNames,
  summarizeLine,
  trackingOf,
} from "./home";
import sortCases from "./__fixtures__/kit-sort-cases.json";

function kit(name: string, status: Kit["status"] = "ordered"): Kit {
  return {
    id: `kit-${name}`,
    name,
    grade: "HG",
    scale: "1/144",
    kit_number: null,
    series: null,
    status,
    status_updated_at: "2026-08-01T00:00:00Z",
    rating: null,
    build_started_at: null,
    build_completed_at: null,
    build_notes: null,
    order_item_id: null,
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
  };
}

function kitLine(name: string, status: Kit["status"] = "ordered", quantity = 1): OrderItem {
  return {
    id: `line-${name}`,
    item_type: "kit",
    catalog_ref_id: null,
    quantity,
    unit_price_minor: 2800,
    currency_code: "JPY",
    converted_price_minor: null,
    converted_currency_code: null,
    spawned_kit_ids: Array.from({ length: quantity }, (_, i) => `kit-${name}-${i}`),
    kits: Array.from({ length: quantity }, () => kit(name, status)),
  };
}

function catalogLine(refId: string, quantity = 1): OrderItem {
  return {
    id: `line-${refId}`,
    item_type: "display",
    catalog_ref_id: refId,
    quantity,
    unit_price_minor: 1200,
    currency_code: "JPY",
    converted_price_minor: null,
    converted_currency_code: null,
    spawned_kit_ids: [],
    kits: [],
  };
}

function order(stage: OrderStage, items: OrderItem[], id = `order-${stage}`): Order {
  return {
    id,
    retailer_id: "shop",
    order_date: "2026-08-20",
    order_number: null,
    delivery_service: null,
    tracking_number: null,
    tracking_url: null,
    shipping_cost_minor: null,
    currency_code: "JPY",
    shipped_at: stage === "in_transit" ? "2026-08-25T00:00:00Z" : null,
    received_at: stage === "received" ? "2026-08-30T00:00:00Z" : null,
    items,
    stage,
  };
}

const names = new Map([["base-1", "Action Base 1 (Gray)"]]);
const nameOf = (id: string) => names.get(id);

describe("bucketMail", () => {
  it("keeps the server's order within each column and drops received orders", () => {
    const a = order("ordered", [kitLine("A")], "a");
    const b = order("in_transit", [kitLine("B")], "b");
    const c = order("ordered", [kitLine("C")], "c");
    const d = order("received", [kitLine("D")], "d");
    const e = order("pre_ordered", [kitLine("E", "pre_ordered")], "e");
    const buckets = bucketMail([a, b, c, d, e]);
    expect(Object.keys(buckets)).toEqual([...MAIL_STAGES]);
    expect(buckets.ordered.map((o) => o.id)).toEqual(["a", "c"]);
    expect(buckets.in_transit.map((o) => o.id)).toEqual(["b"]);
    expect(buckets.pre_ordered.map((o) => o.id)).toEqual(["e"]);
  });

  it("has every column even when nothing is in the mail", () => {
    expect(bucketMail([])).toEqual({ pre_ordered: [], ordered: [], in_transit: [] });
  });
});

describe("buildDay", () => {
  const now = new Date("2026-09-08T10:00:00Z");
  it.each([
    ["2026-09-08T09:00:00Z", 1], // started today
    ["2026-09-07T11:00:00Z", 1], // under a full day ago
    ["2026-09-07T09:00:00Z", 2], // a full day
    ["2026-06-14T10:00:00Z", 87], // the artboard's 14 June → 8 September
    ["2026-09-09T10:00:00Z", 1], // a start in the future reads as day 1, never 0 or -1
  ])("%s → day %d", (started, day) => {
    expect(buildDay(started, now)).toBe(day);
  });
});

/** #247 — the date a build shows and the order the server lists it in are one
 *  rule, held by `__fixtures__/kit-sort-cases.json`, which
 *  backend/tests/test_kit_sorts.py seeds and asks the API about. Here: every
 *  case's printed date, and that every promised order is sorted by it. */
describe("kit dates, shared with the server (#247)", () => {
  const fixtureKit = (c: (typeof sortCases.kits)[number]): Kit => ({
    ...kit(c.name, c.status as Kit["status"]),
    created_at: c.created_at,
    status_updated_at: c.status_updated_at,
    build_started_at: c.build_started_at,
    build_completed_at: c.build_completed_at,
  });
  const byName = new Map(sortCases.kits.map((c) => [c.name, fixtureKit(c)]));

  it("reads a real fixture", () => {
    // An emptied fixture must fail, not parametrize into nothing.
    expect(sortCases.kits).toHaveLength(11);
    expect(sortCases.orders.length).toBeGreaterThanOrEqual(6);
  });

  it.each(sortCases.kits.map((c) => [c.name, c] as const))(
    "%s prints its own completion date, or none",
    (_name, c) => {
      expect(completedOn(fixtureKit(c))).toBe(c.completed_on);
    },
  );

  /** What each page prints for the `by` field: the date the list is promised
   *  to be sorted by. The start date is printed as stored (the bench, the
   *  Started column); the completion date through `completedOn`. */
  const printed: Record<string, (k: Kit) => string | null> = {
    completed_on: completedOn,
    started_on: (k) => k.build_started_at,
    created_at: (k) => k.created_at,
    status_updated_at: (k) => k.status_updated_at,
  };

  it.each(sortCases.orders.map((o) => [JSON.stringify(o.params), o] as const))(
    "%s is sorted by the date the page prints — newest first, undated last",
    (_params, o) => {
      const dateOf = printed[o.by];
      expect(dateOf, `no printed date for ${o.by}`).toBeDefined();
      const rows = o.names.map((n) => byName.get(n)!);
      for (let i = 1; i < rows.length; i++) {
        const [prev, next] = [dateOf(rows[i - 1]), dateOf(rows[i])];
        const where = `${o.names[i - 1]} before ${o.names[i]}`;
        if (next === null) continue; // undated: after every dated row, any order among them
        expect(prev, `${where}: a dated row after an undated one`).not.toBeNull();
        expect(Date.parse(prev!), where).toBeGreaterThanOrEqual(Date.parse(next));
      }
    },
  );
});

describe("mailCardLines", () => {
  it("names the first kit line and says nothing more for a one-line order", () => {
    expect(mailCardLines(order("ordered", [kitLine("HG Calibarn")]), nameOf)).toEqual({
      headline: { label: "HG Calibarn", quantity: 1, itemType: "kit", preOrder: false },
      rest: { kind: "none" },
    });
  });

  it("names the one other line, catalog names included, with its quantity", () => {
    const lines = mailCardLines(
      order("ordered", [kitLine("MG Nu"), catalogLine("base-1", 2)]),
      nameOf,
    );
    expect(lines.rest).toEqual({
      kind: "one",
      line: { label: "Action Base 1 (Gray)", quantity: 2, itemType: "display", preOrder: false },
    });
  });

  it("counts the rest past one more line", () => {
    const lines = mailCardLines(
      order("in_transit", [kitLine("A"), kitLine("B"), catalogLine("base-1")]),
      nameOf,
    );
    expect(lines.rest).toEqual({ kind: "many", count: 2 });
  });

  it("has no headline for an order without lines", () => {
    expect(mailCardLines(order("ordered", []), nameOf)).toEqual({
      headline: null,
      rest: { kind: "none" },
    });
  });

  it("leaves a catalog label null until its list has loaded", () => {
    const first = mailCardLines(order("ordered", [catalogLine("unknown")]), nameOf);
    expect(first.headline).toEqual({ label: null, quantity: 1, itemType: "display", preOrder: false });
  });

  it("tags a pre-ordered line on a mixed order only", () => {
    const pre = kitLine("RG Epyon", "pre_ordered");
    // Mixed: the order is `ordered`, the line is a pre-order → tagged.
    const mixed = order("ordered", [kitLine("HGUC Unicorn"), pre]);
    expect(mailCardLines(mixed, nameOf).rest).toEqual({
      kind: "one",
      line: { label: "RG Epyon", quantity: 1, itemType: "kit", preOrder: true },
    });
    // Wholly a pre-order: the column says it, the line does not.
    expect(summarizeLine(pre, order("pre_ordered", [pre]), nameOf).preOrder).toBe(false);
    // An ordered line is never tagged, and a mixed line (one kit of two moved
    // on by hand) is not "every kit pre-ordered".
    expect(summarizeLine(kitLine("Ord"), mixed, nameOf).preOrder).toBe(false);
    const half: OrderItem = { ...kitLine("Half", "pre_ordered", 2) };
    half.kits[1] = kit("Half", "backlog");
    expect(summarizeLine(half, mixed, nameOf).preOrder).toBe(false);
  });
});

describe("trackingOf", () => {
  const shipped = (fields: Partial<Order>) => ({ ...order("in_transit", [kitLine("A")]), ...fields });
  it.each([
    [null, null, null],
    ["", null, null],
    ["   ", null, null],
    ["AU237", null, { number: "AU237", url: null }],
    [null, "https://t.example/1", { number: null, url: "https://t.example/1" }],
    ["", "https://t.example/1", { number: null, url: "https://t.example/1" }],
    ["   ", "https://t.example/1", { number: null, url: "https://t.example/1" }],
    [" AU237 ", "https://t.example/1", { number: "AU237", url: "https://t.example/1" }],
    ["AU237", "   ", { number: "AU237", url: null }],
  ])("number %j, url %j → %j", (number, url, expected) => {
    expect(trackingOf(shipped({ tracking_number: number, tracking_url: url }), "in_transit")).toEqual(
      expected,
    );
  });

  it("shows nothing before the order ships, whatever the fields hold", () => {
    const pending = { ...order("ordered", [kitLine("A")]), tracking_number: "AU237", tracking_url: "https://t.example/1" };
    expect(trackingOf(pending, "ordered")).toBeNull();
    expect(trackingOf(pending, "pre_ordered")).toBeNull();
  });
});

describe("needsCatalogNames", () => {
  it("is false for kit-only mail and for catalog lines that are only counted", () => {
    expect(needsCatalogNames([order("ordered", [kitLine("A")])])).toBe(false);
    expect(
      needsCatalogNames([order("ordered", [kitLine("A"), kitLine("B"), catalogLine("base-1")])]),
    ).toBe(false);
  });

  it("is true when a card would name a catalog line — first, or the one other", () => {
    expect(needsCatalogNames([order("ordered", [catalogLine("base-1")])])).toBe(true);
    expect(needsCatalogNames([order("ordered", [kitLine("A"), catalogLine("base-1")])])).toBe(true);
  });
});
