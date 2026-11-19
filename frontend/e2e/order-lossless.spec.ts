/** Issue #34: an order edit must not restate facts it never mentioned.
 *
 * The form was not a faithful projection of the stored row — it modelled one
 * currency per order, no kit scale, and no difference between "free postage" and
 * "no shipping cost recorded". Editing a tracking number therefore rewrote a
 * line's money, re-derived its kit's scale, and turned a recorded 0 into null.
 *
 * These are round-trip assertions, so they belong here rather than in the backend
 * suite: the API already stores all of this correctly, and did throughout. Each
 * case below is one the browser used to destroy on the way past.
 */
import { expect, type Page, test } from "@playwright/test";

import { apiContext } from "./api";

const suffix = Date.now().toString(36);
const SHOP = `E2E Lossless Shop ${suffix}`;
const ORDER = `LOSSLESS-${suffix}`;
const KIT = `E2E Scaled Kit ${suffix}`;

type Line = {
  id: string;
  unit_price_minor: number;
  currency_code: string;
  converted_price_minor: number | null;
  converted_currency_code: string | null;
  spawned_kit_ids: string[];
};

type StoredOrder = {
  id: string;
  order_number: string | null;
  shipping_cost_minor: number | null;
  tracking_number: string | null;
  notes: string | null;
  items: Line[];
  adjustments: { id: string; label: string; amount_minor: number }[];
};

type Adjustment = { label: string; amount_minor: number };

test.describe.configure({ mode: "serial" });

let reference: string; // this instance's currency
let foreign: string; // a purchase currency with a *different* exponent

async function findOrder(): Promise<StoredOrder> {
  const api = await apiContext();
  const orders = (await (await api.get("/orders")).json()) as StoredOrder[];
  await api.dispose();
  return orders.find((order) => order.order_number === ORDER)!;
}

async function kitScale(kitId: string): Promise<string | null> {
  const api = await apiContext();
  const kits = (await (await api.get("/kits")).json()) as { id: string; scale: string | null }[];
  await api.dispose();
  return kits.find((kit) => kit.id === kitId)!.scale;
}

test.beforeAll("seed an order carrying everything the form used to lose", async () => {
  const api = await apiContext();
  reference = ((await (await api.get("/meta")).json()) as { reference_currency: string })
    .reference_currency;
  // A *different exponent* is what makes a mis-scaled amount visible: 1200 whole
  // yen read as if it were dollars-and-cents comes back as 120000.
  foreign = reference === "JPY" ? "AUD" : "JPY";

  const retailer = (await (await api.post("/retailers", { data: { name: SHOP } })).json()) as {
    id: string;
  };
  const created = await api.post("/orders", {
    data: {
      retailer_id: retailer.id,
      order_date: "2026-08-01",
      order_number: ORDER,
      currency_code: reference,
      // Free postage: a recorded fact, not a missing value.
      shipping_cost_minor: 0,
      items: [
        {
          item_type: "kit",
          quantity: 1,
          // A line denominated in something other than the order header. Only
          // REST, MCP and CSV can create this shape; the browser must not break it.
          unit_price_minor: 1200,
          currency_code: foreign,
          converted_price_minor: 1850,
          converted_currency_code: reference,
          // HG derives 1/144, so 1/100 is only ever here because someone chose it.
          kit: { name: KIT, grade: "HG", scale: "1/100" },
        },
      ],
    },
  });
  expect(created.status(), await created.text()).toBe(201);
  await api.dispose();
});

test("editing only the tracking number leaves currency, scale and free shipping alone", async ({
  page,
}) => {
  const before = await findOrder();
  const line = before.items[0];
  const kitId = line.spawned_kit_ids[0];
  // Controls: the seed really did store what the assertions below depend on.
  expect(line.currency_code).toBe(foreign);
  expect(before.shipping_cost_minor).toBe(0);
  expect(await kitScale(kitId)).toBe("1/100");

  await page.goto(`/orders?q=${encodeURIComponent(SHOP)}`);
  const row = page.getByRole("row").filter({ hasText: ORDER });
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: "Edit" }).click();
  // The scale reached the form at all — without it there is nothing to send back
  // and the API re-derives 1/144 from the grade.
  await expect(page.getByLabel("Scale")).toHaveValue("1/100");

  await page.getByLabel("Tracking number").fill(`TRK-${suffix}`);
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByRole("button", { name: "Save changes" })).toBeHidden();

  const after = await findOrder();
  const edited = after.items.find((candidate) => candidate.id === line.id)!;
  // The edit really happened — otherwise everything below proves nothing.
  expect(after.tracking_number).toBe(`TRK-${suffix}`);

  expect(edited.currency_code).toBe(foreign);
  expect(edited.unit_price_minor).toBe(1200);
  expect(edited.converted_price_minor).toBe(1850);
  expect(edited.converted_currency_code).toBe(reference);
  expect(after.shipping_cost_minor).toBe(0);
  expect(await kitScale(edited.spawned_kit_ids[0])).toBe("1/100");
});

test("a note is written, survives an edit that never mentions it, and clears", async ({ page }) => {
  const NOTE = "Part-paid with a gift card.\nThe rest on the Visa.";
  const open = async () => {
    await page.goto(`/orders?q=${encodeURIComponent(SHOP)}`);
    await page.getByRole("row").filter({ hasText: ORDER }).getByRole("button", { name: "Edit" }).click();
  };
  const save = async () => {
    await page.getByRole("button", { name: "Save changes" }).click();
    await expect(page.getByRole("button", { name: "Save changes" })).toBeHidden();
  };

  await open();
  // Surrounding whitespace is not part of a note: the server says what is.
  await page.getByLabel("Notes").fill(`${NOTE}\n`);
  await save();
  expect((await findOrder()).notes).toBe(NOTE);

  await open();
  await expect(page.getByLabel("Notes")).toHaveValue(NOTE);
  await page.getByLabel("Tracking number").fill(`NOTE-${suffix}`);
  await save();
  const edited = await findOrder();
  expect(edited.tracking_number).toBe(`NOTE-${suffix}`);
  expect(edited.notes).toBe(NOTE);

  await open();
  await page.getByLabel("Notes").fill("");
  await save();
  expect((await findOrder()).notes).toBeNull();
});

