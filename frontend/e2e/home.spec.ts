/** #233 (design §13.2): Home is the start page — the bench, the two strips,
 *  the mail columns — with the true counts in its headings, a *view all* link
 *  that lands on the list page filtered and sorted, and one visible edit
 *  control per card opening the same dialog the list pages use. Every row this
 *  spec reads is its own, named with a unique prefix; the counts are asserted
 *  as differences against the server's own summary, so a populated dev
 *  database changes nothing. */
import { expect, test } from "@playwright/test";

import { apiContext } from "./api";

const suffix = Date.now().toString(36);
const PREFIX = `E2E Home ${suffix}`;
const SHOP = `E2E Home Shop ${suffix}`;
const name = (label: string) => `${PREFIX} ${label}`;

type Summary = {
  kits: Record<string, number>;
  orders: Record<string, number>;
};

const kitIds: string[] = [];
const orderIds: string[] = [];
let retailerId: string;
let movedKitId: string;
let before: Summary;

test.beforeAll(async () => {
  const api = await apiContext();
  before = (await (await api.get("/summary")).json()) as Summary;
  const post = async (route: string, data: object) => {
    const resp = await api.post(route, { data });
    expect(resp.ok(), `${route}: ${await resp.text()}`).toBeTruthy();
    return (await resp.json()) as { id: string; items?: { spawned_kit_ids: string[] }[] };
  };
  // Two on the bench (one with a start date and a note, one bare), one backlog
  // kit — the newest backlog kit anywhere, so it heads the strip — and one
  // completed with a rating.
  // Two backlog kits, older then newer: the strips and the Kits list are asserted
  // on their *relative* order, which holds whatever else the database holds.
  kitIds.push((await post("/kits", { name: name("Backlog older"), grade: "HG", status: "backlog" })).id);
  kitIds.push(
    (
      await post("/kits", {
        name: name("Bench A"),
        grade: "MG",
        kit_number: "5062845",
        status: "building",
        build_started_at: "2026-06-14T00:00:00+10:00",
        build_notes: "Panel-lining the core block.",
      })
    ).id,
    (await post("/kits", { name: name("Bench B"), grade: "RG", status: "building" })).id,
    (await post("/kits", { name: name("Backlog"), grade: "HG", status: "backlog" })).id,
  );
  const done = await post("/kits", { name: name("Done"), grade: "SD", status: "complete" });
  kitIds.push(done.id);
  const rated = await api.patch(`/kits/${done.id}`, { data: { rating: 4 } });
  expect(rated.ok()).toBeTruthy();

  retailerId = (await post("/retailers", { name: SHOP })).id;
  const line = (kitName: string, status?: string) => ({
    item_type: "kit",
    quantity: 1,
    unit_price_minor: 2800,
    currency_code: "JPY",
    kit: { name: kitName, grade: "HG", ...(status ? { status } : {}) },
  });
  const order = async (data: object) => {
    const created = await post("/orders", { retailer_id: retailerId, currency_code: "JPY", ...data });
    orderIds.push(created.id);
    return created;
  };
  // Pre-ordered: every kit a pre-order. Ordered: a mixed order — its
  // pre-ordered line is tagged. In transit: shipped, with a carrier and a
  // tracking number.
  await order({ order_date: "2026-08-21", items: [line(name("Pre"), "pre_ordered")] });
  await order({
    order_date: "2026-08-30",
    items: [line(name("Mixed ordered")), line(name("Mixed pre"), "pre_ordered")],
  });
  await order({
    order_date: "2026-09-01",
    shipped_at: "2026-09-04T10:00:00+00:00",
    delivery_service: "AusPost",
    tracking_number: `33AAB${suffix}`,
    tracking_url: `https://example.com/track/33AAB${suffix}`,
    items: [line(name("Shipped")), line(name("Shipped too")), line(name("Shipped three"))],
  });
  // A URL and no number (Codex #237 P3-3): the card must still link it.
  await order({
    order_date: "2026-09-02",
    shipped_at: "2026-09-03T10:00:00+00:00",
    tracking_url: `https://example.com/track/url-only-${suffix}`,
    items: [line(name("Url only"))],
  });
  // A pending order whose one kit the owner moves by hand (Codex #237 P2): the
  // order's stage follows its kits, so the card must change column.
  const moved = await order({ order_date: "2026-09-05", items: [line(name("Moved kit"))] });
  movedKitId = moved.items![0].spawned_kit_ids[0];
  await api.dispose();
});

