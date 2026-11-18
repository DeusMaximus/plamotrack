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
 *  Latched: the first current copy is the one the caller keeps for as long as it
 *  is mounted, whatever is invalidated after it. The form under the gate took its
 *  defaults from that copy, and an invalidation while it is open would otherwise
 *  unmount it and lose what was typed — an import outlives the Data section
 *  (`lib/importRun.ts`) and refreshes every query when it answers, wherever the
 *  person has gone meanwhile (Greptile on #368). It also keeps the prop the form
 *  computes against equal to the copy its defaults came from, the second
 *  measurement above. A currency an import changes while a dialog is open is
 *  that dialog's to miss, as a change from any other writer is.
 *
 *  A refetch that fails leaves the form on its loading state, as a first fetch
 *  that fails always has; closing the dialog and opening it again asks again. */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { metaQuery } from "../api/client";
import type { Meta } from "../api/types";

export function useFormMeta(): Meta | undefined {
  const { data, isStale } = useQuery(metaQuery);
  const current = isStale ? undefined : data;
  const [kept, keep] = useState<Meta | undefined>(undefined);
  // Set while rendering, which React allows for a component's own state: the
  // latch closes in the same pass that first finds a current copy.
  if (kept === undefined && current !== undefined) keep(current);
  return kept ?? current;
}
