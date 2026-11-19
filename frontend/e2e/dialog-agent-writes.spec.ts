/** Issue #358, the sweep: every edit dialog holds a copy of its record from when
 *  it opened, and an agent can write the record in the meantime. A save restates
 *  only what the person changed, so everything the agent wrote stands.
 *
 *  The order dialog has its own file (order-lossless.spec.ts). These are the
 *  others, asked the same question the same way: open the dialog, write every
 *  other field through REST, change only the name in the dialog, save, read the
 *  row back. Each record is seeded with a value in every field, and every value
 *  the agent writes differs from it, so the stored row says which writer won. */
import { expect, type Page, test } from "@playwright/test";

import { apiContext } from "./api";
import { openListAt } from "./listRows";

const suffix = Date.now().toString(36);

type Case = {
  /** The collection's REST path, which is also how the row is read back. */
  path: string;
  /** Where the row is listed, and how a test reaches its dialog. */
  open: (page: Page, name: string) => Promise<void>;
  seed: Record<string, unknown>;
  agent: Record<string, unknown>;
};

const byQuery = (list: string) => async (page: Page, name: string) => {
  await page.goto(`${list}?q=${encodeURIComponent(name)}`);
};
const onInventory = (tab: string) => async (page: Page, name: string) => {
  await openListAt(page, `/inventory?tab=${tab}`, name);
};

const CASES: Record<string, Case> = {
  kit: {
    path: "/kits",
    open: byQuery("/kits"),
    seed: {
      grade: "HG",
      scale: "1/144",
      kit_number: "OPENING-NO",
      series: "Opening Series",
      status: "complete",
      rating: 3,
      build_notes: "The notes it opened with.",
    },
    agent: {
      grade: "RG",
      scale: "1/100",
      kit_number: "AGENT-NO",
      series: "Agent Series",
      status: "building",
      rating: 5,
      build_notes: "Notes an agent wrote while the dialog was open.",
    },
  },
  retailer: {
    path: "/retailers",
    open: byQuery("/retailers"),
    seed: {
      url: "https://shop.example/opening",
      rating: 3,
      packing_quality: "average",
      shipping_speed: "average",
      would_order_again: "maybe",
      notes: "The notes it opened with.",
    },
    agent: {
      url: "https://shop.example/agent",
      rating: 5,
      packing_quality: "excellent",
      shipping_speed: "very_fast",
      would_order_again: "yes",
      notes: "Notes an agent wrote while the dialog was open.",
    },
  },
  tool: {
    path: "/tools",
    open: onInventory("tools"),
    seed: {
      category: "cutting",
      quantity_on_hand: 1,
      condition_notes: "The notes it opened with.",
      unit_cost_reference_minor: 1000,
      unit_cost_reference_currency: "AUD",
    },
    agent: {
      category: "sanding",
      quantity_on_hand: 7,
      condition_notes: "Notes an agent wrote while the dialog was open.",
      unit_cost_reference_minor: 2500,
      unit_cost_reference_currency: "JPY",
    },
  },
  consumable: {
    path: "/consumables",
    open: onInventory("consumables"),
    seed: { category: "cement", quantity_on_hand: 1, low_stock_threshold: 1 },
    agent: { category: "paint", quantity_on_hand: 7, low_stock_threshold: 4 },
  },
  upgrade: {
    path: "/upgrades",
    open: onInventory("upgrades"),
    seed: { manufacturer: "Opening Works", quantity_on_hand: 1 },
    agent: { manufacturer: "Agent Works", quantity_on_hand: 7 },
  },
  "display item": {
    path: "/display-items",
    open: onInventory("display-items"),
    seed: {
      category: "stand",
      scale: "1/144",
      manufacturer: "Opening Works",
      quantity_on_hand: 1,
      notes: "The notes it opened with.",
    },
    agent: {
      category: "base",
      scale: "1/100",
      manufacturer: "Agent Works",
      quantity_on_hand: 7,
      notes: "Notes an agent wrote while the dialog was open.",
    },
  },
};

for (const [label, { path, open, seed, agent }] of Object.entries(CASES)) {
  test(`${label} dialog: a save that changed only the name leaves what an agent wrote`, async ({ page }) => {
    const name = `E2E Agent Writes ${label} ${suffix}`;
    const api = await apiContext();
    const created = await api.post(path, { data: { name, ...seed } });
    expect(created.status(), await created.text()).toBe(201);
    const { id } = (await created.json()) as { id: string };
    const read = async () =>
      ((await (await api.get(path)).json()) as Record<string, unknown>[]).find((row) => row.id === id)!;

    try {
      await open(page, name);
      await page.getByRole("row").filter({ hasText: name }).getByRole("button", { name: /^Edit / }).click();
      const dialog = page.getByRole("dialog");
      // Hydrated: the dialog holds its copy, so the write below is "meanwhile".
      await expect(dialog.getByLabel("Name")).toHaveValue(name);

      const written = await api.patch(`${path}/${id}`, { data: agent });
      expect(written.status(), await written.text()).toBe(200);
      expect(await read()).toMatchObject(agent); // control: the agent's write landed

      await dialog.getByLabel("Name").fill(`${name}!`);
      await dialog.getByRole("button", { name: "Save", exact: true }).click();
      await expect(dialog).toBeHidden();

      const stored = await read();
      expect(stored.name).toBe(`${name}!`); // the save happened
      expect(stored).toMatchObject(agent);
    } finally {
      await api.delete(`${path}/${id}`);
      await api.dispose();
    }
  });
}