test.afterAll(async () => {
  const api = await apiContext();
  for (const id of orderIds) await api.delete(`/orders/${id}`);
  for (const id of kitIds) await api.delete(`/kits/${id}`); // a 404 is a row a test deleted
  if (retailerId) await api.delete(`/retailers/${retailerId}`);
  await api.dispose();
});

test("Home is the index route and /board lands on it", async ({ page }) => {
  await page.goto("/board");
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { level: 1, name: "Home" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Home" })).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("link", { name: "Board" })).toHaveCount(0);
});

test("the three sections render from the collection, with the server's counts", async ({
  page,
}) => {
  await page.goto("/");

  // The bench: every building kit as a card, the day counter and the note on
  // the one that has a start date, "No start date" on the one that doesn't.
  const bench = page.getByRole("region", { name: "On the bench" });
  const cardA = bench.getByRole("article").filter({ hasText: name("Bench A") });
  await expect(cardA.getByRole("heading", { level: 3 })).toHaveText(name("Bench A"));
  await expect(cardA.getByText("MG", { exact: true })).toBeVisible();
  await expect(cardA.getByText("5062845")).toBeVisible();
  await expect(cardA.getByText(/^Started /)).toBeVisible();
  await expect(cardA.getByText(/^day \d+$/)).toBeVisible();
  await expect(cardA.getByText("Panel-lining the core block.")).toBeVisible();
  const cardB = bench.getByRole("article").filter({ hasText: name("Bench B") });
  await expect(cardB.getByText("No start date")).toBeVisible();
  await expect(cardB.getByText("No notes yet")).toBeVisible();

  // The strips: the newest backlog kit heads its strip; the completed one shows
  // its rating. The heading counts are the summary's — read off the API, not
  // assumed, so a populated database changes nothing.
  const api = await apiContext();
  const summary = (await (await api.get("/summary")).json()) as Summary;
  await api.dispose();
  expect(summary.kits.building).toBe(before.kits.building + 2);
  expect(summary.kits.backlog).toBe(before.kits.backlog + 2);
  expect(summary.kits.complete).toBe(before.kits.complete + 1);
  await expect(page.getByTestId("home-count-building")).toHaveText(String(summary.kits.building));
  await expect(page.getByTestId("home-count-backlog")).toHaveText(String(summary.kits.backlog));
  await expect(page.getByTestId("home-count-complete")).toHaveText(String(summary.kits.complete));
  const backlog = page.getByRole("region", { name: "Backlog" });
  await expect(backlog.getByText(name("Backlog"), { exact: true })).toBeVisible();
  const completed = page.getByRole("region", { name: "Recently completed" });
  const doneRow = completed.locator("div").filter({ hasText: name("Done") }).last();
  await expect(doneRow.getByRole("img", { name: "4/5" })).toBeVisible();

  // The mail: one card per column from this run, the mixed order's pre-ordered
  // line tagged, the shipped one with its carrier and tracking number.
  const mail = page.getByRole("region", { name: "In the mail" });
  const inMail =
    summary.orders.pre_ordered + summary.orders.ordered + summary.orders.in_transit;
  await expect(page.getByTestId("home-count-mail")).toHaveText(String(inMail));
  await expect(page.getByTestId("home-count-pre_ordered")).toHaveText(
    String(summary.orders.pre_ordered),
  );
  const pre = mail.getByRole("article").filter({ hasText: name("Pre") });
  await expect(pre.getByText(/^Placed /)).toBeVisible();
  await expect(pre.getByText("pre-order")).toHaveCount(0); // the column says it
  const mixed = mail.getByRole("article").filter({ hasText: name("Mixed ordered") });
  await expect(mixed.getByText(`and ${name("Mixed pre")}`)).toBeVisible();
  await expect(mixed.getByText("pre-order")).toBeVisible();
  const shipped = mail.getByRole("article").filter({ hasText: name("Shipped") }).first();
  await expect(shipped.getByText(/^Shipped .* · AusPost$/)).toBeVisible();
  await expect(shipped.getByText("and 2 more lines")).toBeVisible();
  // Tracking (Codex #237 P3-3): number + URL is a link named by the number; a
  // URL alone is a link with the Orders page's fallback word; the pending and
  // pre-ordered cards carry no tracking at all.
  await expect(shipped.getByRole("link", { name: `33AAB${suffix}` })).toHaveAttribute(
    "href",
    `https://example.com/track/33AAB${suffix}`,
  );
  const urlOnly = mail.getByRole("article").filter({ hasText: name("Url only") });
  await expect(urlOnly.getByRole("link", { name: "link" })).toHaveAttribute(
    "href",
    `https://example.com/track/url-only-${suffix}`,
  );
  await expect(pre.getByRole("link")).toHaveCount(0);
});

test("a kit moved by hand moves its order's card to the stage the server now reports (Codex #237 P2)", async ({
  page,
}) => {
  // The finding's route: the kit arrived early and was put in `backlog` by
  // hand, so it sits on Home's backlog strip with a pencil of its own; the
  // order is still pending, under Ordered.
  const api = await apiContext();
  expect((await api.patch(`/kits/${movedKitId}`, { data: { status: "backlog" } })).ok()).toBeTruthy();
  await api.dispose();
  await page.goto("/");
  const mail = page.getByRole("region", { name: "In the mail" });
  const card = mail.getByRole("article").filter({ hasText: name("Moved kit") });
  await expect(card).toBeVisible();
  // Which column holds the card: the chip at the head of the card's column.
  const columnOf = () =>
    card.evaluate(
      (el) =>
        el.parentElement?.parentElement?.querySelector("[class*='text-status-']")?.textContent ?? "",
    );
  expect(await columnOf()).toBe("Ordered");
  await page
    .getByRole("region", { name: "Backlog" })
    .getByRole("button", { name: `Edit ${name("Moved kit")}` })
    .click();
  const dialog = page.getByRole("dialog", { name: `Edit ${name("Moved kit")}` });
  await dialog.getByLabel("Status").selectOption("pre_ordered");
  await dialog.getByRole("button", { name: "Save" }).click();
  await expect(dialog).toHaveCount(0);
  // The completed state after the save, no reload: the card under Pre-ordered,
  // the headings agreeing with it.
  await expect.poll(columnOf).toBe("Pre-ordered");
  await expect(page.getByTestId("home-count-pre_ordered")).toHaveText(
    String(before.orders.pre_ordered + 2),
  );
  await expect(page.getByTestId("home-count-ordered")).toHaveText(String(before.orders.ordered + 1));
});

test("no width lets the page scroll sideways, and every mail card keeps its retailer readable (Codex #237 P3-2)", async ({
  page,
}) => {
  for (const width of [700, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/");
    const mail = page.getByRole("region", { name: "In the mail" });
    await expect(mail.getByRole("article").filter({ hasText: name("Shipped") }).first()).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, `${width}px: horizontal overflow`).toBe(0);
    // Each card of this run: the retailer has width, and nothing in the card
    // reaches past the card's own box.
    for (const label of ["Pre", "Mixed ordered", "Shipped", "Url only", "Moved kit"]) {
      const card = mail.getByRole("article").filter({ hasText: name(label) }).first();
      const retailer = card.getByText(SHOP, { exact: true });
      const box = (await retailer.boundingBox())!;
      expect(box.width, `${width}px: retailer width on ${label}`).toBeGreaterThan(40);
      const spill = await card.evaluate((el) => {
        const outer = el.getBoundingClientRect();
        return [...el.querySelectorAll("*")].filter((child) => {
          const r = child.getBoundingClientRect();
          return r.width > 0 && r.right > outer.right + 1;
        }).length;
      });
      expect(spill, `${width}px: content past the card on ${label}`).toBe(0);
    }
  }
});

test("a view-all link lands on the list page filtered and sorted", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: /^View all \d+ in the backlog$/ }).click();
  await expect(page).toHaveURL(/\/kits\?status=backlog&sort=recent$/);
  await expect(page.getByLabel("Filter by status")).toHaveValue("backlog");
  await expect(page.getByLabel("Sort")).toHaveValue("recent");
  // The index route is not "current" everywhere (NavLink `end`).
  await expect(page.getByRole("link", { name: "Home" })).not.toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("link", { name: "Kits" })).toHaveAttribute("aria-current", "page");
  // Newest first, asserted on this run's own two kits: the newer precedes the
  // older whatever else the database holds (Codex #237, call 9).
  const rows = page.getByRole("row");
  await expect(rows.filter({ hasText: name("Backlog older") })).toHaveCount(1);
  const names = await rows.allInnerTexts();
  const newer = names.findIndex((text) => text.includes(name("Backlog")) && !text.includes("older"));
  const older = names.findIndex((text) => text.includes(name("Backlog older")));
  expect(newer).toBeGreaterThan(0);
  expect(newer).toBeLessThan(older);
});

