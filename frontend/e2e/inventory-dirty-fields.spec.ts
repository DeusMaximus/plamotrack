/** Issue #35: an inventory edit must send what it changed, not everything it renders.
 *
 * The form shows every column of the row, and submitted every column too — so a
 * notes-only edit re-asserted an absolute `quantity_on_hand` captured when the
 * modal opened, overwriting anything a receive, an upgrade application or an MCP
 * agent had done in between. Three writer types exist by design (rule 7), which
 * is exactly why the browser must not restate a number it wasn't asked about.
 *
 * Round-trip assertions, so they live here: the API has always honoured a partial
 * PATCH (`exclude_unset`), and the defect was entirely in what the browser sent.
 */
import { expect, test } from "@playwright/test";

import { apiContext } from "./api";

const suffix = Date.now().toString(36);
const STALE_TOOL = `E2E Stale Nippers ${suffix}`;
const COUNTED_TOOL = `E2E Counted File ${suffix}`;
const PRICED_TOOL = `E2E Priced Cutter ${suffix}`;

type StoredTool = {
  id: string;
  name: string;
  quantity_on_hand: number;
  condition_notes: string | null;
  unit_cost_reference_minor: number | null;
  unit_cost_reference_currency: string | null;
};

test.describe.configure({ mode: "serial" });

async function tools(): Promise<StoredTool[]> {
  const api = await apiContext();
  const rows = (await (await api.get("/tools")).json()) as StoredTool[];
  await api.dispose();
  return rows;
}

async function tool(name: string): Promise<StoredTool> {
  return (await tools()).find((row) => row.name === name)!;
}

async function makeTool(name: string, data: Record<string, unknown>): Promise<void> {
  const api = await apiContext();
  const created = await api.post("/tools", { data: { name, category: "cutting", ...data } });
  expect(created.status(), await created.text()).toBe(201);
  await api.dispose();
}

async function patchTool(id: string, data: Record<string, unknown>): Promise<void> {
  const api = await apiContext();
  const patched = await api.patch(`/tools/${id}`, { data });
  expect(patched.status(), await patched.text()).toBe(200);
  await api.dispose();
}

/** Open the tool's edit dialog on the Inventory page. */
async function openEditor(page: import("@playwright/test").Page, name: string) {
  await page.goto("/inventory");
  const row = page.getByRole("row").filter({ hasText: name });
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: "Edit" }).click();
  return page.getByRole("dialog");
}

test.beforeAll("seed three tools", async () => {
  await makeTool(STALE_TOOL, { quantity_on_hand: 5, condition_notes: "before" });
  await makeTool(COUNTED_TOOL, { quantity_on_hand: 5 });
  await makeTool(PRICED_TOOL, {
    quantity_on_hand: 1,
    unit_cost_reference_minor: 4500,
    unit_cost_reference_currency: "AUD",
  });
});

test("a notes-only edit does not resurrect a stale stock count", async ({ page }) => {
  const before = await tool(STALE_TOOL);
  const dialog = await openEditor(page, STALE_TOOL);
  await expect(dialog.getByLabel("Quantity on hand")).toHaveValue("5");

  // Another writer moves the stock while the form sits open — a receive, an
  // upgrade application, or an agent. The form's copy is now stale.
  await patchTool(before.id, { quantity_on_hand: 9 });

  await dialog.getByLabel("Condition notes").fill("after");
  await dialog.getByRole("button", { name: "Add", exact: true }).click();
  await expect(dialog).toBeHidden();

  const after = await tool(STALE_TOOL);
  expect(after.condition_notes).toBe("after"); // the edit happened
  expect(after.quantity_on_hand).toBe(9); // and said nothing about stock
});

test("an edit that does change the stock still sends it", async ({ page }) => {
  // The control on the test above: "never send quantity" would also pass it.
  const dialog = await openEditor(page, COUNTED_TOOL);
  await dialog.getByLabel("Quantity on hand").fill("3");
  await dialog.getByRole("button", { name: "Add", exact: true }).click();
  await expect(dialog).toBeHidden();

  expect((await tool(COUNTED_TOOL)).quantity_on_hand).toBe(3);
});

test("changing only the cost currency rescales the amount with it", async ({ page }) => {
  // Guards the fix rather than the original defect: sending the whole row was
  // accidentally consistent here, and filtering by dirty field is what makes the
  // cost pair breakable. A$45.00 is 4500 minor and ¥45 is 45, so a dropdown that
  // moves without its amount stores ¥4500 — a hundredfold error introduced by the
  // repair. Confirmed to fail if PAYLOAD_SOURCES stops pairing the two.
  const dialog = await openEditor(page, PRICED_TOOL);
  await expect(dialog.getByLabel("Reference cost")).toHaveValue("45.00");
  await dialog.getByLabel("Cost currency").selectOption("JPY");
  await dialog.getByRole("button", { name: "Add", exact: true }).click();
  await expect(dialog).toBeHidden();

  const after = await tool(PRICED_TOOL);
  expect(after.unit_cost_reference_currency).toBe("JPY");
  expect(after.unit_cost_reference_minor).toBe(45);
});

test.afterAll("clean up everything this run created", async () => {
  const api = await apiContext();
  for (const row of await tools()) {
    if (row.name.startsWith("E2E ") && row.name.endsWith(suffix)) {
      await api.delete(`/tools/${row.id}`);
    }
  }
  await api.dispose();
});
