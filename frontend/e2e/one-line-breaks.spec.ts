/** A line break stored in a one-line field (#361).
 *
 *  REST, MCP and the importer accept a line break in a field the dialogs edit
 *  in a one-line box. A text input cannot hold one: the browser strips it from
 *  the value, so the box showed the two words joined, and typing anything into
 *  it saved them joined. The editor is made honest instead of the writers
 *  changing (the owner's call on #361): a stored break shows as a space, so an
 *  edit stores what was on screen. A field that never had focus keeps its
 *  break, because the form sends the value it loaded, not the box's. A field
 *  that had focus can be saved as the box showed it, typed into or not:
 *  react-hook-form copies the box's value into the form on blur. The fields
 *  this file calls untouched are never focused.
 *
 *  Each break is driven as `\n` and as `\r\n`, one dialog of each kind: the
 *  order dialog (a kit line's name, an Other line's description, the order
 *  number), the kit dialog (name, series), the retailer dialog (name) and the
 *  catalog dialog (a tool's name; its condition notes are notes, a textarea
 *  that shows the break since #376, `multiline-notes.spec.ts`). The rows are seeded
 *  through REST — the browser cannot write a break — and removed after.
 *
 *  Each display check is soft, so a run against the unfixed dialogs still
 *  saves and shows what it stored: the two words joined. */
import { expect, type Locator, type Page, test } from "@playwright/test";

import { apiContext } from "./api";
import { openListAt } from "./listRows";

const suffix = Date.now().toString(36);

const BREAKS = [
  { label: "LF", br: "\n" },
  { label: "CRLF", br: "\r\n" },
] as const;

test.use({ viewport: { width: 1440, height: 900 } });

/** Type one character at the end of a box, as a person would: a keystroke, not
 *  `fill`, which would replace the value instead of editing what is shown. */
async function typeAtEnd(page: Page, field: Locator, text: string): Promise<void> {
  await field.focus();
  await field.evaluate((input: HTMLInputElement) => {
    input.setSelectionRange(input.value.length, input.value.length);
  });
  await page.keyboard.type(text);
}

type Cleanup = () => Promise<void>;
const cleanups: Cleanup[] = [];
let reference: string; // this instance's currency, for the seeded order

test.beforeAll(async () => {
  reference = (await get<{ reference_currency: string }>("/meta")).reference_currency;
});

test.afterAll(async () => {
  for (const cleanup of cleanups.reverse()) await cleanup();
});

async function post<T>(path: string, data: unknown): Promise<T> {
  const api = await apiContext();
  const resp = await api.post(path, { data });
  expect(resp.status(), await resp.text()).toBe(201);
  const body = (await resp.json()) as T;
  await api.dispose();
  return body;
}

async function get<T>(path: string): Promise<T> {
  const api = await apiContext();
  const resp = await api.get(path);
  expect(resp.ok(), await resp.text()).toBeTruthy();
  const body = (await resp.json()) as T;
  await api.dispose();
  return body;
}

function removeLater(path: string): void {
  cleanups.push(async () => {
    const api = await apiContext();
    await api.delete(path);
    await api.dispose();
  });
}

type StoredOrder = {
  id: string;
  order_number: string | null;
  tracking_number: string | null;
  items: { item_type: string; description: string | null; kits: { name: string; series: string | null }[] }[];
};

