import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { CatalogItemType } from "../api/types";
import { Button, Input } from "./ui";

/** A line's catalog target: an existing item picked from search, or a new one.
 * This is the §3.9 select-or-create constraint — there is deliberately no
 * free-text path that silently fragments the catalog. */
export type CatalogSelection =
  | { mode: "existing"; id: string; name: string }
  | { mode: "new"; name: string; category: string; manufacturer: string };

export function CatalogItemPicker({
  itemType,
  value,
  onChange,
}: {
  itemType: CatalogItemType;
  value: CatalogSelection | null;
  onChange: (value: CatalogSelection | null) => void;
}) {
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(query.trim()), 250);
    return () => clearTimeout(timer);
  }, [query]);

  const { data: results, isFetching } = useQuery({
    queryKey: ["catalog-search", debounced],
    queryFn: () => api.searchCatalog(debounced),
    enabled: open && debounced.length > 0,
    // This picker is the de-dup gate for the whole catalog, so it must never
    // answer "nothing matches — create it" from a cached result. The app-wide
    // staleTime is 5 s; a search made in one order form and repeated in the
    // next would otherwise be served stale, and the item created seconds ago
    // would be offered for creation again (#49). Zero means every open and every
    // query change re-asks the server — including for rows an MCP agent added
    // that no invalidation in this client could know about.
    staleTime: 0,
  });

  const matches = (results ?? []).filter((result) => result.item_type === itemType);

  if (value?.mode === "existing") {
    return (
      <div className="flex items-center gap-2">
        <span className="inline-flex items-center gap-1 rounded-md bg-indigo-50 px-2 py-1 text-sm text-indigo-800">
          {value.name}
        </span>
        <Button type="button" variant="secondary" onClick={() => onChange(null)}>
          Change
        </Button>
      </div>
    );
  }

  if (value?.mode === "new") {
    return (
      <div className="space-y-2 rounded-md border border-dashed border-indigo-300 bg-indigo-50/50 p-2">
        <div className="flex items-center justify-between">
          <span className="text-xs font-medium text-indigo-700">New {itemType}</span>
          <button
            type="button"
            className="text-xs text-zinc-500 hover:text-zinc-700"
            onClick={() => onChange(null)}
          >
            ← back to search
          </button>
        </div>
        <Input
          value={value.name}
          onChange={(event) => onChange({ ...value, name: event.target.value })}
          placeholder="Name"
        />
        {itemType === "upgrade" ? (
          <Input
            value={value.manufacturer}
            onChange={(event) => onChange({ ...value, manufacturer: event.target.value })}
            placeholder="Manufacturer (required)"
          />
        ) : (
          <Input
            value={value.category}
            onChange={(event) => onChange({ ...value, category: event.target.value })}
            placeholder="Category (required)"
          />
        )}
      </div>
    );
  }

  return (
    <div className="relative">
      <Input
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        placeholder={`Search ${itemType}s…`}
      />
      {open && debounced.length > 0 && (
        <div className="absolute z-10 mt-1 w-full overflow-hidden rounded-md border border-zinc-200 bg-white shadow-lg">
          {isFetching && <div className="px-3 py-2 text-xs text-zinc-400">Searching…</div>}
          {matches.map((result) => (
            <button
              key={result.id}
              type="button"
              className="flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-indigo-50"
              onMouseDown={() =>
                onChange({ mode: "existing", id: result.id, name: result.name })
              }
            >
              <span>
                {result.name}
                <span className="ml-2 text-xs text-zinc-400">
                  {result.category ?? result.manufacturer}
                </span>
              </span>
              <span className="text-xs text-zinc-400">{result.quantity_on_hand} on hand</span>
            </button>
          ))}
          <button
            type="button"
            className="w-full border-t border-zinc-100 px-3 py-2 text-left text-sm font-medium text-indigo-600 hover:bg-indigo-50"
            onMouseDown={() =>
              onChange({ mode: "new", name: query.trim(), category: "", manufacturer: "" })
            }
          >
            ＋ Create new {itemType} “{query.trim()}”
          </button>
        </div>
      )}
    </div>
  );
}