// The dialog holds a copy from when it opened, and an agent can write the order
// in the meantime. A save restates only what its own hand changed, so the agent's
// note stands: first where there was none, then over one the dialog is showing.
for (const [before, written] of [
  [null, "Gift card AUD 50, written while the dialog was open."],
  ["The note the dialog opened with.", "The note an agent replaced it with."],
] as const) {
  test(`a save that never touched the note leaves what an agent wrote meanwhile, over ${before === null ? "no note" : "a note"}`, async ({ page }) => {
    const writeNote = async (notes: string | null) => {
      const api = await apiContext();
      const response = await api.patch(`/orders/${(await findOrder()).id}`, { data: { notes } });
      expect(response.status(), await response.text()).toBe(200);
      await api.dispose();
    };
    await writeNote(before);

    await page.goto(`/orders?q=${encodeURIComponent(SHOP)}`);
    await page.getByRole("row").filter({ hasText: ORDER }).getByRole("button", { name: "Edit" }).click();
    // The dialog has its copy before the agent writes: that is the whole order of events.
    await expect(page.getByLabel("Notes")).toHaveValue(before ?? "");
    await writeNote(written);

    const tracking = `AGENT-${suffix}-${before === null ? "A" : "B"}`;
    await page.getByLabel("Tracking number").fill(tracking);
    await page.getByRole("button", { name: "Save changes" }).click();
    await expect(page.getByRole("button", { name: "Save changes" })).toBeHidden();

    const stored = await findOrder();
    expect(stored.tracking_number).toBe(tracking);
    expect(stored.notes).toBe(written);
  });
}

