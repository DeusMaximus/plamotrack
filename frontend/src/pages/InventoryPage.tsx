import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";

import { api, ApiError, metaQuery } from "../api/client";
import type {
  Consumable,
  ConsumableUpdate,
  DisplayItem,
  DisplayItemUpdate,
  Tool,
  ToolUpdate,
  Upgrade,
  UpgradeUpdate,
} from "../api/types";
import { ExportCsvButton } from "../components/ExportCsvButton";
import { Modal } from "../components/Modal";
import { Button, EmptyState, ErrorBanner, Field, Input, Select } from "../components/ui";
import { currencyOptions, formatMoney, majorToMinor, minorToMajor, stepFor } from "../lib/format";
import { itemTypeLabel, itemTypePlural } from "../lib/labels";

type Tab = "tools" | "consumables" | "upgrades" | "display-items";
type InventoryItem = Tool | Consumable | Upgrade | DisplayItem;

const TABS: Tab[] = ["tools", "consumables", "upgrades", "display-items"];

/** The CSV table key, which is the spec registry's key and not the route segment:
 * `/display-items` is the REST resource, `display_items.csv` is the file. Every
 * other tab happens to spell them the same, which is why this needs saying. */
const EXPORT_TABLE: Record<Tab, string> = {
  tools: "tools",
  consumables: "consumables",
  upgrades: "upgrades",
  "display-items": "display_items",
};

/** The tab's wire item type, for the shared noun lookups — the tab id is a route
 * segment ("display-items"), not the `item_type` value ("display"), which is why
 * this map exists rather than a slice(). What one row of each tab is called
 * (labels, placeholders, empty states) all resolves through `itemType.*`. */
const TAB_ITEM_TYPE: Record<Tab, "tool" | "consumable" | "upgrade" | "display"> = {
  tools: "tool",
  consumables: "consumable",
  upgrades: "upgrade",
  "display-items": "display",
};

interface ItemFormValues {
  name: string;
  category: string;
  manufacturer: string;
  scale: string;
  notes: string;
  quantity_on_hand: number;
  low_stock_threshold: string;
  /** Major units of `unit_cost_reference_currency`. "" = no recorded cost. */
  unit_cost_reference: string;
  unit_cost_reference_currency: string;
  condition_notes: string;
}

/** Which form field(s) each payload key is derived from.
 *
 * One-to-one everywhere except the tool cost pair: the stored minor amount is
 * scaled by the currency's exponent, so switching AUD to JPY changes the number
 * even when the typed figure hasn't. Both halves therefore move whenever either
 * does — which is also what the paired CHECK constraint requires.
 *
 * Keyed off the API's own update types, so adding a column there stops
 * compiling until it is mapped here rather than silently dropping out of edits. */
const PAYLOAD_SOURCES: Record<
  keyof ToolUpdate | keyof ConsumableUpdate | keyof UpgradeUpdate | keyof DisplayItemUpdate,
  (keyof ItemFormValues)[]
> = {
  name: ["name"],
  category: ["category"],
  manufacturer: ["manufacturer"],
  scale: ["scale"],
  notes: ["notes"],
  quantity_on_hand: ["quantity_on_hand"],
  low_stock_threshold: ["low_stock_threshold"],
  condition_notes: ["condition_notes"],
  unit_cost_reference_minor: ["unit_cost_reference", "unit_cost_reference_currency"],
  unit_cost_reference_currency: ["unit_cost_reference", "unit_cost_reference_currency"],
};

/** Drop the keys this edit didn't touch.
 *
 * The form renders every column of the row, so a PATCH restating all of them
 * makes an unrelated edit authoritative over whatever another writer changed in
 * the meantime — which is how saving a notes-only edit resurrected a stock count
 * from whenever the modal was opened. Three writer types exist by design, so the
 * form has to say what it means rather than everything it can see.
 *
 * Every *Update schema is `exclude_unset`, so an omitted key is genuinely left
 * alone by the service. Creates are unfiltered: there, every field is intended. */
function editedOnly<T extends object>(
  full: T,
  changed: (field: keyof ItemFormValues) => boolean,
): Partial<T> {
  const entries = Object.entries(full).filter(([key]) =>
    PAYLOAD_SOURCES[key as keyof typeof PAYLOAD_SOURCES].some(changed),
  );
  return Object.fromEntries(entries) as Partial<T>;
}

