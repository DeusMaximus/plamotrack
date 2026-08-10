import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The app calls the API under /api; in dev Vite proxies that to the backend
// (stripping the prefix — the API serves at root). The production nginx will
// do the same (Milestone 5).
export default defineConfig({
  plugins: [react(), tailwindcss()],
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