// A save is a PATCH and then the ship or receive it carries, so it can fail halfway:
// the note is stored, the dialog stays open, and the person gets another go.
test.describe("a save that fails after its note was stored", () => {
  type Transition = "ship" | "receive";
  const DATE_LABEL = { ship: "Shipped on", receive: "Received on" } as const;
  const STAMP = { ship: "shipped_at", receive: "received_at" } as const;
  let seeded = 0;

  /** An order of its own: a transition can't be undone for the next case. */
  async function openFailingSave(
    page: Page,
    transition: Transition,
    notes: string | null,
    adjustments: Adjustment[] = [],
  ) {
    const number = `RETRY-${suffix}-${++seeded}`;
    const api = await apiContext();
    const retailers = (await (await api.get("/retailers")).json()) as { id: string; name: string }[];
    const created = await api.post("/orders", {
      data: {
        retailer_id: retailers.find((retailer) => retailer.name === SHOP)!.id,
        order_date: "2020-01-01",
        order_number: number,
        currency_code: reference,
        notes,
        adjustments,
        items: [
          {
            item_type: "kit",
            quantity: 1,
            unit_price_minor: 1000,
            currency_code: reference,
            kit: { name: `E2E Retry Kit ${number}`, grade: "HG" },
          },
        ],
      },
    });
    expect(created.status(), await created.text()).toBe(201);
    const { id } = (await created.json()) as { id: string };
    await api.dispose();

    await page.route(`**/orders/${id}/${transition}`, (route) => route.fulfill({ status: 503 }), {
      times: 1,
    });
    await page.goto(`/orders?q=${encodeURIComponent(number)}`);
    await page.getByRole("row").filter({ hasText: number }).getByRole("button", { name: "Edit" }).click();
    await expect(page.getByLabel("Notes")).toHaveValue(notes ?? "");
    await page.getByLabel(DATE_LABEL[transition]).fill("2020-02-01");

    const read = async () => {
      const reader = await apiContext();
      const stored = (await (await reader.get(`/orders/${id}`)).json()) as StoredOrder &
        Record<(typeof STAMP)[Transition], string | null>;
      await reader.dispose();
      return stored;
    };
    const write = async (data: object) => {
      const writer = await apiContext();
      const response = await writer.patch(`/orders/${id}`, { data });
      expect(response.status(), await response.text()).toBe(200);
      await writer.dispose();
    };
    const save = page.getByRole("button", { name: "Save changes" });
    /** The PATCH lands, the transition 503s, the dialog stays open and can go again. */
    const saveAndFail = async () => {
      const failed = page.waitForResponse(`**/orders/${id}/${transition}`);
      await save.click();
      expect((await failed).status()).toBe(503);
      await expect(save).toBeEnabled();
    };
    const saveAndClose = async () => {
      await save.click();
      await expect(save).toBeHidden();
    };
    return { read, write, saveAndFail, saveAndClose };
  }

  for (const transition of ["ship", "receive"] as const) {
    for (const before of [null, "The note it opened with."]) {
      test(`${transition}: putting the note back to how it opened is kept, from ${before === null ? "no note" : "a note"}`, async ({ page }) => {
        const { read, saveAndFail, saveAndClose } = await openFailingSave(page, transition, before);
        await page.getByLabel("Notes").fill("Stored by the half that worked.");
        await saveAndFail();
        expect((await read()).notes).toBe("Stored by the half that worked.");

        // Back to the opening value, which is not dirty, and is not what is stored.
        await page.getByLabel("Notes").fill(before ?? "");
        await saveAndClose();
        const stored = await read();
        expect(stored.notes).toBe(before);
        expect(stored[STAMP[transition]]).not.toBeNull();
      });
    }

    test(`${transition}: a retry that never touched the note still leaves what an agent wrote`, async ({ page }) => {
      const { read, write, saveAndFail, saveAndClose } = await openFailingSave(page, transition, null);
      await page.getByLabel("Tracking number").fill(`RETRY-${suffix}`);
      await saveAndFail();
      await write({ notes: "Written between the two tries." });
      await saveAndClose();
      expect((await read()).notes).toBe("Written between the two tries.");
    });

    // The first try stored the person's note, so on the retry it is what counts
    // as unchanged (#358): a note an agent wrote over it between the two tries is
    // the later write, and a retry that leaves the note alone leaves it. Until
    // #358 a latch re-sent it on every try after the first.
    test(`${transition}: a note the first try stored is not restated by a retry that left it`, async ({ page }) => {
      const { read, write, saveAndFail, saveAndClose } = await openFailingSave(page, transition, null);
      await page.getByLabel("Notes").fill("The person's note.");
      await saveAndFail();
      expect((await read()).notes).toBe("The person's note.");
      await write({ notes: "Written between the two tries." });
      await saveAndClose();
      expect((await read()).notes).toBe("Written between the two tries.");
    });

    test(`${transition}: a note changed again on the retry is the person's`, async ({ page }) => {
      const { read, write, saveAndFail, saveAndClose } = await openFailingSave(page, transition, null);
      await page.getByLabel("Notes").fill("The person's note.");
      await saveAndFail();
      await write({ notes: "Written between the two tries." });
      await page.getByLabel("Notes").fill("The person's second thought.");
      await saveAndClose();
      expect((await read()).notes).toBe("The person's second thought.");
    });

    // The same three questions of what came off (#350; Codex #362, finding 1): it is
    // sent only when this edit touched it, so it has the note's retry to answer for.
    const cameOff = (stored: StoredOrder): Adjustment[] =>
      stored.adjustments.map(({ label, amount_minor }) => ({ label, amount_minor }));
    const GIFT: Adjustment = { label: "Gift card", amount_minor: 100 };
    const BETWEEN: Adjustment = { label: "Written between the two tries", amount_minor: 300 };

    for (const before of [[], [GIFT]]) {
      test(`${transition}: putting what came off back to how it opened is kept, from ${before.length ? "one adjustment" : "none"}`, async ({ page }) => {
        const { read, saveAndFail, saveAndClose } = await openFailingSave(page, transition, null, before);
        if (before.length === 0) {
          await page.getByRole("button", { name: "Add discount" }).click();
          await page.getByLabel("What came off").fill(GIFT.label);
        }
        const amount = page.getByLabel("Amount off");
        // As the form wrote it, so that putting it back is not a change of spelling.
        const opening = await amount.inputValue();
        await amount.fill("2.00");
        await saveAndFail();
        expect(cameOff(await read())).toEqual([{ ...GIFT, amount_minor: 200 }]);

        // Back to how it opened, which is not dirty, and is not what is stored.
        if (before.length === 0) await page.getByRole("button", { name: "Remove discount" }).click();
        else await amount.fill(opening);
        await saveAndClose();
        const stored = await read();
        expect(cameOff(stored)).toEqual(before);
        expect(stored[STAMP[transition]]).not.toBeNull();
      });
    }

    test(`${transition}: a retry that never touched what came off still leaves what an agent wrote`, async ({ page }) => {
      const { read, write, saveAndFail, saveAndClose } = await openFailingSave(page, transition, null, [GIFT]);
      await page.getByLabel("Tracking number").fill(`RETRY-${suffix}`);
      await saveAndFail();
      await write({ adjustments: [BETWEEN] });
      await saveAndClose();
      expect(cameOff(await read())).toEqual([BETWEEN]);
    });

    // As for the note above: what the first try stored is the new "unchanged".
    test(`${transition}: what the first try said came off is not restated by a retry that left it`, async ({ page }) => {
      const { read, write, saveAndFail, saveAndClose } = await openFailingSave(page, transition, null, [GIFT]);
      await page.getByLabel("Amount off").fill("2.00");
      await saveAndFail();
      expect(cameOff(await read())).toEqual([{ ...GIFT, amount_minor: 200 }]);
      await write({ adjustments: [BETWEEN] });
      await saveAndClose();
      expect(cameOff(await read())).toEqual([BETWEEN]);
    });

    test(`${transition}: what came off, changed again on the retry, is the person's`, async ({ page }) => {
      const { read, write, saveAndFail, saveAndClose } = await openFailingSave(page, transition, null, [GIFT]);
      await page.getByLabel("Amount off").fill("2.00");
      await saveAndFail();
      await write({ adjustments: [BETWEEN] });
      await page.getByLabel("Amount off").fill("2.50");
      await saveAndClose();
      expect(cameOff(await read())).toEqual([{ ...GIFT, amount_minor: 250 }]);
    });
  }
});

/** Issue #358: the header holds a copy from when the dialog opened, as the note did,
 *  and a save sent all eight of its fields back whether or not they were changed.
 *
 *  Every order here is its own and carries a value in every field, so "kept",
 *  "overwritten" and "cleared" are three different stored values. */
