/* The per-browser theme (design §13.1), applied before first paint.
 *
 * A classic script in <head> blocks the parser, so nothing renders until
 * `data-theme` is on <html> — a dark browser never flashes light. It is a
 * first-party file rather than an inline script because the bundled nginx
 * serves the app under `script-src 'self'` (frontend/nginx/default.conf.template),
 * which an inline script would violate.
 *
 * src/lib/theme.ts is the runtime twin: the storage key, the accepted values and
 * the attribute are held equal by src/lib/theme.test.ts, which evaluates this
 * file against the same cases. Keep it free of anything the test's stubs do not
 * supply: `localStorage`, `matchMedia` and `document.documentElement` only.
 */
(function () {
  var stored = null;
  try {
    stored = localStorage.getItem("plamotrack.theme");
  } catch {
    // Storage disabled or denied: follow the device.
    stored = null;
  }
  var preference = stored === "light" || stored === "dark" ? stored : "system";
  var resolved =
    preference === "system"
      ? matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light"
      : preference;
  document.documentElement.setAttribute("data-theme", resolved);
})();
