import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { api, ApiError, metaQuery } from "../api/client";
import type { Consumable, Tool, Upgrade } from "../api/types";
import { ExportCsvButton } from "../components/ExportCsvButton";
import { Modal } from "../components/Modal";
import { Button, EmptyState, ErrorBanner, Field, Input, Select } from "../components/ui";
import { currencyOptions, formatMoney, majorToMinor, minorToMajor, stepFor } from "../lib/format";

type Tab = "tools" | "consumables" | "upgrades";
type InventoryItem = Tool | Consumable | Upgrade;

const TABS: { id: Tab; label: string }[] = [
  { id: "tools", label: "Tools" },
  { id: "consumables", label: "Consumables" },
  { id: "upgrades", label: "Upgrades" },
];

interface ItemFormValues {
  name: string;
  category: string;
  manufacturer: string;
  quantity_on_hand: number;
  low_stock_threshold: string;
  /** Major units of `unit_cost_reference_currency`. "" = no recorded cost. */
  unit_cost_reference: string;
  unit_cost_reference_currency: string;
  condition_notes: string;
}

function ItemFormModal({
  tab,
  item,
  onClose,
}: {
  tab: Tab;
  item?: InventoryItem;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const { data: meta } = useQuery(metaQuery);
  const referenceCurrency = meta?.reference_currency ?? "AUD";
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
    formState: { errors, isSubmitting },
  } = useForm<ItemFormValues>({
    defaultValues: {
      name: item?.name ?? "",
      category: item && "category" in item ? item.category : "",
      manufacturer: item && "manufacturer" in item ? item.manufacturer : "",
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
        await (item ? api.updateTool(item.id, payload) : api.createTool(payload));
      } else if (tab === "consumables") {
        const payload = {
          name: values.name,
          category: values.category,
          quantity_on_hand: Number(values.quantity_on_hand),
          low_stock_threshold:
            values.low_stock_threshold === "" ? null : Number(values.low_stock_threshold),
        };
        await (item ? api.updateConsumable(item.id, payload) : api.createConsumable(payload));
      } else {
        const payload = {
          name: values.name,
          manufacturer: values.manufacturer,
          quantity_on_hand: Number(values.quantity_on_hand),
        };
        await (item ? api.updateUpgrade(item.id, payload) : api.createUpgrade(payload));
      }
      await queryClient.invalidateQueries({ queryKey: [tab] });
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Request failed");
    }
  });

  return (
    <Modal
      title={item ? `Edit ${item.name}` : `Add ${tab.slice(0, -1)}`}
      onClose={onClose}
    >
      <form onSubmit={onSubmit} className="space-y-3">
        <ErrorBanner message={error} />
        <Field label="Name" required error={errors.name?.message}>
          <Input {...register("name", { required: "Name is required" })} />
        </Field>
        {tab !== "upgrades" ? (
          <Field label="Category" required error={errors.category?.message}>
            <Input
              {...register("category", { required: "Category is required" })}
              placeholder={tab === "tools" ? "cutting / filing / gluing" : "paint / cement / blades"}
            />
          </Field>
        ) : (
          <Field label="Manufacturer" required error={errors.manufacturer?.message}>
            <Input {...register("manufacturer", { required: "Manufacturer is required" })} />
          </Field>
        )}
        <div className="grid grid-cols-2 gap-3">
          <Field label="Quantity on hand">
            <Input type="number" min={0} {...register("quantity_on_hand", { min: 0 })} />
          </Field>
          {tab === "consumables" && (
            <Field label="Low-stock threshold">
              <Input type="number" min={0} {...register("low_stock_threshold")} placeholder="—" />
            </Field>
          )}
          {tab === "tools" && (
            <>
              <Field label="Reference cost">
                <Input
                  type="number"
                  // Derived from the picked currency, so a yen amount can't be typed
                  // with cents and a dinar can reach its third decimal place.
                  step={stepFor(watch("unit_cost_reference_currency"))}
                  min={0}
                  {...register("unit_cost_reference")}
                  placeholder="informational"
                />
              </Field>
              <Field label="Cost currency">
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
          <Field label="Condition notes">
            <Input {...register("condition_notes")} />
          </Field>
        )}
        <div className="flex justify-end gap-2 pt-1">
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={isSubmitting}>
            Add
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function ApplyUpgradeModal({ upgrade, onClose }: { upgrade: Upgrade; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [kitId, setKitId] = useState("");
  const [quantity, setQuantity] = useState(1);
  const [submitting, setSubmitting] = useState(false);
  const { data: kits } = useQuery({ queryKey: ["kits"], queryFn: () => api.listKits() });

  const apply = async () => {
    if (!kitId) {
      setError("Pick a kit first");
      return;
    }
    setSubmitting(true);
    try {
      await api.applyUpgrade(upgrade.id, { kit_id: kitId, quantity });
      await queryClient.invalidateQueries({ queryKey: ["upgrades"] });
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Request failed");
      setSubmitting(false);
    }
  };

  return (
    <Modal title={`Apply "${upgrade.name}"`} onClose={onClose}>
      <div className="space-y-3">
        <ErrorBanner message={error} />
        <p className="text-sm text-zinc-500">
          {upgrade.quantity_on_hand} on hand — applying decrements stock and records which kit got
          it.
        </p>
        <Field label="Kit" required>
          <Select value={kitId} onChange={(event) => setKitId(event.target.value)}>
            <option value="">Select a kit…</option>
            {kits?.map((kit) => (
              <option key={kit.id} value={kit.id}>
                {kit.name} ({kit.grade})
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Quantity">
          <Input
            type="number"
            min={1}
            value={quantity}
            onChange={(event) => setQuantity(Number(event.target.value))}
          />
        </Field>
        <div className="flex justify-end gap-2 pt-1">
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={apply} disabled={submitting}>
            Apply
          </Button>
        </div>
      </div>
    </Modal>
  );
}

export function InventoryPage() {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<Tab>("tools");
  const [addOpen, setAddOpen] = useState(false);
  const [editing, setEditing] = useState<InventoryItem | null>(null);
  const [applying, setApplying] = useState<Upgrade | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const removeItem = async (item: InventoryItem) => {
    if (!window.confirm(`Delete "${item.name}"?`)) return;
    setActionError(null);
    try {
      if (tab === "tools") {
        await api.deleteTool(item.id);
      } else if (tab === "consumables") {
        await api.deleteConsumable(item.id);
      } else {
        await api.deleteUpgrade(item.id);
      }
      await queryClient.invalidateQueries({ queryKey: [tab] });
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Delete failed");
    }
  };

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

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-2xl font-bold">Inventory</h1>
        <div className="flex gap-2">
          <ExportCsvButton table={tab} />
          <Button onClick={() => setAddOpen(true)}>+ Add {tab.slice(0, -1)}</Button>
        </div>
      </div>

      <div className="flex gap-1 border-b border-zinc-200">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium ${
              tab === t.id
                ? "border-indigo-600 text-indigo-700"
                : "border-transparent text-zinc-500 hover:text-zinc-800"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <ErrorBanner message={actionError} />

      {tab === "tools" &&
        (tools.isError ? (
          <ErrorBanner message={`Failed to load tools: ${(tools.error as Error).message}`} />
        ) : tools.data?.length ? (
          <div className="overflow-x-auto rounded-lg border border-zinc-200 bg-white">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500">
                  <th className="px-3 py-2">Name</th>
                  <th className="px-3 py-2">Category</th>
                  <th className="px-3 py-2">On hand</th>
                  <th className="px-3 py-2">Ref. cost</th>
                  <th className="px-3 py-2">Condition</th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody>
                {tools.data.map((tool) => (
                  <tr key={tool.id} className="border-b border-zinc-100 last:border-0">
                    <td className="px-3 py-2 font-medium">{tool.name}</td>
                    <td className="px-3 py-2">{tool.category}</td>
                    <td className="px-3 py-2">{tool.quantity_on_hand}</td>
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
                    <td className="px-3 py-2 text-right">
                      <div className="flex justify-end gap-1">
                        <Button variant="secondary" onClick={() => setEditing(tool)}>
                          Edit
                        </Button>
                        <Button variant="danger" onClick={() => removeItem(tool)}>
                          Delete
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState>{tools.isLoading ? "Loading…" : "No tools yet."}</EmptyState>
        ))}

      {tab === "consumables" &&
        (consumables.isError ? (
          <ErrorBanner
            message={`Failed to load consumables: ${(consumables.error as Error).message}`}
          />
        ) : consumables.data?.length ? (
          <div className="overflow-x-auto rounded-lg border border-zinc-200 bg-white">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500">
                  <th className="px-3 py-2">Name</th>
                  <th className="px-3 py-2">Category</th>
                  <th className="px-3 py-2">On hand</th>
                  <th className="px-3 py-2">Low-stock at</th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody>
                {consumables.data.map((item) => {
                  const low =
                    item.low_stock_threshold !== null &&
                    item.quantity_on_hand <= item.low_stock_threshold;
                  return (
                    <tr key={item.id} className="border-b border-zinc-100 last:border-0">
                      <td className="px-3 py-2 font-medium">{item.name}</td>
                      <td className="px-3 py-2">{item.category}</td>
                      <td className="px-3 py-2">
                        <span className={low ? "font-semibold text-red-600" : ""}>
                          {item.quantity_on_hand}
                        </span>
                        {low && (
                          <span className="ml-2 rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">
                            restock
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2">{item.low_stock_threshold ?? "—"}</td>
                      <td className="px-3 py-2 text-right">
                        <div className="flex justify-end gap-1">
                          <Button variant="secondary" onClick={() => setEditing(item)}>
                            Edit
                          </Button>
                          <Button variant="danger" onClick={() => removeItem(item)}>
                            Delete
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
          <EmptyState>{consumables.isLoading ? "Loading…" : "No consumables yet."}</EmptyState>
        ))}

      {tab === "upgrades" &&
        (upgrades.isError ? (
          <ErrorBanner message={`Failed to load upgrades: ${(upgrades.error as Error).message}`} />
        ) : upgrades.data?.length ? (
          <div className="overflow-x-auto rounded-lg border border-zinc-200 bg-white">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500">
                  <th className="px-3 py-2">Name</th>
                  <th className="px-3 py-2">Manufacturer</th>
                  <th className="px-3 py-2">On hand</th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody>
                {upgrades.data.map((upgrade) => (
                  <tr key={upgrade.id} className="border-b border-zinc-100 last:border-0">
                    <td className="px-3 py-2 font-medium">{upgrade.name}</td>
                    <td className="px-3 py-2">{upgrade.manufacturer}</td>
                    <td className="px-3 py-2">{upgrade.quantity_on_hand}</td>
                    <td className="px-3 py-2 text-right">
                      <div className="flex justify-end gap-1">
                        <Button
                          variant="secondary"
                          onClick={() => setApplying(upgrade)}
                          disabled={upgrade.quantity_on_hand === 0}
                        >
                          Apply to kit
                        </Button>
                        <Button variant="secondary" onClick={() => setEditing(upgrade)}>
                          Edit
                        </Button>
                        <Button variant="danger" onClick={() => removeItem(upgrade)}>
                          Delete
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState>{upgrades.isLoading ? "Loading…" : "No upgrades yet."}</EmptyState>
        ))}

      {addOpen && <ItemFormModal tab={tab} onClose={() => setAddOpen(false)} />}
      {editing && <ItemFormModal tab={tab} item={editing} onClose={() => setEditing(null)} />}
      {applying && <ApplyUpgradeModal upgrade={applying} onClose={() => setApplying(null)} />}
    </div>
  );
}