test("the card's edit control opens the shared dialog, and a status change moves the kit", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: `Edit ${name("Bench B")}` }).click();
  const dialog = page.getByRole("dialog", { name: `Edit ${name("Bench B")}` });
  await dialog.getByLabel("Status").selectOption("complete");
  await dialog.getByRole("button", { name: "Save" }).click();
  await expect(dialog).toHaveCount(0);
  // Off the bench, onto the completed strip, and the counts followed without a
  // reload — the save invalidated the summary too.
  const bench = page.getByRole("region", { name: "On the bench" });
  await expect(bench.getByText(name("Bench B"))).toHaveCount(0);
  await expect(
    page.getByRole("region", { name: "Recently completed" }).getByText(name("Bench B")),
  ).toBeVisible();
  await expect(page.getByTestId("home-count-building")).toHaveText(String(before.kits.building + 1));
  await expect(page.getByTestId("home-count-complete")).toHaveText(String(before.kits.complete + 2));
});

test("an order card opens the order dialog, where the ship transition lives", async ({ page }) => {
  await page.goto("/");
  const mail = page.getByRole("region", { name: "In the mail" });
  const pre = mail.getByRole("article").filter({ hasText: name("Pre") });
  await pre.getByRole("button", { name: /^Edit the .* order of / }).click();
  const dialog = page.getByRole("dialog", { name: "Edit order" });
  await expect(dialog.getByLabel("Shipped on")).toBeVisible();
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toHaveCount(0);
});

