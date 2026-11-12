/** Which of the three shells this viewport gets (design §13.7): a bottom tab
 *  bar below 768 px, a 64 px icon rail from there to 1279 px, today's sidebar
 *  from 1280 px up. Chosen by viewport width alone — no device or touch
 *  sniffing — so an iPad and a narrow desktop window are one case, and an iPad
 *  mini in portrait (744 px) is a phone.
 *
 *  The two lines are Tailwind's `md` and `xl` (48rem and 80rem), spelled here
 *  in the same unit: a component that asks this hook and a utility that says
 *  `max-md:` answer from the same media query, whatever the browser's default
 *  font size is. `shell.test.ts` holds this file and `index.css` together.
 *
 *  Ask the hook when a shell renders *different things* (the navigation, card
 *  rows instead of a table); use the `max-md:` / `touch:` utilities when it is
 *  the same thing at a different size.
 */

import { useSyncExternalStore } from "react";

export const SHELLS = ["phone", "rail", "sidebar"] as const;
export type Shell = (typeof SHELLS)[number];

export const RAIL_QUERY = "(min-width: 48rem)";
export const SIDEBAR_QUERY = "(min-width: 80rem)";

export function resolveShell(railUp: boolean, sidebarUp: boolean): Shell {
  if (sidebarUp) return "sidebar";
  return railUp ? "rail" : "phone";
}

/** No `matchMedia` (a unit test's Node) reads as the layout that predates the
 *  shells, the way `theme.ts` reads a missing one as "not dark". */
export function currentShell(): Shell {
  if (typeof matchMedia !== "function") return "sidebar";
  return resolveShell(matchMedia(RAIL_QUERY).matches, matchMedia(SIDEBAR_QUERY).matches);
}

function subscribe(listener: () => void): () => void {
  if (typeof matchMedia !== "function") return () => {};
  const queries = [matchMedia(RAIL_QUERY), matchMedia(SIDEBAR_QUERY)];
  for (const query of queries) query.addEventListener("change", listener);
  return () => {
    for (const query of queries) query.removeEventListener("change", listener);
  };
}

/** The shell for this viewport, live: a rotation or a window resize across a
 *  line re-renders the caller. */
export function useShell(): Shell {
  return useSyncExternalStore(subscribe, currentShell, () => "sidebar" as const);
}
