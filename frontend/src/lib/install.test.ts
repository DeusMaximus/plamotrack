/** Add to Home Screen (design §13.7) is four things that have to agree and
 *  that nothing compiles together: the manifest, the icon files it and
 *  index.html name, the links in index.html, and the tokens the colours come
 *  from. A renamed file or a retuned `--bg` fails here instead of on
 *  somebody's phone. `scripts/render-icons.mjs` draws the PNGs. */

/// <reference types="node" />
// Node's fs, in this file alone (see tokens.test.ts): these are files the
// browser fetches, not modules the app imports.
import { existsSync, readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const file = (path: string) => new URL(`../../${path}`, import.meta.url);
const html = readFileSync(file("index.html"), "utf8");
const stylesheet = readFileSync(file("src/index.css"), "utf8");
const manifest = JSON.parse(readFileSync(file("public/manifest.json"), "utf8")) as {
  name: string;
  short_name: string;
  start_url: string;
  display: string;
  theme_color: string;
  background_color: string;
  icons: { src: string; sizes: string; type: string; purpose: string }[];
};

/** A PNG's IHDR: width and height at bytes 16–23, colour type at 25 (6 and 4
 *  carry alpha). */
function png(path: string) {
  const bytes = readFileSync(file(`public${path}`));
  expect(bytes.subarray(1, 4).toString("latin1"), path).toBe("PNG");
  return { width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20), alpha: [4, 6].includes(bytes[25]) };
}

function darkToken(name: string): string | undefined {
  const root = /:root\s*\{([^}]*)\}/.exec(stylesheet)?.[1] ?? "";
  return new RegExp(`--${name}:\\s*(#[0-9a-f]{6});`, "i").exec(root)?.[1];
}

describe("the web manifest", () => {
  it("installs as a standalone app that opens on Home", () => {
    expect(manifest).toMatchObject({
      name: "plamotrack",
      short_name: "plamotrack",
      start_url: "/",
      display: "standalone",
    });
  });

  it("takes its colours from the dark theme's background — the default theme", () => {
    expect(darkToken("bg")).toMatch(/^#[0-9a-f]{6}$/);
    expect(manifest.theme_color).toBe(darkToken("bg"));
    expect(manifest.background_color).toBe(darkToken("bg"));
  });

  it("names icons that exist at the sizes it says, opaque, with a maskable one", () => {
    expect(manifest.icons.map((icon) => icon.sizes).sort()).toEqual(["192x192", "512x512", "512x512"]);
    expect(manifest.icons.some((icon) => icon.purpose === "maskable")).toBe(true);
    for (const icon of manifest.icons) {
      const [width, height] = icon.sizes.split("x").map(Number);
      // Opaque: a launcher masks the icon's own corners, and a transparent
      // one shows whatever the launcher puts behind it.
      expect(png(icon.src), icon.src).toEqual({ width, height, alpha: false });
      expect(icon.type).toBe("image/png");
    }
  });
});

describe("index.html", () => {
  const links = [...html.matchAll(/<link\b[^>]*>/g)].map((match) => match[0]);
  const attr = (tag: string, name: string) => new RegExp(`\\b${name}="([^"]*)"`).exec(tag)?.[1];

  it("links the manifest as .json, which the bundled nginx has a type for", () => {
    const link = links.find((tag) => attr(tag, "rel") === "manifest");
    expect(link && attr(link, "href")).toBe("/manifest.json");
    expect(existsSync(file("public/manifest.json"))).toBe(true);
  });

  it("gives iOS a 180 px opaque touch icon", () => {
    const link = links.find((tag) => attr(tag, "rel") === "apple-touch-icon");
    const href = link && attr(link, "href");
    expect(href).toBe("/apple-touch-icon.png");
    expect(png(href as string)).toEqual({ width: 180, height: 180, alpha: false });
  });

  it("offers a PNG tab icon first and ends on the amber SVG", () => {
    // Order is the mechanism: Safari 18 and earlier skip the SVGs and find the
    // PNG; a browser that reads SVG icons but ignores `media` takes the last.
    const icons = links.filter((tag) => attr(tag, "rel") === "icon");
    expect(icons.map((tag) => attr(tag, "href"))).toEqual([
      "/favicon-32.png",
      "/favicon-light.svg",
      "/favicon-dark.svg",
    ]);
    expect(attr(icons[0], "sizes")).toBe("32x32");
    expect(png("/favicon-32.png")).toEqual({ width: 32, height: 32, alpha: true });
  });

  it("paints to the screen's edges, so the safe-area insets have a value", () => {
    const viewport = [...html.matchAll(/<meta\b[^>]*>/g)]
      .map((match) => match[0])
      .find((tag) => attr(tag, "name") === "viewport");
    expect(viewport && attr(viewport, "content")?.split(/,\s*/)).toEqual([
      "width=device-width",
      "initial-scale=1.0",
      "viewport-fit=cover",
    ]);
  });
});