test.describe("header fields an agent wrote while the dialog was open (#358)", () => {
  const OTHER_SHOP = `E2E Lossless Other Shop ${suffix}`;
  let seeded = 0;
  let shopId: string;
  let otherShopId: string;

  type Header = {
    id: string;
    retailer_id: string;
    order_date: string;
    order_number: string | null;
    currency_code: string;
    shipping_cost_minor: number | null;
    delivery_service: string | null;
    tracking_number: string | null;
    tracking_url: string | null;
    notes: string | null;
    shipped_at: string | null;
    received_at: string | null;
    items: Line[];
  };

  test.beforeAll(async () => {
    const api = await apiContext();
    const retailers = (await (await api.get("/retailers")).json()) as { id: string; name: string }[];
    shopId = retailers.find((retailer) => retailer.name === SHOP)!.id;
    const other = await api.post("/retailers", { data: { name: OTHER_SHOP } });
    expect(other.status(), await other.text()).toBe(201);
    otherShopId = ((await other.json()) as { id: string }).id;
    await api.dispose();
  });

  test.afterAll(async () => {
    // The shop orders were moved to: the file's own clean-up only knows the first.
    const api = await apiContext();
    const orders = (await (await api.get("/orders")).json()) as { id: string; retailer_id: string }[];
    for (const order of orders.filter((candidate) => candidate.retailer_id === otherShopId)) {
      await api.delete(`/orders/${order.id}`);
    }
    await api.delete(`/retailers/${otherShopId}`);
    await api.dispose();
  });

  /** An order with every header field set, its dialog open and hydrated. */
  async function openOrder(page: Page, extra: Record<string, unknown> = {}) {
    const number = `HEAD-${suffix}-${++seeded}`;
    const api = await apiContext();
    const created = await api.post("/orders", {
      data: {
        retailer_id: shopId,
        order_date: "2020-01-01",
        order_number: number,
        currency_code: reference,
        shipping_cost_minor: 500,
        delivery_service: "Opening Post",
        tracking_number: "OPENING-TRK",
        tracking_url: "https://tracking.example/opening",
        notes: "The note it opened with.",
        items: [
          {
            item_type: "kit",
            quantity: 1,
            unit_price_minor: 1000,
            currency_code: reference,
            kit: { name: `E2E Header Kit ${number}`, grade: "HG" },
          },
        ],
        ...extra,
      },
    });
    expect(created.status(), await created.text()).toBe(201);
    const { id } = (await created.json()) as { id: string };
    await api.dispose();

    await page.goto(`/orders?q=${encodeURIComponent(number)}`);
    await page.getByRole("row").filter({ hasText: number }).getByRole("button", { name: "Edit" }).click();
    // Hydrated: the dialog has its copy, so anything written from here is "meanwhile".
    await expect(page.getByLabel("Tracking number")).toHaveValue("OPENING-TRK");

    const read = async () => {
      const reader = await apiContext();
      const stored = (await (await reader.get(`/orders/${id}`)).json()) as Header;
      await reader.dispose();
      return stored;
    };
    const write = async (data: object) => {
      const writer = await apiContext();
      const response = await writer.patch(`/orders/${id}`, { data });
      expect(response.status(), await response.text()).toBe(200);
      await writer.dispose();
    };
    const save = page.getByRole("button", { name: "Save changes" });
    const saveAndClose = async () => {
      await save.click();
      await expect(save).toBeHidden();
    };
    return { id, read, write, save, saveAndClose };
  }

  // What an agent writes to each field while the dialog is open. Every value
  // differs from the opening one, so the stored row says which writer won.
  const AGENT: [keyof Header, () => unknown][] = [
    ["order_number", () => `AGENT-NUMBER-${suffix}`],
    ["order_date", () => "2021-03-04"],
    ["retailer_id", () => otherShopId],
    ["currency_code", () => foreign],
    ["shipping_cost_minor", () => 750],
    ["delivery_service", () => "Agent Express"],
    ["tracking_number", () => `AGENT-TRK-${suffix}`],
    ["tracking_url", () => "https://tracking.example/agent"],
  ];

  for (const [field, value] of AGENT) {
    test(`a save that changed only the note leaves the ${field} an agent wrote`, async ({ page }) => {
      const { read, write, saveAndClose } = await openOrder(page);
      await write({ [field]: value() });
      expect((await read())[field]).toEqual(value()); // control: the agent's write landed

      await page.getByLabel("Notes").fill("The person's note.");
      await saveAndClose();
      const stored = await read();
      expect(stored.notes).toBe("The person's note."); // the save happened
      expect(stored[field]).toEqual(value());
    });
  }

  // The eight above, asked once of the request itself: nothing else rides along,
  // the lines and what came off included.
  test("a save that changed only the note sends only the note", async ({ page }) => {
    const { id, read, saveAndClose } = await openOrder(page, {
      adjustments: [{ label: "Gift card", amount_minor: 100 }],
    });
    const patched = page.waitForRequest(
      (request) => request.method() === "PATCH" && request.url().endsWith(`/orders/${id}`),
    );
    await page.getByLabel("Notes").fill("The person's note.");
    await saveAndClose();
    expect((await patched).postDataJSON()).toEqual({ notes: "The person's note." });
    expect((await read()).notes).toBe("The person's note.");
  });

  test("a field typed and put back before the save is not sent", async ({ page }) => {
    const { read, write, saveAndClose } = await openOrder(page);
    const tracking = page.getByLabel("Tracking number");
    await tracking.fill("TYPED-THEN-UNDONE");
    await tracking.fill("OPENING-TRK");
    await write({ tracking_number: `AGENT-TRK-${suffix}` });
    await page.getByLabel("Notes").fill("The person's note.");
    await saveAndClose();
    const stored = await read();
    expect(stored.notes).toBe("The person's note.");
    expect(stored.tracking_number).toBe(`AGENT-TRK-${suffix}`);
  });

  test("when both wrote the same field, the person's save wins", async ({ page }) => {
    const { read, write, saveAndClose } = await openOrder(page);
    await write({ tracking_number: `AGENT-TRK-${suffix}`, delivery_service: "Agent Express" });
    await page.getByLabel("Tracking number").fill("THE-PERSON'S");
    await saveAndClose();
    const stored = await read();
    expect(stored.tracking_number).toBe("THE-PERSON'S");
    // and only that field: the one beside it was not the person's to restate
    expect(stored.delivery_service).toBe("Agent Express");
  });

  // Shipping cost is stored in minor units of the order's currency, so a currency
  // changed alone moves it: the amount on screen has to land in the new currency.
  // Two exponents, both ways, so that a stale minor amount is a factor of 100 off.
  for (const [from, to, shown, minorBefore, minorAfter] of [
    ["AUD", "JPY", "15.00", 1500, 15],
    ["JPY", "AUD", "1500", 1500, 150000],
  ] as const) {
    test(`a currency changed alone takes the shipping cost on screen with it, ${from} to ${to}`, async ({ page }) => {
      const { read, write, saveAndClose } = await openOrder(page, {
        currency_code: from,
        shipping_cost_minor: minorBefore,
      });
      await expect(page.getByLabel("Shipping cost")).toHaveValue(shown);
      // What the pair overrules: an agent's shipping cost, in the old currency.
      await write({ shipping_cost_minor: 900 });
      await page.getByLabel("Currency").fill(to);
      await saveAndClose();
      const stored = await read();
      expect(stored.currency_code).toBe(to);
      expect(stored.shipping_cost_minor).toBe(minorAfter);
      // Only the pair went: the rest of the header is the agent's to keep.
      expect(stored.tracking_number).toBe("OPENING-TRK");
    });
  }

  // The pair the other way round: a cost changed alone is read in the currency on
  // screen, so the currency goes with it, over one an agent chose meanwhile.
  test("a shipping cost changed alone is stored in the currency on screen", async ({ page }) => {
    const { read, write, saveAndClose } = await openOrder(page, {
      currency_code: "AUD",
      shipping_cost_minor: 1500,
    });
    await write({ currency_code: "JPY" });
    await page.getByLabel("Shipping cost").fill("12.50");
    await saveAndClose();
    const stored = await read();
    expect(stored.currency_code).toBe("AUD");
    expect(stored.shipping_cost_minor).toBe(1250);
  });

  // What came off is in the order's currency too (#350): a currency changed alone
  // restates the amounts on screen in it.
  test("a currency changed alone takes what came off on screen with it", async ({ page }) => {
    // Shipping is what the discount comes off once the currency moves: the line
    // stays in the currency it was bought in, and the server refuses a discount
    // larger than the order's lines in its own currency plus its shipping.
    const { read, saveAndClose } = await openOrder(page, {
      currency_code: "AUD",
      shipping_cost_minor: 500,
      adjustments: [{ label: "Gift card", amount_minor: 300 }],
    });
    await expect(page.getByLabel("Amount off")).toHaveValue("3.00");
    await page.getByLabel("Currency").fill("JPY");
    await saveAndClose();
    const stored = (await read()) as Header & { adjustments: Adjustment[] };
    expect(stored.currency_code).toBe("JPY");
    expect(stored.adjustments.map(({ label, amount_minor }) => ({ label, amount_minor }))).toEqual([
      { label: "Gift card", amount_minor: 3 },
    ]);
  });

  test("a kit detail changed on its line reaches the kit", async ({ page }) => {
    const { read, saveAndClose } = await openOrder(page);
    await page.getByPlaceholder("Kit #").fill("CHANGED-ON-THE-LINE");
    await saveAndClose();
    expect(await kitsOf((await read()).order_number!)).toMatchObject([
      { kit_number: "CHANGED-ON-THE-LINE" },
    ]);
  });

  // A line is compared with the stored line it names. Compared by position
  // instead, removing the first line set the second against the first's kit
  // details, so the save restated the second's from the dialog's copy over what
  // an agent had written to its kit.
  test("removing a line leaves the kit details of the line below it alone", async ({ page }) => {
    const kitLine = (name: string) => ({
      item_type: "kit",
      quantity: 1,
      unit_price_minor: 1000,
      currency_code: reference,
      kit: { name, grade: "HG", kit_number: `OPENING-${name}` },
    });
    const { read, saveAndClose } = await openOrder(page, {
      items: [kitLine(`E2E Header Line A ${suffix}`), kitLine(`E2E Header Line B ${suffix}`)],
    });
    // Whichever the order lists second is the line below; the dialog lists them
    // in the same order (checked below, once the first is gone).
    const opened = (await read()) as Header & { items: (Line & { kits: SpawnedKit[] })[] };
    const below = opened.items[1].kits[0];
    await patchKit(below.id, { kit_number: "AGENT-NO" });

    await page.getByRole("button", { name: "Remove line" }).first().click();
    await expect(page.getByPlaceholder("Kit name *")).toHaveValue(below.name);
    await saveAndClose();
    const stored = (await read()) as Header & { items: (Line & { kits: SpawnedKit[] })[] };
    expect(stored.items).toHaveLength(1);
    expect(stored.items[0].kits).toMatchObject([{ id: below.id, kit_number: "AGENT-NO" }]);
  });

  /** The save stores its PATCH, then the transition it carries 503s once. */
  function failOnce(page: Page, id: string, transition: "ship" | "receive") {
    return page.route(`**/orders/${id}/${transition}`, (route) => route.fulfill({ status: 503 }), {
      times: 1,
    });
  }
  async function saveAndFail(page: Page, id: string, transition: "ship" | "receive") {
    const failed = page.waitForResponse(`**/orders/${id}/${transition}`);
    await page.getByRole("button", { name: "Save changes" }).click();
    expect((await failed).status()).toBe(503);
    await expect(page.getByRole("button", { name: "Save changes" })).toBeEnabled();
  }

  // A save that failed halfway stored its PATCH. Putting a field back to how the
  // dialog opened is then a change from what is stored, and the retry owes it.
  for (const transition of ["ship", "receive"] as const) {
    const DATE = { ship: "Shipped on", receive: "Received on" }[transition];

    test(`${transition}: a header field put back after a failed save is stored as it opened`, async ({ page }) => {
      const { id, read, saveAndClose } = await openOrder(page);
      await failOnce(page, id, transition);
      await page.getByLabel(DATE).fill("2020-02-01");
      await page.getByLabel("Tracking number").fill("STORED-BY-THE-HALF-THAT-WORKED");
      await saveAndFail(page, id, transition);
      expect((await read()).tracking_number).toBe("STORED-BY-THE-HALF-THAT-WORKED");

      await page.getByLabel("Tracking number").fill("OPENING-TRK");
      await saveAndClose();
      expect((await read()).tracking_number).toBe("OPENING-TRK");
    });

    test(`${transition}: a line's price put back after a failed save is stored as it opened`, async ({ page }) => {
      const { id, read, saveAndClose } = await openOrder(page);
      await failOnce(page, id, transition);
      await page.getByLabel(DATE).fill("2020-02-01");
      const price = page.getByLabel("Unit price");
      const opening = await price.inputValue(); // as the form wrote it
      await price.fill("8.00");
      await saveAndFail(page, id, transition);
      expect((await read()).items[0].unit_price_minor).toBe(800);

      await price.fill(opening);
      await saveAndClose();
      expect((await read()).items[0].unit_price_minor).toBe(1000);
    });

    test(`${transition}: a retry that never touched a header field leaves what an agent wrote`, async ({ page }) => {
      const { id, read, write, saveAndClose } = await openOrder(page);
      await failOnce(page, id, transition);
      await page.getByLabel(DATE).fill("2020-02-01");
      await page.getByLabel("Notes").fill("The person's note.");
      await saveAndFail(page, id, transition);
      await write({ tracking_number: `AGENT-TRK-${suffix}` });
      await saveAndClose();
      const stored = await read();
      expect(stored.tracking_number).toBe(`AGENT-TRK-${suffix}`);
      expect(stored.notes).toBe("The person's note.");
    });
  }

  // A corrected date has the same trap: the receive fails after the PATCH stored
  // the correction, and the date put back is the one the order opened with.
  test("receive: a corrected ship date put back after a failed save is stored as it opened", async ({ page }) => {
    const opening = new Date(2020, 0, 15); // local midnight, as the dialog writes a date
    const { id, read, saveAndClose } = await openOrder(page, {});
    const shipper = await apiContext();
    const shipped = await shipper.post(`/orders/${id}/ship`, {
      data: { shipped_at: opening.toISOString() },
    });
    expect(shipped.status(), await shipped.text()).toBe(200);
    await shipper.dispose();
    // Reopened, so the dialog holds the shipped order.
    await page.reload();
    await page.getByRole("button", { name: "Edit" }).first().click();
    await expect(page.getByLabel("Shipped on")).toHaveValue("2020-01-15");

    await failOnce(page, id, "receive");
    await page.getByLabel("Shipped on").fill("2020-01-20");
    await page.getByLabel("Received on").fill("2020-02-01");
    await saveAndFail(page, id, "receive");
    expect(new Date((await read()).shipped_at!).getTime()).toBe(new Date(2020, 0, 20).getTime());

    await page.getByLabel("Shipped on").fill("2020-01-15");
    await saveAndClose();
    const stored = await read();
    expect(new Date(stored.shipped_at!).getTime()).toBe(opening.getTime());
    expect(stored.received_at).not.toBeNull();
  });

  // Both transitions in one save, the second failing: the ship is stored, so the
  // retry must not ship again (the server refuses a second ship), and a ship date
  // changed on the retry is now a correction of what the first try stored.
  test("a ship that worked is not repeated, and a ship date changed on the retry corrects it", async ({ page }) => {
    const { id, read, saveAndClose } = await openOrder(page);
    await failOnce(page, id, "receive");
    await page.getByLabel("Shipped on").fill("2020-01-15");
    await page.getByLabel("Received on").fill("2020-02-01");
    await saveAndFail(page, id, "receive");
    expect(new Date((await read()).shipped_at!).getTime()).toBe(new Date(2020, 0, 15).getTime());

    await page.getByLabel("Shipped on").fill("2020-01-20");
    await saveAndClose();
    const stored = await read();
    expect(new Date(stored.shipped_at!).getTime()).toBe(new Date(2020, 0, 20).getTime());
    expect(new Date(stored.received_at!).getTime()).toBe(new Date(2020, 1, 1).getTime());
  });

  // Shipped today, the server stamps the moment; a date field can only say
  // midnight. So once the ship has gone through, its date is what is stored, and
  // a retry that left it alone must not send it back as a correction.
  test("a ship that worked today is not restated as midnight by the retry", async ({ page }) => {
    const { id, read, saveAndClose } = await openOrder(page);
    await failOnce(page, id, "receive");
    const today = await page.getByLabel("Shipped on").getAttribute("max");
    await page.getByLabel("Shipped on").fill(today!);
    await page.getByLabel("Received on").fill(today!);
    await saveAndFail(page, id, "receive");
    const stamped = (await read()).shipped_at;
    expect(stamped).not.toBeNull();

    await saveAndClose();
    const stored = await read();
    expect(stored.shipped_at).toBe(stamped);
    expect(stored.received_at).not.toBeNull();
  });
});

