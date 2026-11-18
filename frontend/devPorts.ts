/**
 * The two ports the source-run stack listens on: the API (uvicorn) and the SPA
 * (Vite). Read by `vite.config.ts` (its own port and the `/api` proxy target),
 * `playwright.config.ts` (the servers it starts or reuses) and `e2e/api.ts` (the
 * URLs the specs speak to), so the three cannot disagree.
 *
 * `DEV_API_PORT` and `DEV_WEB_PORT` move them. They exist for a second checkout
 * on the same machine (#144): Playwright reuses whatever answers on the port it
 * expects, so two checkouts on one pair of ports means one of them tests the
 * other's code. Give each checkout its own pair, and its own database
 * (`.agents/testing-and-review.md` → "More than one session at a time").
 */
function port(name: string, fallback: number): number {
  const raw = process.env[name];
  if (raw === undefined || raw === "") return fallback;
  const value = Number(raw);
  if (!/^[0-9]+$/.test(raw) || value < 1 || value > 65535) {
    // Refused, never defaulted: a typo that fell back to the usual port would
    // put this checkout on the pair another one is using.
    throw new Error(`${name} must be a port number from 1 to 65535, not ${JSON.stringify(raw)}.`);
  }
  return value;
}

export const API_PORT = port("DEV_API_PORT", 8000);
export const WEB_PORT = port("DEV_WEB_PORT", 5173);
