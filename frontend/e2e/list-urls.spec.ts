/** #232 (design §13.4): a list page's state is its URL. A link lands filtered
 *  and sorted, the controls write the URL back, the page is a parameter that a
 *  shrinking list clamps rather than breaks, and the row's one control opens
 *  the dialog where Delete now lives. Fourteen kits of this run's own, scoped
 *  by the search so a populated dev database changes nothing. */
import { expect, test } from "@playwright/test";

import { apiContext } from "./api";

const suffix = Date.now().toString(36);
const PREFIX = `E2E ListUrl Kit ${suffix}`;
const name = (n: number) => `${PREFIX} ${String(n).padStart(2, "0")}`;
const created: string[] = [];

test.beforeAll(async () => {
  const api = await apiContext();
  // Eleven building (two pages of ten), three backlog.
  for (let n = 1; n <= 14; n += 1) {
    const resp = await api.post("/kits", {
      data: { name: name(n), grade: "HG", status: n <= 11 ? "building" : "backlog" },
    });
    expect(resp.ok(), await resp.text()).toBeTruthy();
    created.push(((await resp.json()) as { id: string }).id);
  }
  await api.dispose();
});

test.afterAll(async () => {
  const api = await apiContext();
  for (const id of created) await api.delete(`/kits/${id}`); // a 404 is a row the test deleted
  await api.dispose();
});

const ours = (page: import("@playwright/test").Page) =>
  page.getByRole("row").filter({ hasText: PREFIX });

test("a link lands filtered and sorted; the controls and the pager write the URL back", async ({
  page,
}) => {
  await page.goto(`/kits?status=building&sort=recent&q=${encodeURIComponent(PREFIX)}`);
  await expect(page.getByLabel("Filter by status")).toHaveValue("building");
  await expect(page.getByLabel("Sort")).toHaveValue("recent");
  await expect(page.getByLabel("Search")).toHaveValue(PREFIX);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(/Kits\s*11/);
  await expect(ours(page)).toHaveCount(10);
  await expect(page.getByText("1–10 of 11")).toBeVisible();

  // The pager is URL state.
  await page.getByRole("navigation", { name: "Pages" }).getByRole("button", { name: "Page 2" }).click();
  await expect(page).toHaveURL(/[?&]page=2(&|$)/);
  await expect(ours(page)).toHaveCount(1);
  await expect(page.getByText("11–11 of 11")).toBeVisible();

  // A filter change resets the page and writes itself.
  await page.getByLabel("Filter by status").selectOption("backlog");
  await expect(page).toHaveURL(/[?&]status=backlog(&|$)/);
  await expect(page).not.toHaveURL(/[?&]page=/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(/Kits\s*3/);
  await expect(ours(page)).toHaveCount(3);

  // The default sort leaves the URL clean; a chosen one is in it.
  await page.getByLabel("Sort").selectOption("name");
  await expect(page).toHaveURL(/[?&]sort=name(&|$)/);
  await page.getByLabel("Sort").selectOption("recent");
  await expect(page).not.toHaveURL(/[?&]sort=/);
});

test("a page past the end clamps onto the last page", async ({ page }) => {
  await page.goto(`/kits?status=building&q=${encodeURIComponent(PREFIX)}&page=99`);
  await expect(ours(page)).toHaveCount(1);
  await expect(
    page.getByRole("navigation", { name: "Pages" }).getByRole("button", { name: "Page 2" }),
  ).toHaveAttribute("aria-current", "page");
});

test("the row's one control opens the dialog, and Delete lives there", async ({ page }) => {
  page.on("dialog", (dialog) => dialog.accept());
  await page.goto(`/kits?status=backlog&q=${encodeURIComponent(PREFIX)}`);
  const row = ours(page).filter({ hasText: name(14) });
  await expect(row).toBeVisible();
  await expect(row.getByRole("button")).toHaveCount(1);
  await row.getByRole("button", { name: `Edit ${name(14)}` }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Delete" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(row).toHaveCount(0);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(/Kits\s*2/);
});

test("the orders page reads its sort and status from the URL too", async ({ page }) => {
  await page.goto("/orders?sort=recent&status=received");
  await expect(page.getByLabel("Sort")).toHaveValue("recent");
  await expect(page.getByLabel("Filter by status")).toHaveValue("received");
});
