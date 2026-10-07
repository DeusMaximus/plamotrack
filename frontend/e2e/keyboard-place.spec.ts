/**
 * A control pressed from the keyboard keeps its place (#268).
 *
 * Disabling the focused control drops the keyboard to `<body>`, and outside a
 * dialog nothing gave it back: the next Tab started from the top of the page.
 * Two answers, one per kind of control. One that is only *waiting* on its own
 * request keeps the keyboard (`Button`'s `pending`, `aria-disabled`) and refuses
 * a second press. One that *cannot act any more* — disabled, or gone — hands the
 * keyboard to the control it names (`lib/focusKey.ts`): − at zero to +, a
 * revoked token's Revoke to the next one's, Create to the new token's Copy,
 * Done to the name.
 *
 * Runs in `app`, `phone` and `tablet`: the phone's stepper and token list are
 * other elements (the large stepper, the cards). Settings → Save is in
 * settings.spec.ts, since it saves the singleton; a refused sign-in is in
 * auth.spec.ts.
 */
import { expect, test, type APIRequestContext, type Locator, type Page, type Route } from "@playwright/test";

import { apiContext } from "./api";
import { openListAt } from "./listRows";
import { shown } from "./lists";

const suffix = String(Date.now()).slice(-8);

/** Hold every request to `pattern` with `method` until the returned release. */
async function hold(page: Page, pattern: string, method: string): Promise<() => void> {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => (release = resolve));
  await page.route(pattern, async (route: Route) => {
    if (route.request().method() !== method) return route.fallback();
    await gate;
    await route.continue();
  });
  return release;
}

async function consumable(name: string, quantity: number): Promise<string> {
  const api = await apiContext();
  const resp = await api.post("/consumables", { data: { name, category: "cement", quantity_on_hand: quantity } });
  expect(resp.ok(), await resp.text()).toBeTruthy();
  const { id } = (await resp.json()) as { id: string };
  await api.dispose();
  return id;
}

async function onHand(id: string): Promise<number> {
  const api = await apiContext();
  // The list: there is no read of one consumable.
  const rows = (await (await api.get("/consumables")).json()) as { id: string; quantity_on_hand: number }[];
  await api.dispose();
  return rows.find((row) => row.id === id)?.quantity_on_hand ?? Number.NaN;
}

async function remove(route: string, id: string): Promise<void> {
  const api = await apiContext();
  await api.delete(`${route}/${id}`);
  await api.dispose();
}

type Listed = { id: string; name: string; revoked_at: string | null };

/** The tokens the page draws a Revoke for — every one not revoked, expired or
 *  not — in the list's order. */
async function listedWithRevoke(api: APIRequestContext): Promise<Listed[]> {
  return ((await (await api.get("/auth/tokens")).json()) as Listed[]).filter((token) => token.revoked_at === null);
}

async function mint(api: APIRequestContext, name: string, expiresAt?: string): Promise<string> {
  const minted = await api.post("/auth/tokens", {
    data: { name, scopes: ["collection:read"], ...(expiresAt ? { expires_at: expiresAt } : {}) },
  });
  expect(minted.ok(), await minted.text()).toBeTruthy();
  return ((await minted.json()) as { id: string }).id;
}

const revokeOf = (page: Page, name: string): Locator =>
  shown(page.getByTestId(/^token-(row|card)$/).filter({ hasText: name })).getByRole("button", { name: "Revoke" });

const stepper = (page: Page, which: "Add one" | "Remove one", name: string): Locator =>
  shown(page.locator("main").getByRole("button", { name: `${which} ${name}`, exact: true }));