/** Gate on meta before the form exists at all.
 *
 * `useForm` snapshots `defaultValues` on its first render and never revisits them,
 * so a form mounted while this query is still in flight would pick the fallback
 * currency and keep it — on a JPY instance, a new tool's cost quietly filed as AUD.
 * Not rendering isn't the same as not mounting, which is the same trap OrderFormModal
 * documents. InventoryPage warms the query, so this loading state is rarely seen —
 * "rarely" being exactly why the bug would survive. */
function ItemFormModal({
  tab,
  item,
  onClose,
}: {
  tab: Tab;
  item?: InventoryItem;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const { data: meta } = useQuery(metaQuery);

  if (!meta) {
    return (
      <Modal
        title={
          item
            ? t("inventory.editTitle", { name: item.name })
            : t("inventory.addTitle", { type: itemTypeLabel(TAB_ITEM_TYPE[tab]) })
        }
        onClose={onClose}
      >
        <EmptyState>{t("common.loading")}</EmptyState>
      </Modal>
    );
  }
  return (
    <ItemForm tab={tab} item={item} onClose={onClose} referenceCurrency={meta.reference_currency} />
  );
}

function ItemForm({
  tab,
  item,
  onClose,
  referenceCurrency,
}: {
  tab: Tab;
  item?: InventoryItem;
  onClose: () => void;
  referenceCurrency: string;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  // The typeahead half of the category vocabulary (#127) — the same device the kit
  // form gives series. The server folds a case-insensitive match onto the stored
  // spelling either way; this is what makes picking the stored spelling easy.
  const { data: categoryValues } = useQuery({
    queryKey: [tab, "categories"],
    queryFn: () => api.listCategories(tab as "tools" | "consumables" | "display-items"),
    enabled: tab !== "upgrades",
  });
  // A stored cost is read back in the code it was recorded under, never today's
  // reference currency — a JPY tool must not be re-read with two decimal places (§6).
  const storedCurrency =
    item && "unit_cost_reference_currency" in item ? item.unit_cost_reference_currency : null;
  const storedMinor =
    item && "unit_cost_reference_minor" in item ? item.unit_cost_reference_minor : null;
  const {
    register,
    watch,
    handleSubmit,
    formState: { errors, isSubmitting, dirtyFields },
  } = useForm<ItemFormValues>({
    defaultValues: {
      name: item?.name ?? "",
      category: item && "category" in item ? item.category : "",
      manufacturer: item && "manufacturer" in item ? (item.manufacturer ?? "") : "",
      scale: item && "scale" in item ? (item.scale ?? "") : "",
      notes: item && "notes" in item ? (item.notes ?? "") : "",
      quantity_on_hand: item?.quantity_on_hand ?? 1,
      low_stock_threshold:
        item && "low_stock_threshold" in item ? (item.low_stock_threshold?.toString() ?? "") : "",
      unit_cost_reference:
        storedMinor === null || storedCurrency === null
          ? ""
          : minorToMajor(storedMinor, storedCurrency),
      unit_cost_reference_currency: storedCurrency ?? referenceCurrency,
      condition_notes: item && "condition_notes" in item ? (item.condition_notes ?? "") : "",
    },
  });

  const onSubmit = handleSubmit(async (values) => {
    const changed = (field: keyof ItemFormValues) => Boolean(dirtyFields[field]);
    try {
      if (tab === "tools") {
        // Both halves move together — the API refuses an amount with no code, and a
        // code on its own denominates nothing.
        const hasCost = values.unit_cost_reference.trim() !== "";
        const payload = {
          name: values.name,
          category: values.category,
          quantity_on_hand: Number(values.quantity_on_hand),
          unit_cost_reference_minor: hasCost
            ? majorToMinor(values.unit_cost_reference, values.unit_cost_reference_currency)
            : null,
          unit_cost_reference_currency: hasCost ? values.unit_cost_reference_currency : null,
          condition_notes: values.condition_notes || null,
        };
        await (item
          ? api.updateTool(item.id, editedOnly(payload, changed))
          : api.createTool(payload));
      } else if (tab === "consumables") {
        const payload = {
          name: values.name,
          category: values.category,
          quantity_on_hand: Number(values.quantity_on_hand),
          low_stock_threshold:
            values.low_stock_threshold === "" ? null : Number(values.low_stock_threshold),
        };
        await (item
          ? api.updateConsumable(item.id, editedOnly(payload, changed))
          : api.createConsumable(payload));
      } else if (tab === "upgrades") {
        const payload = {
          name: values.name,
          manufacturer: values.manufacturer,
          quantity_on_hand: Number(values.quantity_on_hand),
        };
        await (item
          ? api.updateUpgrade(item.id, editedOnly(payload, changed))
          : api.createUpgrade(payload));
      } else {
        // Blank means "not recorded" on all three optional columns, and the API
        // stores null rather than "" — an empty string here would come back as a
        // scale of "" and read as a value the user typed.
        const payload = {
          name: values.name,
          category: values.category,
          scale: values.scale.trim() || null,
          manufacturer: values.manufacturer.trim() || null,
          quantity_on_hand: Number(values.quantity_on_hand),
          notes: values.notes.trim() || null,
        };
        await (item
          ? api.updateDisplayItem(item.id, editedOnly(payload, changed))
          : api.createDisplayItem(payload));
      }
      await queryClient.invalidateQueries({ queryKey: [tab] });
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("common.requestFailed"));
    }
  });

  return (
    <Modal
      title={
        item
          ? t("inventory.editTitle", { name: item.name })
          : t("inventory.addTitle", { type: itemTypeLabel(TAB_ITEM_TYPE[tab]) })
      }
      onClose={onClose}
    >
      <form onSubmit={onSubmit} className="space-y-3">
        <ErrorBanner message={error} />
        <Field label={t("common.name")} required error={errors.name?.message}>
          <Input {...register("name", { required: t("validation.nameRequired") })} />
        </Field>
        {tab !== "upgrades" ? (
          <Field label={t("inventory.category")} required error={errors.category?.message}>
            <Input
              {...register("category", { required: t("validation.categoryRequired") })}
              list="inventory-category-values"
              placeholder={t(`inventory.categoryPlaceholder.${tab}`)}
            />
            <datalist id="inventory-category-values">
              {categoryValues?.map((value) => (
                <option key={value} value={value} />
              ))}
            </datalist>
          </Field>
        ) : (
          <Field label={t("inventory.manufacturer")} required error={errors.manufacturer?.message}>
            <Input {...register("manufacturer", { required: t("validation.manufacturerRequired") })} />
          </Field>
        )}
        {/* Display items take a manufacturer too, but optional — the required one
            above belongs to upgrades, where the column is NOT NULL. */}
        {tab === "display-items" && (
          <div className="grid grid-cols-2 gap-3">
            <Field label={t("inventory.manufacturer")}>
              <Input {...register("manufacturer")} placeholder={t("inventory.manufacturerPlaceholder")} />
            </Field>
            <Field label={t("inventory.scale")}>
              <Input {...register("scale")} placeholder={t("inventory.scalePlaceholder")} />
            </Field>
          </div>
        )}
        <div className="grid grid-cols-2 gap-3">
          <Field label={t("inventory.quantityOnHand")}>
            <Input type="number" min={0} {...register("quantity_on_hand", { min: 0 })} />
          </Field>
          {tab === "consumables" && (
            <Field label={t("inventory.lowStockThreshold")}>
              <Input type="number" min={0} {...register("low_stock_threshold")} placeholder="—" />
            </Field>
          )}
          {tab === "tools" && (
            <>
              <Field label={t("inventory.referenceCost")}>
                <Input
                  type="number"
                  // Derived from the picked currency, so a yen amount can't be typed
                  // with cents and a dinar can reach its third decimal place.
                  step={stepFor(watch("unit_cost_reference_currency"))}
                  min={0}
                  {...register("unit_cost_reference")}
                  placeholder={t("inventory.referenceCostPlaceholder")}
                />
              </Field>
              <Field label={t("inventory.costCurrency")}>
                <Select {...register("unit_cost_reference_currency")}>
                  {currencyOptions(referenceCurrency).map((code) => (
                    <option key={code} value={code}>
                      {code}
                    </option>
                  ))}
                </Select>
              </Field>
            </>
          )}
        </div>
        {tab === "tools" && (
          <Field label={t("inventory.conditionNotes")}>
            <Input {...register("condition_notes")} />
          </Field>
        )}
        {tab === "display-items" && (
          <Field label={t("inventory.notes")}>
            <Input {...register("notes")} placeholder={t("inventory.notesPlaceholder")} />
          </Field>
        )}
        <div className="flex justify-end gap-2 pt-1">
          <Button type="button" variant="secondary" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" disabled={isSubmitting}>
            {t("common.add")}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function ApplyUpgradeModal({ upgrade, onClose }: { upgrade: Upgrade; onClose: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [kitId, setKitId] = useState("");
  const [quantity, setQuantity] = useState(1);
  const [submitting, setSubmitting] = useState(false);
  const { data: kits } = useQuery({ queryKey: ["kits"], queryFn: () => api.listKits() });

  const apply = async () => {
    if (!kitId) {
      setError(t("inventory.pickKitFirst"));
      return;
    }
    setSubmitting(true);
    try {
      await api.applyUpgrade(upgrade.id, { kit_id: kitId, quantity });
      await queryClient.invalidateQueries({ queryKey: ["upgrades"] });
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("common.requestFailed"));
      setSubmitting(false);
    }
  };

  return (
    <Modal title={t("inventory.applyTitle", { name: upgrade.name })} onClose={onClose}>
      <div className="space-y-3">
        <ErrorBanner message={error} />
        <p className="text-sm text-zinc-500">
          {t("inventory.applyOnHand", { count: upgrade.quantity_on_hand })}
        </p>
        <Field label={t("inventory.kit")} required>
          <Select value={kitId} onChange={(event) => setKitId(event.target.value)}>
            <option value="">{t("inventory.selectKit")}</option>
            {kits?.map((kit) => (
              <option key={kit.id} value={kit.id}>
                {kit.name} ({kit.grade})
              </option>
            ))}
          </Select>
        </Field>
        <Field label={t("inventory.quantity")}>
          <Input
            type="number"
            min={1}
            value={quantity}
            onChange={(event) => setQuantity(Number(event.target.value))}
          />
        </Field>
        <div className="flex justify-end gap-2 pt-1">
          <Button variant="secondary" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button onClick={apply} disabled={submitting}>
            {t("inventory.apply")}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

/** −1 / +1 on a stock row (#55).
 *
 * A signed delta, not a PATCH of `quantity_on_hand`: an absolute write has to read
 * the number before it can state one, and three writer types can move it in
 * between (rule 7) — which is the mechanism behind #35. "One fewer of these" is
 * what a consumable running out actually is, and this says so on the wire.
 *
 * Disabled while in flight rather than merely debounced: two clicks are two
 * intents, and the server would apply both. Disabling at zero is cosmetic — the
 * service refuses a negative result either way — but it puts the refusal where the
 * user can see it coming instead of in an error banner.
 */
function StockStepper({
  item,
  queryKey,
  onError,
}: {
  item: InventoryItem;
  queryKey: Tab;
  onError: (message: string | null) => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [pending, setPending] = useState(false);

  const adjust = async (delta: number) => {
    setPending(true);
    onError(null);
    try {
      await api.adjustStock(item.id, delta);
    } catch (err) {
      onError(err instanceof ApiError ? err.message : t("inventory.stockAdjustFailed"));
    } finally {
      // Refetch whether it succeeded or not. A refusal means the stored count is
      // not the one this row is showing — that is *why* it was refused — so
      // keeping the stale number leaves − armed against a quantity the server has
      // already rejected, and the next click earns the same 409.
      await queryClient.invalidateQueries({ queryKey: [queryKey] });
      setPending(false);
    }
  };

  return (
    <span className="inline-flex items-center gap-1">
      <Button
        variant="secondary"
        className="px-2 py-0.5 leading-none"
        aria-label={t("inventory.removeOne", { name: item.name })}
        disabled={pending || item.quantity_on_hand === 0}
        onClick={() => void adjust(-1)}
      >
        −
      </Button>
      <Button
        variant="secondary"
        className="px-2 py-0.5 leading-none"
        aria-label={t("inventory.addOne", { name: item.name })}
        disabled={pending}
        onClick={() => void adjust(1)}
      >
        +
      </Button>
    </span>
  );
}

export function InventoryPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<Tab>("tools");
  const [addOpen, setAddOpen] = useState(false);
  const [editing, setEditing] = useState<InventoryItem | null>(null);
  const [applying, setApplying] = useState<Upgrade | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [categoryFilter, setCategoryFilter] = useState("");

  const removeItem = async (item: InventoryItem) => {
    if (!window.confirm(t("common.confirmDelete", { name: item.name }))) return;
    setActionError(null);
    try {
      if (tab === "tools") {
        await api.deleteTool(item.id);
      } else if (tab === "consumables") {
        await api.deleteConsumable(item.id);
      } else if (tab === "upgrades") {
        await api.deleteUpgrade(item.id);
      } else {
        await api.deleteDisplayItem(item.id);
      }
      await queryClient.invalidateQueries({ queryKey: [tab] });
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : t("common.deleteFailed"));
    }
  };

  // Warms the shared cache so the form modal has it the moment it opens.
  useQuery(metaQuery);
  const tools = useQuery({ queryKey: ["tools"], queryFn: api.listTools, enabled: tab === "tools" });
  const consumables = useQuery({
    queryKey: ["consumables"],
    queryFn: api.listConsumables,
    enabled: tab === "consumables",
  });
  const upgrades = useQuery({
    queryKey: ["upgrades"],
    queryFn: api.listUpgrades,
    enabled: tab === "upgrades",
  });
  const displayItems = useQuery({
    queryKey: ["display-items"],
    queryFn: api.listDisplayItems,
    enabled: tab === "display-items",
  });

  // Distinct categories among the loaded rows, for the filter dropdown —
  // KitsPage's series-filter shape. Alphabetical: a picker, not a ranking.
  const categoryOptions = useMemo(() => {
    const rows =
      tab === "tools"
        ? tools.data
        : tab === "consumables"
          ? consumables.data
          : tab === "display-items"
            ? displayItems.data
            : undefined;
    const values = new Set<string>();
    for (const row of rows ?? []) if ("category" in row) values.add(row.category);
    return [...values].sort((a, b) => a.localeCompare(b));
  }, [tab, tools.data, consumables.data, displayItems.data]);

  const inCategory = <T extends { category: string }>(rows: T[] | undefined) =>
    categoryFilter ? (rows ?? []).filter((row) => row.category === categoryFilter) : (rows ?? []);
  const filteredTools = inCategory(tools.data);
  const filteredConsumables = inCategory(consumables.data);
  const filteredDisplayItems = inCategory(displayItems.data);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-2xl font-bold">{t("inventory.title")}</h1>
        <div className="flex gap-2">
          <ExportCsvButton table={EXPORT_TABLE[tab]} />
          <Button onClick={() => setAddOpen(true)}>
            {t("inventory.addButton", { type: itemTypeLabel(TAB_ITEM_TYPE[tab]) })}
          </Button>
        </div>
      </div>

      <div className="flex gap-1 border-b border-zinc-200">
        {TABS.map((tabOption) => (
          <button
            key={tabOption}
            onClick={() => {
              setTab(tabOption);
              // Vocabularies are per-table — a tool category filter is
              // meaningless on the consumables tab.
              setCategoryFilter("");
            }}
            className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium ${
              tab === tabOption
                ? "border-indigo-600 text-indigo-700"
                : "border-transparent text-zinc-500 hover:text-zinc-800"
            }`}
          >
            {t(`inventory.tabs.${tabOption}`)}
          </button>
        ))}
      </div>

      {tab !== "upgrades" && categoryOptions.length > 0 && (
        <Select
          aria-label={t("inventory.filterByCategory")}
          className="w-auto"
          value={categoryFilter}
          onChange={(event) => setCategoryFilter(event.target.value)}
        >
          <option value="">{t("inventory.allCategories")}</option>
          {categoryOptions.map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </Select>
      )}

      <ErrorBanner message={actionError} />

      {tab === "tools" &&
        (tools.isError ? (
          <ErrorBanner message={t("inventory.loadFailed.tools", { message: (tools.error as Error).message })} />
        ) : filteredTools.length ? (
          <div className="overflow-x-auto rounded-lg border border-zinc-200 bg-white">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-zinc-200 text-start text-xs uppercase tracking-wide text-zinc-500">
                  <th className="px-3 py-2">{t("common.name")}</th>
                  <th className="px-3 py-2">{t("inventory.category")}</th>
                  <th className="px-3 py-2">{t("inventory.headerOnHand")}</th>
                  <th className="px-3 py-2">{t("inventory.headerRefCost")}</th>
                  <th className="px-3 py-2">{t("inventory.headerCondition")}</th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody>
                {filteredTools.map((tool) => (
                  <tr key={tool.id} className="border-b border-zinc-100 last:border-0">
                    <td className="px-3 py-2 font-medium">{tool.name}</td>
                    <td className="px-3 py-2">{tool.category}</td>
                    <td className="px-3 py-2">
                      <span className="me-2 tabular-nums" data-testid="stock-count">
                        {tool.quantity_on_hand}
                      </span>
                      <StockStepper item={tool} queryKey="tools" onError={setActionError} />
                    </td>
                    <td className="px-3 py-2">
                      {tool.unit_cost_reference_minor === null ||
                      tool.unit_cost_reference_currency === null
                        ? "—"
                        : formatMoney(
                            tool.unit_cost_reference_minor,
                            tool.unit_cost_reference_currency,
                          )}
                    </td>
                    <td className="px-3 py-2 text-zinc-500">{tool.condition_notes ?? "—"}</td>
                    <td className="px-3 py-2 text-end">
                      <div className="flex justify-end gap-1">
                        <Button variant="secondary" onClick={() => setEditing(tool)}>
                          {t("common.edit")}
                        </Button>
                        <Button variant="danger" onClick={() => removeItem(tool)}>
                          {t("common.delete")}
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState>
            {tools.isLoading
              ? t("common.loading")
              : categoryFilter
                ? t("inventory.emptyFiltered", {
                    type: itemTypePlural("tool"),
                    category: categoryFilter,
                  })
                : t("inventory.emptyNone.tools")}
          </EmptyState>
        ))}

      {tab === "consumables" &&
        (consumables.isError ? (
          <ErrorBanner
            message={t("inventory.loadFailed.consumables", {
              message: (consumables.error as Error).message,
            })}
          />
        ) : filteredConsumables.length ? (
          <div className="overflow-x-auto rounded-lg border border-zinc-200 bg-white">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-zinc-200 text-start text-xs uppercase tracking-wide text-zinc-500">
                  <th className="px-3 py-2">{t("common.name")}</th>
                  <th className="px-3 py-2">{t("inventory.category")}</th>
                  <th className="px-3 py-2">{t("inventory.headerOnHand")}</th>
                  <th className="px-3 py-2">{t("inventory.headerLowStockAt")}</th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody>
                {filteredConsumables.map((item) => {
                  const low =
                    item.low_stock_threshold !== null &&
                    item.quantity_on_hand <= item.low_stock_threshold;
                  return (
                    <tr key={item.id} className="border-b border-zinc-100 last:border-0">
                      <td className="px-3 py-2 font-medium">{item.name}</td>
                      <td className="px-3 py-2">{item.category}</td>
                      <td className="px-3 py-2">
                        <span
                          className={`me-2 tabular-nums ${low ? "font-semibold text-red-600" : ""}`}
                          data-testid="stock-count"
                        >
                          {item.quantity_on_hand}
                        </span>
                        <StockStepper item={item} queryKey="consumables" onError={setActionError} />
                        {low && (
                          <span className="ms-2 rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">
                            {t("inventory.restock")}
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2">{item.low_stock_threshold ?? "—"}</td>
                      <td className="px-3 py-2 text-end">
                        <div className="flex justify-end gap-1">
                          <Button variant="secondary" onClick={() => setEditing(item)}>
                            {t("common.edit")}
                          </Button>
                          <Button variant="danger" onClick={() => removeItem(item)}>
                            {t("common.delete")}
                          </Button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState>
            {consumables.isLoading
              ? t("common.loading")
              : categoryFilter
                ? t("inventory.emptyFiltered", {
                    type: itemTypePlural("consumable"),
                    category: categoryFilter,
                  })
                : t("inventory.emptyNone.consumables")}
          </EmptyState>
        ))}

      {tab === "upgrades" &&
        (upgrades.isError ? (
          <ErrorBanner message={t("inventory.loadFailed.upgrades", { message: (upgrades.error as Error).message })} />
        ) : upgrades.data?.length ? (
          <div className="overflow-x-auto rounded-lg border border-zinc-200 bg-white">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-zinc-200 text-start text-xs uppercase tracking-wide text-zinc-500">
                  <th className="px-3 py-2">{t("common.name")}</th>
                  <th className="px-3 py-2">{t("inventory.manufacturer")}</th>
                  <th className="px-3 py-2">{t("inventory.headerOnHand")}</th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody>
                {upgrades.data.map((upgrade) => (
                  <tr key={upgrade.id} className="border-b border-zinc-100 last:border-0">
                    <td className="px-3 py-2 font-medium">{upgrade.name}</td>
                    <td className="px-3 py-2">{upgrade.manufacturer}</td>
                    <td className="px-3 py-2">
                      <span className="me-2 tabular-nums" data-testid="stock-count">
                        {upgrade.quantity_on_hand}
                      </span>
                      <StockStepper item={upgrade} queryKey="upgrades" onError={setActionError} />
                    </td>
                    <td className="px-3 py-2 text-end">
                      <div className="flex justify-end gap-1">
                        <Button
                          variant="secondary"
                          onClick={() => setApplying(upgrade)}
                          disabled={upgrade.quantity_on_hand === 0}
                        >
                          {t("inventory.applyToKit")}
                        </Button>
                        <Button variant="secondary" onClick={() => setEditing(upgrade)}>
                          {t("common.edit")}
                        </Button>
                        <Button variant="danger" onClick={() => removeItem(upgrade)}>
                          {t("common.delete")}
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState>
            {upgrades.isLoading ? t("common.loading") : t("inventory.emptyNone.upgrades")}
          </EmptyState>
        ))}

      {tab === "display-items" &&
        (displayItems.isError ? (
          <ErrorBanner
            message={t("inventory.loadFailed.display-items", {
              message: (displayItems.error as Error).message,
            })}
          />
        ) : filteredDisplayItems.length ? (
          <div className="overflow-x-auto rounded-lg border border-zinc-200 bg-white">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-zinc-200 text-start text-xs uppercase tracking-wide text-zinc-500">
                  <th className="px-3 py-2">{t("common.name")}</th>
                  <th className="px-3 py-2">{t("inventory.category")}</th>
                  <th className="px-3 py-2">{t("inventory.scale")}</th>
                  <th className="px-3 py-2">{t("inventory.manufacturer")}</th>
                  <th className="px-3 py-2">{t("inventory.headerOnHand")}</th>
                  <th className="px-3 py-2">{t("inventory.notes")}</th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody>
                {filteredDisplayItems.map((row) => (
                  <tr key={row.id} className="border-b border-zinc-100 last:border-0">
                    <td className="px-3 py-2 font-medium">{row.name}</td>
                    <td className="px-3 py-2">{row.category}</td>
                    <td className="px-3 py-2">{row.scale ?? "—"}</td>
                    <td className="px-3 py-2">{row.manufacturer ?? "—"}</td>
                    <td className="px-3 py-2">
                      <span className="me-2 tabular-nums" data-testid="stock-count">
                        {row.quantity_on_hand}
                      </span>
                      <StockStepper item={row} queryKey="display-items" onError={setActionError} />
                    </td>
                    <td className="px-3 py-2 text-zinc-500">{row.notes ?? "—"}</td>
                    <td className="px-3 py-2 text-end">
                      <div className="flex justify-end gap-1">
                        <Button variant="secondary" onClick={() => setEditing(row)}>
                          {t("common.edit")}
                        </Button>
                        <Button variant="danger" onClick={() => removeItem(row)}>
                          {t("common.delete")}
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState>
            {displayItems.isLoading
              ? t("common.loading")
              : categoryFilter
                ? t("inventory.emptyFiltered", {
                    type: itemTypePlural("display"),
                    category: categoryFilter,
                  })
                : t("inventory.emptyNone.display-items")}
          </EmptyState>
        ))}

      {addOpen && <ItemFormModal tab={tab} onClose={() => setAddOpen(false)} />}
      {editing && <ItemFormModal tab={tab} item={editing} onClose={() => setEditing(null)} />}
      {applying && <ApplyUpgradeModal upgrade={applying} onClose={() => setApplying(null)} />}
    </div>
  );
}
