/** The list pages' filters (design §13.4), read by the page for its rows and by
 *  the phone's filter sheet for the count on its button (§13.7) — so what is
 *  held here is that the two cannot disagree: one function, and every value a
 *  filter can hold. Empty means "no filter", never "match the empty string". */
import { describe, expect, it } from "vitest";

import type { Kit, Order } from "../api/types";
import { filterKits, filterOrders } from "./listFilters";

const kit = (name: string, fields: Partial<Kit> = {}): Kit =>
  ({ id: name, name, grade: "HG", status: "backlog", kit_number: null, series: null, ...fields }) as Kit;

const KITS = [
  kit("HG Zaku II", { series: "Mobile Suit Gundam", kit_number: "HGUC 241" }),
  kit("HG Zaku II", { series: "Mobile Suit Gundam", status: "building" }),
  kit("MG Sazabi Ver.Ka", { series: "Char's Counterattack", status: "complete" }),
  kit("SD Gundam", {}), // no series, no number
];
const names = (rows: Kit[]) => rows.map((row) => `${row.name}/${row.status}`);

describe("filterKits", () => {
  it("keeps everything when nothing is chosen", () => {
    expect(filterKits(KITS, { status: "", series: "", search: "" })).toEqual(KITS);
    expect(filterKits([], { status: "", series: "", search: "" })).toEqual([]);
  });

  it("does not mutate or alias the list it was given", () => {
    const rows = filterKits(KITS, { status: "", series: "", search: "" });
    expect(rows).not.toBe(KITS);
  });

  it("narrows by status, by series, and by both", () => {
    expect(names(filterKits(KITS, { status: "building", series: "", search: "" }))).toEqual(["HG Zaku II/building"]);
    expect(filterKits(KITS, { status: "", series: "Mobile Suit Gundam", search: "" })).toHaveLength(2);
    expect(names(filterKits(KITS, { status: "backlog", series: "Mobile Suit Gundam", search: "" }))).toEqual([
      "HG Zaku II/backlog",
    ]);
  });

  it("an empty series is no filter — it does not select the kits without one", () => {
    expect(filterKits(KITS, { status: "", series: "", search: "" })).toHaveLength(4);
  });

  it("a series nothing has matches nothing", () => {
    expect(filterKits(KITS, { status: "", series: "Gundam SEED", search: "" })).toEqual([]);
  });

  it.each([
    ["zaku", 2],
    ["  ZAKU  ", 2], // trimmed, case-insensitive
    ["hguc 241", 1], // the kit number
    ["   ", 4], // whitespace is no search
    ["Mobile Suit", 0], // the series is a filter, not something the search reads
  ])("searches the name and the kit number: %j → %i", (search, count) => {
    expect(filterKits(KITS, { status: "", series: "", search })).toHaveLength(count);
  });

  it("applies the search on top of the filters, as the sheet's count does", () => {
    expect(filterKits(KITS, { status: "complete", series: "", search: "zaku" })).toEqual([]);
    expect(names(filterKits(KITS, { status: "building", series: "", search: "zaku" }))).toEqual(["HG Zaku II/building"]);
  });
});

const order = (id: string, fields: Partial<Order>): Order =>
  ({ id, retailer_id: "r1", order_number: null, tracking_number: null, stage: "ordered", items: [], ...fields }) as Order;

const RETAILERS = new Map([
  ["r1", "Mecha Supply Co"],
  ["r2", "Side 7 Hobby Works"],
]);
const ORDERS = [
  order("a", { order_number: "MS-91055" }),
  order("b", { retailer_id: "r2", stage: "in_transit", order_number: "S7-20260812", tracking_number: "EJ482113905JP" }),
  order("c", { retailer_id: "r2", stage: "received" }), // no number, no tracking
  order("d", { retailer_id: "gone", stage: "received" }), // a retailer the map does not know
];
const ids = (rows: Order[]) => rows.map((row) => row.id);

describe("filterOrders", () => {
  it("keeps everything when nothing is chosen", () => {
    expect(ids(filterOrders(ORDERS, { stage: "", retailer: "", search: "" }, RETAILERS))).toEqual(["a", "b", "c", "d"]);
  });

  it("narrows by stage, by retailer, and by both", () => {
    expect(ids(filterOrders(ORDERS, { stage: "received", retailer: "", search: "" }, RETAILERS))).toEqual(["c", "d"]);
    expect(ids(filterOrders(ORDERS, { stage: "", retailer: "r2", search: "" }, RETAILERS))).toEqual(["b", "c"]);
    expect(ids(filterOrders(ORDERS, { stage: "received", retailer: "r2", search: "" }, RETAILERS))).toEqual(["c"]);
  });

  it.each([
    ["side 7", ["b", "c"]], // the retailer's name, which the row does not carry
    ["ms-91055", ["a"]], // the order number
    ["ej4821", ["b"]], // the tracking number
    ["   ", ["a", "b", "c", "d"]],
    ["nothing like this", []],
  ])("searches the retailer, the number and the tracking: %j → %j", (search, expected) => {
    expect(ids(filterOrders(ORDERS, { stage: "", retailer: "", search }, RETAILERS))).toEqual(expected);
  });

  it("an order whose retailer is unknown, with no number or tracking, is simply not found by a search", () => {
    // Every searchable field null: nothing to read, and nothing to throw on.
    expect(ids(filterOrders(ORDERS, { stage: "", retailer: "gone", search: "x" }, RETAILERS))).toEqual([]);
    expect(ids(filterOrders(ORDERS, { stage: "", retailer: "gone", search: "" }, new Map()))).toEqual(["d"]);
  });
});