test("+ keeps the keyboard through its request, and a press while it waits is refused (#268)", async ({
  page,
}, testInfo) => {
  const name = `E2E Keyboard ${testInfo.project.name} ${suffix} thinner`;
  const id = await consumable(name, 3);
  try {
    await openListAt(page, "/inventory?tab=consumables", name);
    const add = stepper(page, "Add one", name);
    let requests = 0;
    page.on("request", (request) => {
      if (request.method() === "POST" && request.url().endsWith(`/catalog/${id}/adjust`)) requests += 1;
    });

    // While the request is held: still focused, said to be unavailable, and a
    // second Enter is not a second request (#55).
    const release = await hold(page, `**/api/catalog/${id}/adjust`, "POST");
    await add.focus();
    await page.keyboard.press("Enter");
    await expect(add).toHaveAttribute("aria-disabled", "true");
    await expect(add).toBeFocused();
    await page.keyboard.press("Enter");
    release();
    await expect(add).not.toHaveAttribute("aria-disabled");
    await expect(add, "the keyboard is still on +").toBeFocused();
    await page.unrouteAll();

    // The issue's test: Enter again, and the count has moved by two in all.
    await page.keyboard.press("Enter");
    await expect.poll(() => onHand(id)).toBe(5);
    await expect(add).not.toHaveAttribute("aria-disabled");
    await expect(add).toBeFocused();
    expect(requests, "one request per press that was not refused").toBe(2);
  } finally {
    await remove("/consumables", id);
  }
});

test("− at zero hands the keyboard to + (#268)", async ({ page }, testInfo) => {
  const name = `E2E Keyboard ${testInfo.project.name} ${suffix} cement`;
  const id = await consumable(name, 1);
  try {
    await openListAt(page, "/inventory?tab=consumables", name);
    const minus = stepper(page, "Remove one", name);
    await minus.focus();
    await page.keyboard.press("Enter");
    await expect.poll(() => onHand(id)).toBe(0);
    await expect(minus).toBeDisabled();
    await expect(stepper(page, "Add one", name), "nothing left to remove: the keyboard is on +").toBeFocused();
  } finally {
    await remove("/consumables", id);
  }
});

test("Create hands the keyboard to the new token's Copy, and Done to the name (#268)", async ({ page }, testInfo) => {
  const name = `E2E Keyboard ${testInfo.project.name} ${suffix} created`;
  await page.goto("/settings/tokens");
  try {
    await page.getByLabel("Name").fill(name);
    await page.getByRole("button", { name: "Create token" }).focus();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("minted-token")).toBeVisible();
    await expect(page.getByRole("button", { name: "Copy" })).toBeFocused();

    await page.getByRole("button", { name: "Done" }).focus();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("minted-token")).toHaveCount(0);
    await expect(page.getByLabel("Name")).toBeFocused();
  } finally {
    const api = await apiContext();
    const tokens = (await (await api.get("/auth/tokens")).json()) as { id: string; name: string }[];
    for (const token of tokens.filter((each) => each.name === name)) await api.delete(`/auth/tokens/${token.id}`);
    await api.dispose();
  }
});

test("a revoked token's Revoke hands the keyboard to the next token's, then to the name (#268)", async ({
  page,
}, testInfo) => {
  const api = await apiContext();
  const names = [1, 2].map((n) => `E2E Keyboard ${testInfo.project.name} ${suffix} revoke ${n}`);
  const ids: string[] = [];
  for (const name of names) ids.push(await mint(api, name));
  const revocable = () => listedWithRevoke(api);

  try {
    await page.goto("/settings/tokens");
    page.on("dialog", (dialog) => void dialog.accept());
    // The first of the two in the list's order, then the other: two minted in
    // turn are neighbours there, so the first's next is the second.
    const listed = (await revocable()).filter((token) => ids.includes(token.id));
    expect(listed).toHaveLength(2);
    const [first, second] = listed;

    await revokeOf(page, first.name).focus();
    await page.keyboard.press("Enter");
    await expect(revokeOf(page, first.name)).toHaveCount(0);
    await expect(revokeOf(page, second.name), "the next token's Revoke").toBeFocused();

    // The second: its next, else the one before it, else the name — read off
    // the list as it stands, since the suite's other files may leave a token.
    const before = await revocable();
    const at = before.findIndex((token) => token.id === second.id);
    const neighbour = before[at + 1] ?? before[at - 1];
    await page.keyboard.press("Enter");
    await expect(revokeOf(page, second.name)).toHaveCount(0);
    await expect(neighbour ? revokeOf(page, neighbour.name) : page.getByLabel("Name")).toBeFocused();
  } finally {
    for (const id of ids) await api.delete(`/auth/tokens/${id}`);
    await api.dispose();
  }
});