test("a new order is created with its note", async ({ page }) => {
  const NUMBER = `NOTED-${suffix}`;
  await page.goto("/orders");
  await page.getByRole("button", { name: "New order" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.locator('select[name="retailer_id"]').selectOption({ label: SHOP });
  await page.getByLabel("Order number").fill(NUMBER);
  await page.getByLabel("Notes").fill("Bought in store.");
  await dialog.getByPlaceholder("Kit name *").fill(`E2E Noted Kit ${suffix}`);
  await dialog.getByPlaceholder("Grade *").fill("HG");
  await page.getByLabel("Unit price").first().fill("10");
  await page.getByRole("button", { name: "Record order" }).click();
  await expect(page.getByRole("button", { name: "Record order" })).toBeHidden();

  const api = await apiContext();
  const orders = (await (await api.get("/orders")).json()) as { id: string; order_number: string | null; notes: string | null }[];
  const created = orders.find((order) => order.order_number === NUMBER)!;
  expect(created.notes).toBe("Bought in store.");
  const deleted = await api.delete(`/orders/${created.id}`);
  expect(deleted.status(), await deleted.text()).toBe(204);
  await api.dispose();
});

test("a cold edit waits for the data it rebuilds the form from", async ({ page }) => {
  // Mounting the form before its queries resolve captured blanks in defaultValues,
  // which react-hook-form never revisits, and wrote them back.
  //
  // This used to hold `/api/kits`, because kit details were read from that list.
  // They now arrive on the order itself (#65), so the list is no longer a
  // dependency and holding it would prove nothing. The gate that remains covers
  // catalog naming, so that is what this holds — and the kit assertions below
  // still stand, because those values must survive regardless of which query is slow.
  let release = () => {};
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/consumables", async (route) => {
    await held;
    await route.continue();
  });

  await page.goto(`/orders?q=${encodeURIComponent(SHOP)}`);
  const row = page.getByRole("row").filter({ hasText: ORDER });
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: "Edit" }).click();

  // No form at all while the data is outstanding. Not rendering the fields would
  // not be enough — the hooks would already have run.
  await expect(page.getByRole("dialog")).toContainText("Loading…");
  await expect(page.getByPlaceholder("Kit name *")).toBeHidden();

  release();
  await expect(page.getByPlaceholder("Kit name *")).toHaveValue(KIT);
  await expect(page.getByLabel("Scale")).toHaveValue("1/100");
});

