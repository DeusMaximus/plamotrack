import { expect, test } from "@playwright/test";

/** TEMPORARY — remove before merge.
 *
 * Fails on purpose so the `if: failure()` upload in the Integration job runs at
 * least once while someone is watching. An artifact step that has never fired is
 * a guess, and this PR exists because the evidence went missing exactly when it
 * was needed. */
test("deliberate failure: proves the artifact upload works", async ({ page }) => {
  await page.goto("/orders");
  await expect(page.getByRole("button", { name: "This button does not exist" })).toBeVisible({
    timeout: 2000,
  });
});
