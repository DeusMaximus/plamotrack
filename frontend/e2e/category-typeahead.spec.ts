import { expect, request, test } from "@playwright/test";

/**
 * #130 review, P3-4 — two new-item lines in one order dialog each get their OWN
 * category vocabulary.
 *
 * The category datalist id was a shared literal, and an HTML `list` attribute
 * resolves against the document: with a tool line and a consumable line both in
 * "new item" mode, both inputs resolved to whichever datalist rendered first,
 * so the consumable line offered the tool vocabulary. A single-line hand loop
 * cannot see this — it needs two simultaneous pickers — hence this spec. The
 * assertion reads each input's *resolved* `input.list.options`, which is the
 * browser's answer, not the JSX's.
 */

const API = "http://127.0.0.1:8000";
const suffix = Date.now().toString(36);
const TOOL = `E2E CatList Tool ${suffix}`;
const CONSUMABLE = `E2E CatList Consumable ${suffix}`;
const TOOL_CATEGORY = `e2e-cat-tools-${suffix}`;
const CONSUMABLE_CATEGORY = `e2e-cat-paint-${suffix}`;

test("each new-item line resolves its own category vocabulary", async ({ page }) => {
  const api = await request.newContext({ baseURL: API });
  await api.post("/tools", { data: { name: TOOL, category: TOOL_CATEGORY } });
  await api.post("/consumables", { data: { name: CONSUMABLE, category: CONSUMABLE_CATEGORY } });
  await api.dispose();

  await page.goto("/orders");
  await page.getByRole("button", { name: "+ New order" }).click();

  // Line 1: a new tool. Line 2: a new consumable — both pickers in "new item"
  // mode at once, which is the state the shared id could not survive.
  await page.locator('select:has(option[value="consumable"])').first().selectOption("tool");
  await page.getByPlaceholder("Search tools…").fill(`New nipper ${suffix}`);
  await page.getByRole("button", { name: /Create new tool/ }).click();

  await page.getByRole("button", { name: "+ Add line" }).click();
  await page.locator('select:has(option[value="consumable"])').nth(1).selectOption("consumable");
  await page.getByPlaceholder("Search consumables…").fill(`New paint ${suffix}`);
  await page.getByRole("button", { name: /Create new consumable/ }).click();

  const categoryInputs = page.getByPlaceholder("Category (required)", { exact: true });
  await expect(categoryInputs).toHaveCount(2);
  const resolved = async (nth: number) =>
    categoryInputs
      .nth(nth)
      .evaluate((el: HTMLInputElement) => Array.from(el.list?.options ?? []).map((o) => o.value));

  const toolOptions = await resolved(0);
  const consumableOptions = await resolved(1);
  expect(toolOptions).toContain(TOOL_CATEGORY);
  expect(toolOptions).not.toContain(CONSUMABLE_CATEGORY);
  expect(consumableOptions).toContain(CONSUMABLE_CATEGORY);
  expect(consumableOptions).not.toContain(TOOL_CATEGORY);

  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test.afterAll("clean up everything this run created", async () => {
  const api = await request.newContext({ baseURL: API });
  const tools = (await (await api.get("/tools")).json()) as { id: string; name: string }[];
  for (const t of tools.filter((t) => t.name === TOOL)) await api.delete(`/tools/${t.id}`);
  const consumables = (await (await api.get("/consumables")).json()) as {
    id: string;
    name: string;
  }[];
  for (const c of consumables.filter((c) => c.name === CONSUMABLE))
    await api.delete(`/consumables/${c.id}`);
  await api.dispose();
});