test("Export CSV keeps the keyboard while the file is fetched (#268)", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === "phone", "a phone's page head has no Export CSV (shell.spec.ts)");
  await page.goto("/kits");
  // By its key: the label says "Exporting…" while it waits.
  const exportCsv = shown(page.locator('[data-focus-key="export:kits"]'));
  const release = await hold(page, "**/api/export/kits.csv", "GET");
  await exportCsv.focus();
  const download = page.waitForEvent("download");
  await page.keyboard.press("Enter");
  await expect(exportCsv).toHaveAttribute("aria-disabled", "true");
  await expect(exportCsv).toBeFocused();
  release();
  await download;
  await expect(exportCsv).not.toHaveAttribute("aria-disabled");
  await expect(exportCsv).toBeFocused();
  await page.unrouteAll();
});

test("a loss nobody could answer is not answered later, by whatever draws its key next (#268)", async ({
  page,
}, testInfo) => {
  // Revoke the only token there is while the new token's card is open: no
  // neighbour, and the name it would fall back to is not drawn — the keyboard
  // is on <body>, answered by nothing. Then Done, by a press that moves no
  // focus (Safari's tap on a button): the form comes back, and with it the name
  // the revoked Revoke named. Handing the keyboard there now would be a jump
  // nobody asked for — on an iPhone, the on-screen keyboard rising under a tap
  // on Done.
  const api = await apiContext();
  const others = await listedWithRevoke(api);
  if (others.length > 0) await api.dispose();
  test.skip(others.length > 0, "another token has a Revoke, a neighbour to answer this one");
  const name = `E2E Keyboard ${testInfo.project.name} ${suffix} only`;
  try {
    await page.goto("/settings/tokens");
    await page.getByLabel("Name").fill(name);
    await page.getByRole("button", { name: "Create token" }).focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("button", { name: "Copy" })).toBeFocused();

    page.on("dialog", (dialog) => void dialog.accept());
    const revoke = shown(page.getByTestId(/^token-(row|card)$/).filter({ hasText: name })).getByRole("button", {
      name: "Revoke",
    });
    await revoke.focus();
    await page.keyboard.press("Enter");
    await expect(revoke).toHaveCount(0);
    await expect.poll(() => page.evaluate(() => document.activeElement === document.body)).toBe(true);

    await page.getByRole("button", { name: "Done" }).dispatchEvent("click");
    await expect(page.getByLabel("Name")).toBeVisible();
    await expect(page.getByLabel("Name")).not.toBeFocused();
    expect(await page.evaluate(() => document.activeElement === document.body)).toBe(true);

    // Nor by the next shell change (Codex #336): a phone turned to the rail, a
    // window dragged across 768 px. The shell effect answers a removed control
    // for a frame, for a twin that mounts a commit late; long after, it is not
    // there to answer.
    const wide = (page.viewportSize()?.width ?? 1280) >= 768;
    await page.setViewportSize(wide ? { width: 390, height: 844 } : { width: 820, height: 1180 });
    await page.waitForFunction((phone) => matchMedia("(max-width: 767.98px)").matches === phone, wide);
    await page.evaluate(() => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done))));
    await expect(page.getByLabel("Name")).toBeVisible();
    await expect(page.getByLabel("Name"), "after a shell change").not.toBeFocused();
    expect(await page.evaluate(() => document.activeElement === document.body)).toBe(true);
  } finally {
    const tokens = (await (await api.get("/auth/tokens")).json()) as Listed[];
    for (const token of tokens.filter((each) => each.name === name)) await api.delete(`/auth/tokens/${token.id}`);
    await api.dispose();
  }
});