for (const { label, br } of BREAKS) {
  const tag = `${label}-${suffix}`;

  test.describe(`a stored ${label}`, () => {
    test("order dialog: a typed field stores the space it showed; untouched ones keep the break", async ({
      page,
    }) => {
      const shop = `E2E Break Shop ${tag}`;
      const kitName = `E2E Break Kit ${tag}${br}second line`;
      const description = `E2E Break Mag ${tag}${br}March issue`;
      const orderNumber = `BRK-${tag}${br}part two`;
      const retailer = await post<{ id: string }>("/retailers", { name: shop });
      removeLater(`/retailers/${retailer.id}`);
      const created = await post<StoredOrder>("/orders", {
        retailer_id: retailer.id,
        order_date: "2026-11-01",
        order_number: orderNumber,
        currency_code: reference,
        items: [
          {
            item_type: "kit",
            quantity: 1,
            unit_price_minor: 2000,
            currency_code: reference,
            kit: { name: kitName, grade: "HG" },
          },
          { item_type: "other", quantity: 1, unit_price_minor: 500, currency_code: reference, description },
        ],
      });
      removeLater(`/orders/${created.id}`);
      // Control: REST stored the breaks the rest of this test reads.
      expect(created.order_number).toBe(orderNumber);
      expect(created.items[0].kits[0].name).toBe(kitName);
      expect(created.items[1].description).toBe(description);

      const open = async () => {
        await page.goto(`/orders?q=${encodeURIComponent(shop)}`);
        await page.getByRole("row").filter({ hasText: shop }).getByRole("button", { name: "Edit" }).click();
        return page.getByRole("dialog", { name: "Edit order" });
      };

      // One edit that touches neither: the tracking number.
      let dialog = await open();
      const kitBox = dialog.getByPlaceholder("Kit name *");
      const descriptionBox = dialog.getByLabel("Description");
      const orderNumberBox = dialog.getByLabel("Order number");
      await expect.soft(kitBox).toHaveValue(`E2E Break Kit ${tag} second line`);
      await expect.soft(descriptionBox).toHaveValue(`E2E Break Mag ${tag} March issue`);
      await expect.soft(orderNumberBox).toHaveValue(`BRK-${tag} part two`);
      await dialog.getByLabel("Tracking number").fill(`TRK-${tag}`);
      await dialog.getByRole("button", { name: "Save changes" }).click();
      await expect(dialog).toBeHidden();

      let stored = await get<StoredOrder>(`/orders/${created.id}`);
      expect(stored.tracking_number).toBe(`TRK-${tag}`); // the edit happened
      expect(stored.order_number).toBe(orderNumber);
      expect(stored.items[0].kits[0].name).toBe(kitName);
      expect(stored.items[1].description).toBe(description);

      // One character typed into the kit name and the description; the order
      // number is still left alone.
      dialog = await open();
      await typeAtEnd(page, dialog.getByPlaceholder("Kit name *"), "!");
      await typeAtEnd(page, dialog.getByLabel("Description"), "!");
      await dialog.getByRole("button", { name: "Save changes" }).click();
      await expect(dialog).toBeHidden();

      stored = await get<StoredOrder>(`/orders/${created.id}`);
      expect(stored.items[0].kits[0].name).toBe(`E2E Break Kit ${tag} second line!`);
      expect(stored.items[1].description).toBe(`E2E Break Mag ${tag} March issue!`);
      expect(stored.order_number).toBe(orderNumber);
    });

    test("kit dialog: the name typed into, the series left alone", async ({ page }) => {
      const name = `E2E Break Lone Kit ${tag}${br}second line`;
      const series = `E2E Series ${tag}${br}Iron-Blooded`;
      const kit = await post<{ id: string }>("/kits", { name, grade: "HG", series });
      removeLater(`/kits/${kit.id}`);

      await page.goto(`/kits?q=${encodeURIComponent(`E2E Break Lone Kit ${tag}`)}`);
      await page
        .getByRole("row")
        .filter({ hasText: `E2E Break Lone Kit ${tag}` })
        .getByRole("button", { name: /^Edit / })
        .click();
      const dialog = page.getByRole("dialog");
      await expect.soft(dialog.getByLabel("Name")).toHaveValue(`E2E Break Lone Kit ${tag} second line`);
      await expect.soft(dialog.getByLabel("Series")).toHaveValue(`E2E Series ${tag} Iron-Blooded`);
      await typeAtEnd(page, dialog.getByLabel("Name"), "!");
      await dialog.getByRole("button", { name: "Save", exact: true }).click();
      await expect(dialog).toBeHidden();

      const stored = await get<{ name: string; series: string | null }>(`/kits/${kit.id}`);
      expect(stored.name).toBe(`E2E Break Lone Kit ${tag} second line!`);
      expect(stored.series).toBe(series);
    });

    test("retailer dialog: the name typed into", async ({ page }) => {
      const name = `E2E Break Lone Shop ${tag}${br}Akihabara`;
      const retailer = await post<{ id: string }>("/retailers", { name });
      removeLater(`/retailers/${retailer.id}`);

      await page.goto(`/retailers?q=${encodeURIComponent(`E2E Break Lone Shop ${tag}`)}`);
      await page
        .getByRole("row")
        .filter({ hasText: `E2E Break Lone Shop ${tag}` })
        .getByRole("button", { name: /^Edit / })
        .click();
      const dialog = page.getByRole("dialog");
      await expect.soft(dialog.getByLabel("Name")).toHaveValue(`E2E Break Lone Shop ${tag} Akihabara`);
      await typeAtEnd(page, dialog.getByLabel("Name"), "!");
      await dialog.getByRole("button", { name: "Save", exact: true }).click();
      await expect(dialog).toBeHidden();

      const stored = (await get<{ id: string; name: string }[]>("/retailers")).find(
        (row) => row.id === retailer.id,
      )!;
      expect(stored.name).toBe(`E2E Break Lone Shop ${tag} Akihabara!`);
    });

    test("catalog dialog: a tool's name typed into, its condition notes left alone", async ({ page }) => {
      const name = `E2E Break Nippers ${tag}${br}single blade`;
      const notes = `Blade chipped${br}still cuts`;
      const tool = await post<{ id: string }>("/tools", {
        name,
        category: "cutting",
        condition_notes: notes,
      });
      removeLater(`/tools/${tool.id}`);

      await openListAt(page, "/inventory", `E2E Break Nippers ${tag}`);
      await page
        .getByRole("row")
        .filter({ hasText: `E2E Break Nippers ${tag}` })
        .getByRole("button", { name: /^Edit / })
        .click();
      const dialog = page.getByRole("dialog");
      await expect.soft(dialog.getByLabel("Name")).toHaveValue(`E2E Break Nippers ${tag} single blade`);
      await expect.soft(dialog.getByLabel("Condition notes")).toHaveValue("Blade chipped\nstill cuts");
      await typeAtEnd(page, dialog.getByLabel("Name"), "!");
      await dialog.getByRole("button", { name: "Save", exact: true }).click();
      await expect(dialog).toBeHidden();

      const stored = (await get<{ id: string; name: string; condition_notes: string | null }[]>("/tools")).find(
        (row) => row.id === tool.id,
      )!;
      expect(stored.name).toBe(`E2E Break Nippers ${tag} single blade!`);
      expect(stored.condition_notes).toBe(notes);
    });
  });
}
