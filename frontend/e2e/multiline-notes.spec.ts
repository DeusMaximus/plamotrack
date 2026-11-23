/** A note of more than one line survives the catalog dialog (#376).
 *
 *  A tool's condition notes and a display item's notes are notes, as a kit's
 *  build notes and an order's notes are (the owner's call on #376), and REST,
 *  MCP and the importer store a break in them. The dialog edited both in a
 *  one-line box, which shows a break as a space (#361), so an edit, and a box
 *  that was only clicked into, saved the note as one line.
 *
 *  Each note is seeded through REST with its break as `\n`, `\r\n` and `\r`, then
 *  edited in the dialog two ways: a word changed, and a box only clicked into
 *  while the name is what changes. Each is read back through REST. A textarea's
 *  value spells every break `\n`, whatever the stored spelling, so an edit
 *  stores `\n`; a note that was only clicked into is not sent at all, so it
 *  keeps the bytes it had. After the edit the list draws the note as one run
 *  of words. Runs in `phone` too, where the dialog is a sheet and the row a
 *  card. */
import { expect, type Locator, type Page, test } from "@playwright/test";

import { apiContext } from "./api";
import { openListAt } from "./listRows";

const suffix = Date.now().toString(36);

const BREAKS = [
  { label: "LF", br: "\n" },
  { label: "CRLF", br: "\r\n" },
  { label: "CR", br: "\r" },
] as const;

/** The two columns, as the dialog labels them and the API names them. */
const COLUMNS = [
  { what: "a tool's condition notes", tab: "tools", route: "/tools", label: "Condition notes", key: "condition_notes", seed: { category: "cutting" } },
  { what: "a display item's notes", tab: "display-items", route: "/display-items", label: "Notes", key: "notes", seed: { category: "action base" } },
] as const;

type Stored = { id: string; name: string } & Record<string, unknown>;

const cleanups: (() => Promise<void>)[] = [];

test.afterAll(async () => {
  for (const cleanup of cleanups.reverse()) await cleanup();
});

async function seed(route: string, data: object): Promise<Stored> {
  const api = await apiContext();
  const resp = await api.post(route, { data });
  expect(resp.status(), await resp.text()).toBe(201);
  const row = (await resp.json()) as Stored;
  await api.dispose();
  cleanups.push(async () => {
    const remover = await apiContext();
    await remover.delete(`${route}/${row.id}`);
    await remover.dispose();
  });
  return row;
}

async function stored(route: string, id: string): Promise<Stored> {
  const api = await apiContext();
  const resp = await api.get(route);
  expect(resp.ok(), await resp.text()).toBeTruthy();
  const row = ((await resp.json()) as Stored[]).find((candidate) => candidate.id === id)!;
  await api.dispose();
  return row;
}

/** Open the row's edit dialog: the table's pencil from 768 px, the card's
 *  below it — one accessible name, whichever shell is drawn. */
async function openEdit(page: Page, tab: string, name: string): Promise<Locator> {
  await openListAt(page, `/inventory?tab=${tab}`, name);
  await page.getByRole("button", { name: `Edit ${name}` }).filter({ visible: true }).first().click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByLabel("Name")).toHaveValue(name);
  return dialog;
}

/** Select `word` in the box and type its replacement over it, as a person
 *  would: keystrokes into what is shown, not `fill`, which would replace the
 *  whole value and say nothing about what the box held. */
async function replaceWord(page: Page, box: Locator, word: string, replacement: string): Promise<void> {
  await box.click();
  await box.evaluate((element: HTMLInputElement | HTMLTextAreaElement, target) => {
    const at = element.value.indexOf(target);
    if (at < 0) throw new Error(`"${target}" is not in ${JSON.stringify(element.value)}`);
    element.setSelectionRange(at, at + target.length);
  }, word);
  await page.keyboard.type(replacement);
}

/** The list draws the row's note as one run of words, each break a space: the
 *  table's cell from 768 px, the card below it. `innerText` is the text as
 *  drawn, by the engine's own white-space rules — under which WebKit draws a
 *  lone CR as nothing, joining the words, unless the row was given a space. */
async function expectDrawnAsOneRun(page: Page, name: string, text: string): Promise<void> {
  const row = page.locator("main").locator("tbody tr, li").filter({ visible: true }).filter({ hasText: name });
  const drawn = row.getByText(text.split(" ").slice(0, 2).join(" ")).filter({ visible: true }).first();
  await expect(drawn).toBeVisible();
  expect(await drawn.innerText()).toMatch(new RegExp(`(^|· )${text}$`));
}

/** Type at the end of a box, after whatever it holds. */
async function typeAtEnd(page: Page, box: Locator, text: string): Promise<void> {
  await box.click();
  await box.evaluate((element: HTMLInputElement) => {
    element.setSelectionRange(element.value.length, element.value.length);
  });
  await page.keyboard.type(text);
}

for (const column of COLUMNS) {
  for (const { label, br } of BREAKS) {
    test.describe(`${column.what}, stored with a ${label}`, () => {
      const note = `Blade chipped${br}still cuts`;

      test("a word changed in the dialog keeps both lines", async ({ page }, testInfo) => {
        const name = `E2E Multiline ${column.tab} ${label} edit ${testInfo.project.name} ${suffix}`;
        const row = await seed(column.route, { name, ...column.seed, [column.key]: note });
        expect(row[column.key]).toBe(note); // control: REST stored the break

        const dialog = await openEdit(page, column.tab, name);
        const box = dialog.getByLabel(column.label);
        // A soft look at the box, so a run against one-line boxes still saves
        // and reads back what they stored.
        await expect.soft(box).toHaveValue("Blade chipped\nstill cuts");
        await replaceWord(page, box, "cuts", "works");
        await dialog.getByRole("button", { name: "Save", exact: true }).click();
        await expect(dialog).toHaveCount(0);

        expect((await stored(column.route, row.id))[column.key]).toBe("Blade chipped\nstill works");
        await expectDrawnAsOneRun(page, name, "Blade chipped still works");
      });

      test("a box only clicked into keeps its break", async ({ page }, testInfo) => {
        const name = `E2E Multiline ${column.tab} ${label} click ${testInfo.project.name} ${suffix}`;
        const row = await seed(column.route, { name, ...column.seed, [column.key]: note });

        const dialog = await openEdit(page, column.tab, name);
        // Into the note and out again, then the change that makes the save,
        // typed at the end of the name: a character, taken back, and a word.
        // Taken back, the name is as it loaded, and that is when react-hook-form
        // compares every field with what it loaded — the note's box included,
        // whose value it copied into the form when the box lost focus. Without
        // that moment it never looks at the note, whatever the box holds.
        await dialog.getByLabel(column.label).click();
        const nameBox = dialog.getByLabel("Name");
        await typeAtEnd(page, nameBox, "x");
        await page.keyboard.press("Backspace");
        await expect(nameBox).toHaveValue(name);
        await page.keyboard.type(" II");
        await dialog.getByRole("button", { name: "Save", exact: true }).click();
        await expect(dialog).toHaveCount(0);

        const after = await stored(column.route, row.id);
        expect(after.name).toBe(`${name} II`); // the save happened
        expect(after[column.key]).toBe(note);
        await expectDrawnAsOneRun(page, `${name} II`, "Blade chipped still cuts");
      });
    });
  }
}
