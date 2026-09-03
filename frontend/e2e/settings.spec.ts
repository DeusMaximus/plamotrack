/** Issue #24: the Settings page — sections, the /data redirect, and the
 * reference-currency save round-trip.
 *
 * This file mutates the instance-settings singleton, which is the one piece of
 * state every other spec shares: order-snapshot and order-lossless read the
 * instance currency in a beforeAll and assert stamps against it. The config
 * therefore runs this file in its own project, after everything else — see the
 * `settings` project in playwright.config.ts. The original value is restored
 * in afterAll whether the tests pass or not.
 */
import { expect, test } from "@playwright/test";

import { apiContext } from "./api";

test.describe.configure({ mode: "serial" });

let original: {
  reference_currency: string;
  interface_language: string;
  formatting_locale: string;
  time_zone: string;
  date_style: string;
  hour_cycle: string;
};
let version: string;
let target: string; // a valid code that differs from the stored one

test.beforeAll("read the instance settings and version", async () => {
  const api = await apiContext();
  original = (await (await api.get("/settings")).json()) as typeof original;
  version = ((await (await api.get("/meta")).json()) as { version: string }).version;
  target = original.reference_currency === "NZD" ? "CAD" : "NZD";
  await api.dispose();
});

test.afterAll("restore the instance settings", async () => {
  const api = await apiContext();
  await api.patch("/settings", {
    data: {
      reference_currency: original.reference_currency,
      interface_language: original.interface_language,
      formatting_locale: original.formatting_locale,
      time_zone: original.time_zone,
      date_style: original.date_style,
      hour_cycle: original.hour_cycle,
    },
  });
  await api.dispose();
});

test("Settings replaces Data in the sidebar and the sections navigate", async ({ page }) => {
  await page.goto("/board");
  await expect(page.getByRole("link", { name: "Settings" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Data", exact: true })).toHaveCount(0);

  await page.getByRole("link", { name: "Settings" }).click();
  await expect(page).toHaveURL(/\/settings\/general$/);
  await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 2, name: "General" })).toBeVisible();

  await page.getByRole("link", { name: "Language & region" }).click();
  await expect(page).toHaveURL(/\/settings\/language$/);
  // A form since #27 — the stored zone hydrates the input, no longer a read-only row.
  await expect(page.getByLabel("Time zone")).toHaveValue(original.time_zone);

  await page.getByRole("link", { name: "About" }).click();
  await expect(page).toHaveURL(/\/settings\/about$/);
  await expect(page.getByText(version, { exact: true })).toBeVisible();
});

test("the old /data URL lands on Data management with the import workflow intact", async ({
  page,
}) => {
  await page.goto("/data");
  await expect(page).toHaveURL(/\/settings\/data$/);
  await expect(page.getByRole("heading", { level: 2, name: "Data management" })).toBeVisible();
  // The pieces of the import workflow the move must not lose: file selection,
  // the mode choice, and the preview gate in front of Apply.
  await expect(page.getByText("Drop a .csv or .zip here")).toBeVisible();
  await expect(page.getByLabel("If something already exists")).toBeVisible();
  await expect(page.getByRole("button", { name: "Preview changes" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Download full archive (.zip)" })).toBeVisible();
});

test("the currency form loads behind an accessible loading state", async ({ page }) => {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => (release = resolve));
  await page.route("**/api/settings", async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await gate; // held until the loading state has been observed — no sleep
    await route.continue();
  });
  await page.goto("/settings/general");
  await expect(page.getByText("Loading…")).toBeVisible();
  release();
  await expect(page.getByLabel("Currency code")).toHaveValue(original.reference_currency);
  // Pristine form: nothing to save yet.
  await expect(page.getByRole("button", { name: "Save" })).toBeDisabled();
  await page.unroute("**/api/settings");
});

test("a malformed currency code is refused client-side with a field error", async ({ page }) => {
  await page.goto("/settings/general");
  const input = page.getByLabel("Currency code");
  await expect(input).toHaveValue(original.reference_currency);
  await input.fill("eu1");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("3-letter ISO code")).toBeVisible();
  // Nothing reached the server.
  const api = await apiContext();
  const row = (await (await api.get("/settings")).json()) as { reference_currency: string };
  await api.dispose();
  expect(row.reference_currency).toBe(original.reference_currency);
});

test("a failed save surfaces an accessible error and keeps the edit", async ({ page }) => {
  await page.route("**/api/settings", (route) =>
    route.request().method() === "PATCH" ? route.abort("failed") : route.fallback(),
  );
  await page.goto("/settings/general");
  const input = page.getByLabel("Currency code");
  await expect(input).toHaveValue(original.reference_currency);
  await input.fill(target);
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("alert")).toHaveText("Request failed");
  await expect(input).toHaveValue(target);
});

test("saving the currency persists it and refreshes the order form's default", async ({
  page,
}) => {
  // Warm the /meta cache (staleTime: Infinity) first: the save must invalidate
  // it, or the order form keeps defaulting to the old currency until a reload.
  await page.goto("/orders");
  await page.getByRole("link", { name: "Settings" }).click();

  const input = page.getByLabel("Currency code");
  await expect(input).toHaveValue(original.reference_currency);
  await input.fill(target);
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("status")).toHaveText("Saved");

  // Persisted on the instance, not just in this form.
  const api = await apiContext();
  const row = (await (await api.get("/settings")).json()) as { reference_currency: string };
  await api.dispose();
  expect(row.reference_currency).toBe(target);

  // Same SPA session, no reload: the new default reaches the order form.
  await page.getByRole("link", { name: "Orders" }).click();
  await page.getByRole("button", { name: "+ New order" }).click();
  await expect(page.getByLabel("Currency").first()).toHaveValue(target);
});