/** Issue #65: the same invariant, for the kits a line spawned rather than the line.
 *
 * A line renders one set of kit fields but can own several kits, so the form shows
 * the first and every save echoed it back over all of them. Two spawned kits made
 * deliberately different were flattened by an edit that never mentioned kits.
 */
const MULTI = `MULTI-${suffix}`;

type SpawnedKit = { id: string; scale: string | null; kit_number: string | null; name: string };

/** Resolved through `/kits` rather than the order payload's nested kits, so this
 *  reads the same on either side of the fix — these tests are about what ends up
 *  stored, and the payload's shape is the backend suite's business. */
async function kitsOf(orderNumber: string): Promise<SpawnedKit[]> {
  const api = await apiContext();
  const orders = (await (await api.get("/orders")).json()) as StoredOrder[];
  const ids = orders.find((order) => order.order_number === orderNumber)!.items[0].spawned_kit_ids;
  const all = (await (await api.get("/kits")).json()) as SpawnedKit[];
  await api.dispose();
  return ids.map((id) => all.find((kit) => kit.id === id)!);
}

async function patchKit(id: string, data: Record<string, string>): Promise<void> {
  const api = await apiContext();
  const resp = await api.patch(`/kits/${id}`, { data });
  expect(resp.status(), await resp.text()).toBe(200);
  await api.dispose();
}

