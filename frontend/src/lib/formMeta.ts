/** The `/meta` a form may take its defaults from (#366).
 *
 *  The order and inventory forms default a new entry to the reference currency
 *  `/meta` serves, and react-hook-form captures defaults once, at mount — so a
 *  form's gate decides which currency it starts on. Presence is not enough for
 *  that gate: a save that changes the currency (General, or an import's settings
 *  sheet) only *invalidates* the cached copy, and TanStack serves an invalidated
 *  copy while the refetch it started is in flight. A dialog opened in that window
 *  mounted on the old currency and kept it. Saved before the answer came, a new
 *  line stored its §6 snapshot in the old currency; saved after it, with no
 *  snapshot at all, because the prop the form computes against had moved under
 *  defaults it never revisits (both measured on the base of #366).
 *
 *  So a copy counts only while no invalidation has overtaken it. `metaQuery` is
 *  fresh forever otherwise (`staleTime: Infinity`), which makes `isStale` exactly
 *  "invalidated and not answered since", or never fetched at all.
 *
 *  A refetch that fails leaves the form on its loading state, as a first fetch
 *  that fails always has; closing the dialog and opening it again asks again. */
import { useQuery } from "@tanstack/react-query";

import { metaQuery } from "../api/client";
import type { Meta } from "../api/types";

export function useFormMeta(): Meta | undefined {
  const { data, isStale } = useQuery(metaQuery);
  return isStale ? undefined : data;
}