test("the language form hydrates from the row and the document carries its metadata (#27)", async ({
  page,
}) => {
  await page.goto("/settings/language");
  await expect(page.getByLabel("Interface language")).toHaveValue(original.interface_language);
  await expect(page.getByLabel("Formatting locale")).toHaveValue(original.formatting_locale);
  await expect(page.getByLabel("Time zone")).toHaveValue(original.time_zone);
  await expect(page.getByLabel("Date style")).toHaveValue(original.date_style);
  await expect(page.getByLabel("Hour cycle")).toHaveValue(original.hour_cycle);
  // The Layout effect stamped the resolved language onto the document itself.
  await expect(page.locator("html")).toHaveAttribute("lang", "en-AU");
  await expect(page.locator("html")).toHaveAttribute("dir", "ltr");
  // Pristine form: nothing to save yet.
  await expect(page.getByRole("button", { name: "Save" })).toBeDisabled();
});

test("saving regional settings re-renders visible dates in the same session (#27)", async ({
  page,
}) => {
  // A kit whose completion instant is unambiguous across the zones involved:
  // 04:00Z is 14/03 in UTC and 15:00 on 14/03 in Sydney.
  const api = await apiContext();
  const kit = (await (
    await api.post("/kits", {
      data: {
        name: `e2e-27-format-${Date.now()}`,
        grade: "HG",
        status: "complete",
        build_completed_at: "2026-03-14T04:00:00+00:00",
      },
    })
  ).json()) as { id: string };

  try {
    await page.goto("/kits");
    await expect(page.getByText("14/03/2026").first()).toBeVisible();

    await page.goto("/settings/language");
    await page.getByLabel("Time zone").fill("Australia/Sydney");
    await page.getByLabel("Date style").selectOption("long");
    await page.getByLabel("Hour cycle").selectOption("h23");
    // The live draft preview re-renders before anything is saved.
    await expect(page.getByTestId("format-preview")).toContainText("14 March 2026");
    await expect(page.getByTestId("format-preview")).toContainText("15:00");
    await page.getByRole("button", { name: "Save" }).click();
    await expect(page.getByRole("status")).toHaveText("Saved");

    // Same SPA session, no reload: the Kits page renders the new shape.
    await page.getByRole("link", { name: "Kits" }).click();
    await expect(page.getByText("14 March 2026").first()).toBeVisible();
  } finally {
    await api.delete(`/kits/${kit.id}`);
    await api.dispose();
  }
});

test("a cold page load re-renders once the settings row arrives (#174 review, P3-1)", async ({
  page,
}) => {
  // The prior test saved Sydney/long/h23; restate it so this test stands alone.
  const api = await apiContext();
  await api.patch("/settings", {
    data: { time_zone: "Australia/Sydney", date_style: "long", hour_cycle: "h23" },
  });
  const kit = (await (
    await api.post("/kits", {
      data: {
        name: `e2e-27-coldload-${Date.now()}`,
        grade: "HG",
        status: "complete",
        build_completed_at: "2026-03-14T04:00:00+00:00",
      },
    })
  ).json()) as { id: string };

  try {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => (release = resolve));
    await page.route("**/api/settings", async (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await gate; // the kits list resolves first — the window under test
      await route.continue();
    });
    await page.goto("/kits");
    // Rendered under the boot defaults while the settings row is held.
    await expect(page.getByText("14/03/2026").first()).toBeVisible();
    release();
    // No focus cycle, no navigation, no interaction: the row's arrival alone
    // must re-render what is already on screen with the applied preferences.
    await expect(page.getByText("14 March 2026").first()).toBeVisible();
    await page.unroute("**/api/settings");
  } finally {
    await api.delete(`/kits/${kit.id}`);
    await api.dispose();
  }
});


test("a cold Board load re-renders its counts once the settings row arrives (#177 review, P3-1)", async ({
  page,
}) => {
  // The locale axis, not the zone axis: `interface_language` stays en-AU, so
  // `useTranslation`'s languageChanged re-render cannot be what makes this
  // pass — only a presentation subscription can. ar-EG because its digits are
  // visibly not the boot locale's, so the assertion reads the rendering rather
  // than a value that happens to agree.
  const api = await apiContext();
  await api.patch("/settings", { data: { formatting_locale: "ar-EG" } });
  const kit = (await (
    await api.post("/kits", {
      data: { name: `e2e-177-boardcount-${Date.now()}`, grade: "HG", status: "backlog" },
    })
  ).json()) as { id: string };

  try {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => (release = resolve));
    await page.route("**/api/settings", async (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await gate; // the kits list resolves first — the window under test
      await route.continue();
    });
    await page.goto("/board");
    const count = page.getByTestId("column-count-backlog");
    // Boot defaults while the row is held: Western digits, and at least the
    // kit just created, so this is not asserting an empty column.
    await expect(count).toHaveText(/^[0-9]+$/);
    const western = await count.textContent();
    expect(Number(western)).toBeGreaterThan(0);

    release();
    // No navigation, no interaction: the row's arrival alone must re-render a
    // count already on screen.
    await expect(count).toHaveText(/^[\u0660-\u0669]+$/);
    await page.unroute("**/api/settings");
  } finally {
    await api.delete(`/kits/${kit.id}`);
    await api.patch("/settings", { data: { formatting_locale: original.formatting_locale } });
    await api.dispose();
  }
});