test.beforeAll("seed a two-kit line whose kits are then made different", async () => {
  const api = await apiContext();
  const retailers = (await (await api.get("/retailers")).json()) as { id: string; name: string }[];
  const created = await api.post("/orders", {
    data: {
      retailer_id: retailers.find((r) => r.name === SHOP)!.id,
      order_date: "2026-08-01",
      order_number: MULTI,
      currency_code: reference,
      items: [
        {
          item_type: "kit",
          quantity: 2,
          unit_price_minor: 4999,
          currency_code: reference,
          kit: { name: `${KIT} pair`, grade: "HG", kit_number: "HGUC 210" },
        },
      ],
    },
  });
  expect(created.status(), await created.text()).toBe(201);
  await api.dispose();

  // Through the supported Kits path, exactly as an owner would.
  const [, second] = await kitsOf(MULTI);
  await patchKit(second.id, { scale: "1/60", kit_number: "DIVERGENT" });
});

test("a tracking-only edit leaves two divergent kits on the same line divergent", async ({
  page,
}) => {
  const [firstBefore, secondBefore] = await kitsOf(MULTI);
  expect(secondBefore.scale).toBe("1/60"); // control: the seed diverged

  await page.goto(`/orders?q=${encodeURIComponent(SHOP)}`);
  const row = page.getByRole("row").filter({ hasText: MULTI });
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: "Edit" }).click();
  // The form shows the *first* kit — it has one set of fields for two kits, which
  // is exactly why echoing them back was destructive.
  await expect(page.getByLabel("Scale")).toHaveValue(firstBefore.scale!);

  await page.getByLabel("Tracking number").fill(`TRK-MULTI-${suffix}`);
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByRole("button", { name: "Save changes" })).toBeHidden();

  const [firstAfter, secondAfter] = await kitsOf(MULTI);
  expect(secondAfter.scale).toBe("1/60");
  expect(secondAfter.kit_number).toBe("DIVERGENT");
  expect(firstAfter).toEqual(firstBefore); // and the one it did show is untouched
});

