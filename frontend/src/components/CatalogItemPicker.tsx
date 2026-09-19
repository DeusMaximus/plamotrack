import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import type { CatalogItemType } from "../api/types";
import { counted, itemTypeLabel, itemTypePlural } from "../lib/labels";
import { Button, Input } from "./ui";

/** A line's catalog target: an existing item picked from search, or a new one.
 * This is the §3.9 select-or-create constraint — there is deliberately no
 * free-text path that silently fragments the catalog. */
export type CatalogSelection =
  | { mode: "existing"; id: string; name: string }
  | { mode: "new"; name: string; category: string; manufacturer: string; scale: string };

/** The categories route segment per wire type — upgrades have no category column
 * (#127, decided against), hence no entry rather than a route that would 404. */
const CATEGORY_ROUTES: Partial<
  Record<CatalogItemType, "tools" | "consumables" | "display-items">
> = {
  tool: "tools",
  consumable: "consumables",
  display: "display-items",
};

export function CatalogItemPicker({
  itemType,
  value,
  onChange,
}: {
  itemType: CatalogItemType;
  value: CatalogSelection | null;
  onChange: (value: CatalogSelection | null) => void;
}) {
  const { t } = useTranslation();
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

  // The category vocabulary for the "new item" form below (#127) — same typeahead
  // the Inventory forms get, so a line entered mid-order folds onto the same
  // spellings. Fetched only once the form is actually showing a category field.
  // The datalist id is per component instance: an order holds one picker per
  // line, and a shared literal id bound every input to whichever datalist
  // rendered first — a consumable line offering the tool vocabulary
  // (#130 review, P3-4).
  const categoryListId = useId();
  const categoryRoute = CATEGORY_ROUTES[itemType];
  const { data: categoryValues } = useQuery({
    // Same key shape the Inventory page uses, so the two share one cache entry.
    // The "upgrades" fallback only keeps the key serializable — the query is
    // disabled whenever categoryRoute is undefined.
    queryKey: [categoryRoute ?? "upgrades", "categories"],
    queryFn: () => api.listCategories(categoryRoute!),
    enabled: value?.mode === "new" && categoryRoute !== undefined,
  });

  if (value?.mode === "existing") {
    return (
      // The name gives way, Change does not: a long unbroken name — a part
      // number run together — breaks inside its chip, where as a box that
      // could not shrink it pushed Change to 525 px on a 320 px sheet, the one
      // control that undoes the choice (#273). The row wraps only where its
      // box is narrow (`stack-3:`): wrapping at every width would send Change
      // under any long name on the desktop too (the lesson of #272's
      // applied-upgrade row).
      <div className="flex items-center gap-2 stack-3:flex-wrap">
        <span className="min-w-0 rounded-sm bg-accent-soft px-2 py-1 text-sm break-words text-accent">
          {value.name}
        </span>
        <Button type="button" variant="secondary" className="shrink-0" onClick={() => onChange(null)}>
          {t("catalogPicker.change")}
        </Button>
      </div>
    );
  }

  if (value?.mode === "new") {
    return (
      <div className="space-y-2 rounded-sm border border-dashed border-accent/40 bg-accent-soft p-2">
        {/* The way back gives way to nothing: where the label and it no longer
            share a line — 0.75rem text under a 40 px browser font, in a 200 px
            card — it takes the next, at the end, whole (Codex #274, finding 3;
            the same on `main`). By need, which at the default size is never:
            both are short and fixed, unlike the chosen name above. */}
        <div className="flex flex-wrap items-center justify-between gap-x-2">
          <span className="min-w-0 text-xs font-medium text-accent">
            {t("catalogPicker.newItem", { type: itemTypeLabel(itemType) })}
          </span>
          <button
            type="button"
            // Its side padding is the finger's, so it is in px: in rem it was 80 of
            // the row's 136 px at that font, and "search" broke in two.
            className="ms-auto max-w-full text-end text-xs text-muted hover:text-text touch:min-h-11 touch:px-[8px]"
            onClick={() => onChange(null)}
          >
            {t("catalogPicker.backToSearch")}
          </button>
        </div>
        <Input
          value={value.name}
          onChange={(event) => onChange({ ...value, name: event.target.value })}
          placeholder={t("common.name")}
        />
        {itemType === "upgrade" ? (
          <Input
            value={value.manufacturer}
            onChange={(event) => onChange({ ...value, manufacturer: event.target.value })}
            placeholder={t("catalogPicker.manufacturerRequired")}
          />
        ) : (
          <>
            <Input
              value={value.category}
              onChange={(event) => onChange({ ...value, category: event.target.value })}
              list={categoryListId}
              placeholder={
                itemType === "display"
                  ? t("catalogPicker.categoryRequiredDisplay")
                  : t("catalogPicker.categoryRequired")
              }
            />
            <datalist id={categoryListId}>
              {categoryValues?.map((category) => (
                <option key={category} value={category} />
              ))}
            </datalist>
          </>
        )}
        {/* Display items are the only type taking both, and neither is required: a
            commercial set names a maker, a scratch-built piece doesn't, and a
            backdrop panel has no scale. */}
        {itemType === "display" && (
          <div className="grid grid-cols-2 gap-2 stack-2:grid-cols-1">
            <Input
              value={value.manufacturer}
              onChange={(event) => onChange({ ...value, manufacturer: event.target.value })}
              placeholder={t("catalogPicker.manufacturer")}
            />
            <Input
              value={value.scale}
              onChange={(event) => onChange({ ...value, scale: event.target.value })}
              placeholder={t("catalogPicker.scalePlaceholder")}
            />
          </div>
        )}
      </div>
    );
  }

  return (
    <div
      className="relative"
      // Close only when focus has genuinely left the picker — relatedTarget is
      // where focus is going, and focusout bubbles, so this one handler sees
      // the input and every result button alike. The old per-input blur timer
      // closed the list under a keyboard user mid-Tab, unmounting the node
      // they had just focused (#104); relatedTarget is null when focus leaves
      // the document entirely, and contains(null) is false, so that still
      // closes.
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
          setOpen(false);
        }
      }}
    >
      <Input
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        placeholder={t("catalogPicker.searchPlaceholder", { type: itemTypePlural(itemType) })}
      />
      {open && debounced.length > 0 && (
        <div
          className="absolute z-10 mt-1 w-full overflow-hidden rounded-sm border border-border bg-surface"
          // Safari does not focus a button on click: a mousedown on a result took
          // focus from the input to nowhere, the `onBlur` above read that as focus
          // leaving the picker and unmounted the list before the click landed —
          // so no catalog item could be picked by tap or mouse on an iPhone or in
          // Safari (measured under Playwright's WebKit, #259). Keeping the input's
          // focus through the press is the standard remedy; the keyboard's Enter
          // and Space fire no mousedown and are untouched.
          onMouseDown={(event) => event.preventDefault()}
        >
          {isFetching && (
            <div className="px-3 py-2 text-xs text-muted">{t("catalogPicker.searching")}</div>
          )}
          {matches.map((result) => (
            <button
              key={result.id}
              type="button"
              // A full-width row, a finger tall under `touch:` (§13.7, #259).
              // The name keeps 8rem beside what is on hand, or the row's width,
              // and breaks where no line holds it; what is on hand takes the
              // next line, at the end, where the two cannot share one. Neither
              // squeezes the other to nothing: "0 on hand" held to its line took
              // all 176 px of the row at a 40 px font and left the name none.
              className="flex w-full flex-wrap items-center justify-between gap-x-3 px-3 py-2 text-start text-sm hover:bg-accent-soft touch:min-h-11"
              // onClick, not onMouseDown: a keyboard's Enter/Space activates a
              // button through click and never fires mousedown (#104). The
              // mousedown-first ordering the old handler relied on is covered
              // by the container's relatedTarget check above instead.
              onClick={() => onChange({ mode: "existing", id: result.id, name: result.name })}
            >
              <span className="min-w-0 flex-[1_1_min(8rem,100%)] break-words">
                {result.name}
                <span className="ms-2 text-xs text-muted">
                  {[result.category ?? result.manufacturer, result.scale]
                    .filter(Boolean)
                    .join(t("common.dotSeparator"))}
                </span>
              </span>
              <span className="ms-auto text-xs text-muted">
                {t("catalogPicker.onHand", counted({}, result.quantity_on_hand))}
              </span>
            </button>
          ))}
          <button
            type="button"
            className="flex w-full items-center gap-1.5 border-t border-rule px-3 py-2 text-start text-sm font-medium text-accent hover:bg-accent-soft touch:min-h-11"
            onClick={() =>
              onChange({
                mode: "new",
                name: query.trim(),
                category: "",
                manufacturer: "",
                scale: "",
              })
            }
          >
            {/* A stroke icon, not the "＋" glyph (§13: one icon set). */}
            <Plus size={14} aria-hidden className="shrink-0" />
            {/* The query is free text: one long token breaks inside the row. */}
            <span className="min-w-0 break-words">
              {t("catalogPicker.createNew", { type: itemTypeLabel(itemType), query: query.trim() })}
            </span>
          </button>
        </div>
      )}
    </div>
  );
}
