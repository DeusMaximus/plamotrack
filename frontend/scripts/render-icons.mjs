/** The raster icons (design §13.7), drawn from the brand mark so nobody
 * redraws it by hand: the home-screen icons the web manifest and iOS ask for,
 * and a PNG tab icon for browsers that cannot read the SVG ones (Safari 18 and
 * earlier). Run by hand when the mark or the tokens change —
 *
 *   node scripts/render-icons.mjs        (needs: npx playwright install chromium)
 *
 * — and commit what it writes under public/. `src/lib/install.test.ts` holds
 * the files, the manifest and index.html to each other.
 *
 * The geometry is components/BrandMark.tsx's three bars; the colours are the
 * dark theme's `--bg` and `--accent`, read from src/index.css — the dark set is
 * the default theme, and the amber reads on light and dark chrome alike (the
 * reason the amber SVG is the last icon link in index.html). */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "@playwright/test";

const here = dirname(fileURLToPath(import.meta.url));
const out = join(here, "../public");

const stylesheet = readFileSync(join(here, "../src/index.css"), "utf8");
const root = /:root\s*\{([^}]*)\}/.exec(stylesheet)?.[1] ?? "";
function token(name) {
  const value = new RegExp(`--${name}:\\s*(#[0-9a-f]{6});`, "i").exec(root)?.[1];
  if (!value) throw new Error(`no --${name} in src/index.css's :root block`);
  return value;
}
const BG = token("bg");
const ACCENT = token("accent");

// components/BrandMark.tsx, on its 24-unit box.
const BARS =
  '<rect x="2" y="9" width="5" height="13" rx="1"/>' +
  '<rect x="9.5" y="2" width="5" height="20" rx="1"/>' +
  '<rect x="17" y="6" width="5" height="16" rx="1"/>';

// `mark` is the share of the icon the mark's 24-unit box takes. The opaque
// icons double as maskable ones: a launcher may crop to a circle of 80% of the
// icon, and at 0.56 the bars' corners sit at 0.33 of the width from the centre,
// inside that circle's 0.4. The tab icon is the SVG favicons' own 24-in-32.
const ICONS = [
  { file: "favicon-32.png", size: 32, mark: 24 / 32, background: null },
  { file: "apple-touch-icon.png", size: 180, mark: 0.56, background: BG },
  { file: "icon-192.png", size: 192, mark: 0.56, background: BG },
  { file: "icon-512.png", size: 512, mark: 0.56, background: BG },
];

function svg({ size, mark, background }) {
  const scale = (size * mark) / 24;
  const offset = (size - size * mark) / 2;
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">` +
    (background ? `<rect width="${size}" height="${size}" fill="${background}"/>` : "") +
    `<g transform="translate(${offset} ${offset}) scale(${scale})" fill="${ACCENT}">${BARS}</g></svg>`
  );
}

const browser = await chromium.launch();
try {
  for (const icon of ICONS) {
    // One device pixel per CSS pixel, so the clip below is exactly `size`
    // square. The viewport is a fixed, ordinary size: headless Chromium never
    // finishes a screenshot of a 32 px one.
    const page = await browser.newPage({
      viewport: { width: 640, height: 640 },
      deviceScaleFactor: 1,
    });
    await page.setContent(
      `<!doctype html><style>html,body{margin:0;background:transparent}svg{display:block}</style>${svg(icon)}`,
    );
    await page.screenshot({
      path: join(out, icon.file),
      omitBackground: icon.background === null,
      clip: { x: 0, y: 0, width: icon.size, height: icon.size },
    });
    await page.close();
    console.log(`public/${icon.file}  ${icon.size}×${icon.size}${icon.background ? "" : "  transparent"}`);
  }
} finally {
  await browser.close();
}