test("Enter in the name creates the token and hands the keyboard to Copy (Greptile #336)", async ({ page }, testInfo) => {
  const name = `E2E Keyboard ${testInfo.project.name} ${suffix} entered`;
  await page.goto("/settings/tokens");
  try {
    await page.getByLabel("Name").fill(name);
    await page.getByLabel("Name").press("Enter");
    await expect(page.getByTestId("minted-token")).toBeVisible();
    await expect(page.getByRole("button", { name: "Copy" })).toBeFocused();
  } finally {
    const api = await apiContext();
    const tokens = (await (await api.get("/auth/tokens")).json()) as Listed[];
    for (const token of tokens.filter((each) => each.name === name)) await api.delete(`/auth/tokens/${token.id}`);
    await api.dispose();
  }
});

test("an expired token has a Revoke, and its place in the order (Codex #336)", async ({ page }, testInfo) => {
  // Expired, live, expired: whichever way the list runs, the live one has an
  // expired one after it, and that one's Revoke is next.
  const api = await apiContext();
  const soon = new Date(Date.now() + 2_000).toISOString();
  const names = ["expired a", "live", "expired b"].map((n) => `E2E Keyboard ${testInfo.project.name} ${suffix} ${n}`);
  const ids = [await mint(api, names[0], soon), await mint(api, names[1]), await mint(api, names[2], soon)];
  try {
    await expect.poll(() => Date.now()).toBeGreaterThan(Date.parse(soon) + 250);
    await page.goto("/settings/tokens");
    page.on("dialog", (dialog) => void dialog.accept());
    const listed = await listedWithRevoke(api);
    const live = listed.findIndex((token) => token.id === ids[1]);
    const next = listed[live + 1];
    expect(next && [ids[0], ids[2]].includes(next.id), "an expired token follows the live one").toBe(true);
    await expect(revokeOf(page, next.name), "an expired token has a Revoke").toBeVisible();

    await revokeOf(page, names[1]).focus();
    await page.keyboard.press("Enter");
    await expect(revokeOf(page, names[1])).toHaveCount(0);
    await expect(revokeOf(page, next.name), "the expired token's Revoke is next").toBeFocused();
  } finally {
    for (const id of ids) await api.delete(`/auth/tokens/${id}`);
    await api.dispose();
  }
});

test("a Revoke's neighbours are the list's when it is pressed, not when it was focused (Greptile #336)", async ({
  page,
}, testInfo) => {
  const api = await apiContext();
  const names = [1, 2, 3].map((n) => `E2E Keyboard ${testInfo.project.name} ${suffix} fresh ${n}`);
  const ids: string[] = [];
  for (const name of names) ids.push(await mint(api, name));
  try {
    await page.goto("/settings/tokens");
    page.on("dialog", (dialog) => void dialog.accept());
    const mine = (await listedWithRevoke(api)).filter((token) => ids.includes(token.id));
    const [first, second, third] = mine;

    // The keyboard on the first; the second is revoked elsewhere, and the list
    // is refetched under the focused Revoke (a tab coming back to the front).
    await revokeOf(page, first.name).focus();
    expect((await api.delete(`/auth/tokens/${second.id}`)).status()).toBe(204);
    await page.evaluate(() => window.dispatchEvent(new Event("visibilitychange")));
    await expect(revokeOf(page, second.name)).toHaveCount(0);
    await expect(revokeOf(page, first.name)).toBeFocused();

    await page.keyboard.press("Enter");
    await expect(revokeOf(page, first.name)).toHaveCount(0);
    await expect(revokeOf(page, third.name), "the next token's Revoke as the list is now").toBeFocused();
  } finally {
    for (const id of ids) await api.delete(`/auth/tokens/${id}`);
    await api.dispose();
  }
});
