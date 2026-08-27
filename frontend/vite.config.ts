import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The app calls the API under /api; in dev Vite proxies that to the backend
// (stripping the prefix — the API serves at root). The production nginx will
// do the same (Milestone 5).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    // One ~507 kB chunk (~155 kB gzip) is deliberate: a single-owner instance
    // on a trusted network fetches it once per release, and a third of it is
    // react-dom. Raised from the 500 kB default when the #22 i18n stack
    // (i18next + react-i18next + the en-AU catalogue, ~71 kB minified) crossed
    // the line. Kept as a tripwire for an accidentally heavy dependency — each
    // statically imported language catalogue adds ~14 kB (src/i18n/registry.ts),
    // so if shipped languages re-trip this, reach for per-language dynamic
    // import before raising it again.
    chunkSizeWarningLimit: 600,
  },
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  test: {
    // Narrower than the default glob on purpose: that one also matches
    // `e2e/*.spec.ts`, which are Playwright tests and can only run under
    // `npm run test:e2e`. Unit tests live beside the code they cover.
    include: ["src/**/*.test.ts"],
  },
});