test("a warm page does not revert a kit changed while it was open", async ({ page }) => {
  // The cached kit list satisfied the old hydration gate instantly, so the form
  // snapshotted values already superseded in the database and wrote them back.
  await page.goto(`/orders?q=${encodeURIComponent(SHOP)}`);
  await expect(page.getByRole("row").filter({ hasText: MULTI })).toBeVisible();

  // From here the kit list is frozen at what the page already holds. Opening the
  // editor does trigger a refetch, and on localhost it usually wins the race — so
  // without this the test passes against the broken code and detects nothing.
  // Stalling it makes the stale window certain instead of likely.
  let release = () => {};
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/kits", async (route) => {
    await held;
    await route.continue();
  });

  const [first] = await kitsOf(MULTI);
  await patchKit(first.id, { scale: "1/48", kit_number: "CACHE-NEW" });

  // No reload: the page has been sitting there since before that change landed.
  const row = page.getByRole("row").filter({ hasText: MULTI });
  await row.getByRole("button", { name: "Edit" }).click();
  await page.getByLabel("Tracking number").fill(`TRK-WARM-${suffix}`);
  await page.getByRole("button", { name: "Save changes" }).click();
  // Released as soon as the click lands: the form's defaults were frozen at mount,
  // so the payload is already decided, and holding it any longer only blocks the
  // cache invalidation the save does on its way out.
  release();
  await expect(page.getByRole("button", { name: "Save changes" })).toBeHidden();

  const [firstAfter] = await kitsOf(MULTI);
  expect(firstAfter.scale).toBe("1/48");
  expect(firstAfter.kit_number).toBe("CACHE-NEW");
});

test("the editor hydrates from a fresh read, not the page's cache (#67)", async ({ page }) => {
  await page.goto(`/orders?q=${encodeURIComponent(SHOP)}`);
  await expect(page.getByRole("row").filter({ hasText: MULTI })).toBeVisible();

  // Lands after the page cached its list. The pre-#67 editor hydrated from that
  // cache and would render the old number here.
  const [first] = await kitsOf(MULTI);
  await patchKit(first.id, { kit_number: "FRESH-67" });

  const row = page.getByRole("row").filter({ hasText: MULTI });
  await row.getByRole("button", { name: "Edit" }).click();
  await expect(page.getByPlaceholder("Kit #")).toHaveValue("FRESH-67");
  await page.getByRole("button", { name: "Close" }).click();
});

test("a price edit does not revert a kit changed while the dialog was open (#67)", async ({
  page,
}) => {
  // The window the fresh read cannot close: the change lands *after* the form
  // hydrated. The form provably holds the older values — only the dirty-only
  // kit payload keeps it from echoing them. No stall needed: the ordering is
  // enforced by awaiting hydration (the field renders) before the change.
  await page.goto(`/orders?q=${encodeURIComponent(SHOP)}`);
  const row = page.getByRole("row").filter({ hasText: MULTI });
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: "Edit" }).click();
  await expect(page.getByPlaceholder("Kit #")).toHaveValue("FRESH-67"); // hydrated, pre-change

  const [first] = await kitsOf(MULTI);
  await patchKit(first.id, { kit_number: "MID-EDIT-67", scale: "1/35" });

  await page.getByLabel("Unit price").fill("99");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByRole("button", { name: "Save changes" })).toBeHidden();

  const [firstAfter] = await kitsOf(MULTI);
  expect(firstAfter.kit_number).toBe("MID-EDIT-67"); // survived the price edit
  expect(firstAfter.scale).toBe("1/35");
  const api = await apiContext();
  const orders = (await (await api.get("/orders")).json()) as StoredOrder[];
  await api.dispose();
  const line = orders.find((order) => order.order_number === MULTI)!.items[0];
  expect(line.unit_price_minor).not.toBe(4999); // and the edit itself landed
});

test("an order deleted under a stale row says so instead of loading forever (PR #154 review, P3-1)", async ({
  page,
}) => {
  // The fresh read's failure mode: the row is cached, the order is gone, and
  // the 404 must surface as words — not as a Loading state that never ends.
  const api = await apiContext();
  const retailers = (await (await api.get("/retailers")).json()) as { id: string; name: string }[];
  const created = (await (
    await api.post("/orders", {
      data: {
        retailer_id: retailers.find((r) => r.name === SHOP)!.id,
        order_date: "2026-08-01",
        order_number: `GONE-${suffix}`,
        currency_code: reference,
        items: [
          {
            item_type: "kit",
            quantity: 1,
            unit_price_minor: 1000,
            currency_code: reference,
            kit: { name: `${KIT} doomed`, grade: "HG" },
          },
        ],
      },
    })
  ).json()) as { id: string };

  await page.goto(`/orders?q=${encodeURIComponent(SHOP)}`);
  const row = page.getByRole("row").filter({ hasText: `GONE-${suffix}` });
  await expect(row).toBeVisible();

  // Out from under the page: deleted in another window or by an agent.
  await api.delete(`/orders/${created.id}`);
  await api.dispose();

  await row.getByRole("button", { name: "Edit" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText(/no longer exists/)).toBeVisible();
  await dialog.getByRole("button", { name: "Close" }).click();
  // The 404 also refreshed the list, so the stale row went with it.
  await expect(row).toHaveCount(0);
});

test.afterAll("clean up everything this run created", async () => {
  const api = await apiContext();
  const retailers = (await (await api.get("/retailers")).json()) as { id: string; name: string }[];
  const shop = retailers.find((retailer) => retailer.name === SHOP);
  if (shop) {
    const orders = (await (await api.get("/orders")).json()) as {
      id: string;
      retailer_id: string;
    }[];
    for (const order of orders.filter((candidate) => candidate.retailer_id === shop.id)) {
      await api.delete(`/orders/${order.id}`); // undoes the spawned kits too
    }
    await api.delete(`/retailers/${shop.id}`);
  }
  await api.dispose();
});
