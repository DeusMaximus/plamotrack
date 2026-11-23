# plamotrack — frontend

The web app: React, Vite and TypeScript, styled with Tailwind v4 on the house tokens,
with TanStack Query for server state and react-hook-form for the dialogs. It talks to
the API through a hand-typed client, and holds no business logic of its own: every rule
lives in the backend's service layer, shared with REST and MCP.

In development, `npm run dev` serves it on :5173 and proxies `/api/*` to the API on
:8000, stripping the prefix. In the packaged stack, the `web` container serves the
production build from nginx, which is also the ingress (`nginx/`).

```
src/api/         the API client and the types that mirror the backend's schemas
src/i18n/        the language manifest and the en-AU source catalogue
src/components/  the shells, the one dialog, the filter sheet, the shared primitives
src/lib/         the shell hook, list filters, focus handling, formatting
src/pages/       Home, the list pages, Settings
e2e/             Playwright, in desktop, phone and tablet projects
nginx/           the ingress template, rendered at container start
```

This file is an orientation, not a setup guide. The instructions live in one place
each:

- **Setting up and running it:** the root README, *Developing on it*
  ([`../README.md`](../README.md#developing-on-it)).
- **The rules, the layout in full, and the commands to run before committing:**
  [`../AGENTS.md`](../AGENTS.md), for human and AI contributors alike.
- **Suites, the e2e harness and review:**
  [`../.agents/testing-and-review.md`](../.agents/testing-and-review.md).
- **Translating the interface:** [`../docs/translating.md`](../docs/translating.md).
- **Why it is shaped this way:** [`../docs/design.md`](../docs/design.md), §13 for the
  interface and §13.7 for the phone and tablet shells.