test("an empty collection renders every section with its empty state", async ({ page }) => {
  // Can't empty a shared database; instead answer the page's own requests
  // with nothing, which is exactly what a fresh instance returns.
  await page.route(
    (url) => url.pathname === "/api/summary",
    (route) =>
      route.fulfill({
        json: {
          kits: { pre_ordered: 0, ordered: 0, in_transit: 0, backlog: 0, building: 0, complete: 0 },
          orders: { pre_ordered: 0, ordered: 0, in_transit: 0, received: 0 },
        },
      }),
  );
  await page.route(
    (url) => url.pathname === "/api/kits" || url.pathname === "/api/orders",
    (route) => route.fulfill({ json: [] }),
  );
  await page.goto("/");
  await expect(page.getByText("Nothing on the bench — pick something from the backlog.")).toBeVisible();
  await expect(page.getByText("The backlog is empty. Enjoy it while it lasts.")).toBeVisible();
  await expect(page.getByText("Nothing completed yet.")).toBeVisible();
  await expect(page.getByText("No pre-orders")).toBeVisible();
  await expect(page.getByText("Nothing ordered")).toBeVisible();
  await expect(page.getByText("Nothing in transit")).toBeVisible();
  await expect(page.getByRole("link", { name: /^View all/ })).toHaveCount(0);
  await expect(page.getByTestId("home-count-mail")).toHaveText("0");
});
