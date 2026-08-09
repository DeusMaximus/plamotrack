import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useMemo, useState } from "react";
import type {
  Control,
  FieldErrors,
  UseFormRegister,
  UseFormSetValue,
  UseFormWatch,
} from "react-hook-form";
import { Controller, useFieldArray, useForm } from "react-hook-form";

import { api, ApiError } from "../api/client";
import type {
  ItemType,
  Kit,
  Order,
  OrderItemUpsert,
  OrderUpdate,
} from "../api/types";
import type { CatalogSelection } from "../components/CatalogItemPicker";
import { CatalogItemPicker } from "../components/CatalogItemPicker";
import { ExportCsvButton } from "../components/ExportCsvButton";
import { Modal } from "../components/Modal";
import { Button, EmptyState, ErrorBanner, Field, Input, Select } from "../components/ui";
import { formatDate, formatMoney, majorToMinor, minorToMajor, todayISO } from "../lib/format";

const COMMON_CURRENCIES = ["AUD", "USD", "JPY", "EUR", "GBP", "SGD", "HKD", "CNY", "KRW"];

/** Suggestions, with this instance's own currency first — it's the likely pick. */
function currencyOptions(reference: string): string[] {
  return [reference, ...COMMON_CURRENCIES.filter((code) => code !== reference)];
}

/** Instance config: static for the life of the process, so fetch it once.
 * Shared key, so the page warms the cache before the form modal needs it. */
const metaQuery = {
  queryKey: ["meta"],
  queryFn: api.getMeta,
  staleTime: Infinity,
} as const;

interface LineValues {
  id?: string;
  item_type: ItemType;
  quantity: number;
  unit_price: string;
  kit_name: string;
  kit_grade: string;
  kit_number: string;
  kit_status: "ordered" | "pre_ordered";
  catalog: CatalogSelection | null;
}

interface OrderFormValues {
  retailer_id: string;
  order_date: string;
  order_number: string;
  currency_code: string;
  shipping_cost: string;
  delivery_service: string;
  tracking_number: string;
  tracking_url: string;
  received: boolean;
  items: LineValues[];
}

function emptyLine(): LineValues {
  return {
    item_type: "kit",
    quantity: 1,
    unit_price: "",
    kit_name: "",
    kit_grade: "",
    kit_number: "",
    kit_status: "ordered",
    catalog: null,
  };
}

function orderToFormValues(
  order: Order,
  kitById: Map<string, Kit>,
  catalogName: Map<string, string>,
): OrderFormValues {
  return {
    retailer_id: order.retailer_id,
    order_date: order.order_date,
    order_number: order.order_number ?? "",
    currency_code: order.currency_code,
    shipping_cost: order.shipping_cost_minor
      ? minorToMajor(order.shipping_cost_minor, order.currency_code)
      : "",
    delivery_service: order.delivery_service ?? "",
    tracking_number: order.tracking_number ?? "",
    tracking_url: order.tracking_url ?? "",
    received: order.received_at !== null,
    items: order.items.map((item) => {
      const firstKit = kitById.get(item.spawned_kit_ids[0] ?? "");
      return {
        id: item.id,
        item_type: item.item_type,
        quantity: item.quantity,
        unit_price: minorToMajor(item.unit_price_minor, item.currency_code),
        kit_name: firstKit?.name ?? "",
        kit_grade: firstKit?.grade ?? "",
        kit_number: firstKit?.kit_number ?? "",
        kit_status: firstKit?.status === "pre_ordered" ? "pre_ordered" : "ordered",
        catalog:
          item.item_type === "kit" || item.catalog_ref_id === null
            ? null
            : {
                mode: "existing",
                id: item.catalog_ref_id,
                name: catalogName.get(item.catalog_ref_id) ?? "(unknown item)",
              },
      };
    }),
  };
}

function toOrderItem(
  line: LineValues,
  currency: string,
  referenceCurrency: string,
): OrderItemUpsert {
  const unitPriceMinor = majorToMinor(line.unit_price, currency);
  // Only a same-currency purchase converts to itself. Anything else needs a rate
  // we don't have, so the snapshot stays empty rather than guessing (§6) — the
  // server stamps the currency code in when an amount is present.
  const converted = currency === referenceCurrency ? unitPriceMinor : null;
  const base = {
    id: line.id,
    quantity: Number(line.quantity),
    unit_price_minor: unitPriceMinor,
    currency_code: currency,
    converted_price_minor: converted,
    converted_currency_code: converted === null ? null : referenceCurrency,
  };
  if (line.item_type === "kit") {
    return {
      ...base,
      item_type: "kit",
      kit: {
        name: line.kit_name,
        grade: line.kit_grade,
        kit_number: line.kit_number || null,
        status: line.kit_status,
      },
    };
  }
  if (line.catalog?.mode === "existing") {
    return { ...base, item_type: line.item_type, catalog_ref_id: line.catalog.id };
  }
  if (line.catalog?.mode === "new") {
    return {
      ...base,
      item_type: line.item_type,
      new_item: {
        name: line.catalog.name,
        category: line.catalog.category || null,
        manufacturer: line.catalog.manufacturer || null,
      },
    };
  }
  throw new Error("catalog line without a selection");
}

function LineEditor({
  index,
  control,
  register,
  watch,
  setValue,
  errors,
  onRemove,
  canRemove,
}: {
  index: number;
  control: Control<OrderFormValues>;
  register: UseFormRegister<OrderFormValues>;
  watch: UseFormWatch<OrderFormValues>;
  setValue: UseFormSetValue<OrderFormValues>;
  errors: FieldErrors<OrderFormValues>;
  onRemove: () => void;
  canRemove: boolean;
}) {
  const itemType = watch(`items.${index}.item_type`);
  const lineErrors = errors.items?.[index];

  return (
    <div className="space-y-2 rounded-lg border border-zinc-200 bg-zinc-50 p-3">
      <div className="flex items-center gap-2">
        <Select
          {...register(`items.${index}.item_type`, {
            onChange: () => {
              // changing type = a different line as far as dispatch is concerned:
              // drop the id (server treats it as remove + add) and stale payloads
              setValue(`items.${index}.id`, undefined);
              setValue(`items.${index}.catalog`, null);
            },
          })}
          className="!w-32"
        >
          <option value="kit">Kit</option>
          <option value="tool">Tool</option>
          <option value="consumable">Consumable</option>
          <option value="upgrade">Upgrade</option>
        </Select>
        <Field label="" className="!mb-0 w-20">
          <Input
            type="number"
            min={1}
            aria-label="Quantity"
            {...register(`items.${index}.quantity`, { required: true, min: 1 })}
          />
        </Field>
        <Input
          type="number"
          step="0.01"
          min={0}
          aria-label="Unit price"
          placeholder="Unit price"
          className="!w-28"
          {...register(`items.${index}.unit_price`, { required: "required" })}
        />
        <div className="flex-1" />
        {canRemove && (
          <button
            type="button"
            onClick={onRemove}
            aria-label="Remove line"
            className="rounded p-1 text-zinc-400 hover:bg-zinc-200 hover:text-zinc-600"
          >
            ✕
          </button>
        )}
      </div>

      {itemType === "kit" ? (
        <div className="grid grid-cols-2 gap-2">
          <Input
            placeholder="Kit name *"
            {...register(`items.${index}.kit_name`, { required: "Kit name is required" })}
          />
          <div className="grid grid-cols-3 gap-2">
            <Input
              placeholder="Grade *"
              {...register(`items.${index}.kit_grade`, { required: "Grade is required" })}
            />
            <Input placeholder="Kit #" {...register(`items.${index}.kit_number`)} />
            <Select {...register(`items.${index}.kit_status`)}>
              <option value="ordered">Ordered</option>
              <option value="pre_ordered">Pre-ordered</option>
            </Select>
          </div>
          {(lineErrors?.kit_name || lineErrors?.kit_grade) && (
            <span className="col-span-2 text-xs text-red-600">
              {lineErrors?.kit_name?.message ?? lineErrors?.kit_grade?.message}
            </span>
          )}
        </div>
      ) : (
        <Controller
          control={control}
          name={`items.${index}.catalog`}
          rules={{
            validate: (value) => {
              if (!value) return "Search for an existing item or create a new one";
              if (value.mode === "new") {
                if (!value.name.trim()) return "New item needs a name";
                if (itemType === "upgrade" && !value.manufacturer.trim())
                  return "New upgrades need a manufacturer";
                if (itemType !== "upgrade" && !value.category.trim())
                  return "New items need a category";
              }
              return true;
            },
          }}
          render={({ field, fieldState }) => (
            <div>
              <CatalogItemPicker
                itemType={itemType}
                value={field.value}
                onChange={field.onChange}
              />
              {fieldState.error && (
                <span className="mt-1 block text-xs text-red-600">{fieldState.error.message}</span>
              )}
            </div>
          )}
        />
      )}
    </div>
  );
}

/** Gate, so the form below is only ever *mounted* with a real reference currency.
 *
 * It has to be a separate component rather than an early return inside the form:
 * hooks run before any return, so `useForm` would already have captured a
 * defaultValues with an empty currency, and react-hook-form does not revisit
 * defaults when the query later resolves. Not rendering isn't the same as not
 * mounting. In practice OrdersPage warms this query, so the loading state is
 * rarely seen — "rarely" being exactly why the bug would have survived. */
function OrderFormModal({ order, onClose }: { order?: Order; onClose: () => void }) {
  const { data: meta } = useQuery(metaQuery);

  if (!meta) {
    return (
      <Modal title={order ? "Edit order" : "New order"} onClose={onClose} wide>
        <EmptyState>Loading…</EmptyState>
      </Modal>
    );
  }
  return (
    <OrderForm
      order={order}
      onClose={onClose}
      referenceCurrency={meta.reference_currency}
    />
  );
}

function OrderForm({
  order,
  onClose,
  referenceCurrency,
}: {
  order?: Order;
  onClose: () => void;
  referenceCurrency: string;
}) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [newRetailerName, setNewRetailerName] = useState<string | null>(null);
  const { data: retailers } = useQuery({ queryKey: ["retailers"], queryFn: api.listRetailers });
  const { data: kits } = useQuery({ queryKey: ["kits"], queryFn: () => api.listKits() });
  const { data: tools } = useQuery({ queryKey: ["tools"], queryFn: api.listTools });
  const { data: consumables } = useQuery({
    queryKey: ["consumables"],
    queryFn: api.listConsumables,
  });
  const { data: upgrades } = useQuery({ queryKey: ["upgrades"], queryFn: api.listUpgrades });

  const defaults = useMemo((): OrderFormValues => {
    if (!order) {
      return {
        retailer_id: "",
        order_date: todayISO(),
        order_number: "",
        currency_code: referenceCurrency,
        shipping_cost: "",
        delivery_service: "",
        tracking_number: "",
        tracking_url: "",
        received: false,
        items: [emptyLine()],
      };
    }
    const kitById = new Map((kits ?? []).map((kit) => [kit.id, kit]));
    const catalogName = new Map(
      [...(tools ?? []), ...(consumables ?? []), ...(upgrades ?? [])].map((row) => [
        row.id,
        row.name,
      ]),
    );
    return orderToFormValues(order, kitById, catalogName);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- snapshot once per open
  }, [order?.id]);

  const {
    register,
    control,
    handleSubmit,
    watch,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<OrderFormValues>({ defaultValues: defaults });
  const { fields, append, remove } = useFieldArray({ control, name: "items" });

  const addRetailer = async () => {
    if (!newRetailerName?.trim()) return;
    try {
      const created = await api.createRetailer({ name: newRetailerName.trim() });
      await queryClient.invalidateQueries({ queryKey: ["retailers"] });
      setValue("retailer_id", created.id);
      setNewRetailerName(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not add retailer");
    }
  };

  const onSubmit = handleSubmit(async (values) => {
    setError(null);
    const payload: OrderUpdate = {
      retailer_id: values.retailer_id,
      order_date: values.order_date,
      order_number: values.order_number || null,
      currency_code: values.currency_code,
      shipping_cost_minor: values.shipping_cost
        ? majorToMinor(values.shipping_cost, values.currency_code)
        : null,
      delivery_service: values.delivery_service || null,
      tracking_number: values.tracking_number || null,
      tracking_url: values.tracking_url || null,
      items: values.items.map((line) =>
        toOrderItem(line, values.currency_code, referenceCurrency),
      ),
    };
    try {
      if (order) {
        await api.updateOrder(order.id, payload);
      } else {
        await api.createOrder({
          retailer_id: values.retailer_id,
          order_date: values.order_date,
          order_number: payload.order_number,
          currency_code: values.currency_code,
          shipping_cost_minor: payload.shipping_cost_minor,
          delivery_service: payload.delivery_service,
          tracking_number: payload.tracking_number,
          tracking_url: payload.tracking_url,
          received: values.received,
          items: payload.items ?? [],
        });
      }
      await Promise.all(
        ["orders", "kits", "tools", "consumables", "upgrades"].map((key) =>
          queryClient.invalidateQueries({ queryKey: [key] }),
        ),
      );
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Request failed");
    }
  });

  return (
    <Modal title={order ? "Edit order" : "New order"} onClose={onClose} wide>
      <form onSubmit={onSubmit} className="space-y-4">
        <ErrorBanner message={error} />

        <div className="grid grid-cols-3 gap-3">
          <Field label="Retailer" required error={errors.retailer_id?.message}>
            {newRetailerName === null ? (
              <div className="flex gap-1">
                <Select {...register("retailer_id", { required: "Pick a retailer" })}>
                  <option value="">Select…</option>
                  {retailers?.map((retailer) => (
                    <option key={retailer.id} value={retailer.id}>
                      {retailer.name}
                    </option>
                  ))}
                </Select>
                <Button type="button" variant="secondary" onClick={() => setNewRetailerName("")}>
                  +
                </Button>
              </div>
            ) : (
              <div className="flex gap-1">
                <Input
                  autoFocus
                  value={newRetailerName}
                  onChange={(event) => setNewRetailerName(event.target.value)}
                  placeholder="New retailer name"
                />
                <Button type="button" onClick={addRetailer}>
                  Add
                </Button>
                <Button type="button" variant="secondary" onClick={() => setNewRetailerName(null)}>
                  ✕
                </Button>
              </div>
            )}
          </Field>
          <Field label="Order date" required>
            <Input type="date" {...register("order_date", { required: true })} />
          </Field>
          <Field label="Currency" required>
            <Input
              list="currencies"
              {...register("currency_code", {
                required: true,
                pattern: { value: /^[A-Z]{3}$/, message: "3-letter ISO code" },
              })}
            />
            <datalist id="currencies">
              {currencyOptions(referenceCurrency).map((code) => (
                <option key={code} value={code} />
              ))}
            </datalist>
          </Field>
        </div>

        <div className="grid grid-cols-3 gap-3">
          <Field label="Order number">
            <Input
              {...register("order_number")}
              placeholder="retailer's reference, e.g. #GEA-10482"
            />
          </Field>
          <Field label="Shipping cost">
            <Input type="number" step="0.01" min={0} {...register("shipping_cost")} />
          </Field>
          <Field label="Delivery service">
            <Input {...register("delivery_service")} placeholder="blank = local pickup" />
          </Field>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Tracking number">
            <Input {...register("tracking_number")} />
          </Field>
          <Field label="Tracking URL">
            <Input {...register("tracking_url")} placeholder="https://…" />
          </Field>
        </div>

        {!order && (
          <label className="flex items-center gap-2 text-sm text-zinc-700">
            <input type="checkbox" {...register("received")} className="h-4 w-4 accent-indigo-600" />
            Already in hand (store purchase / delivery arrived) — stock counts immediately
          </label>
        )}

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-zinc-700">Items</h3>
            <Button type="button" variant="secondary" onClick={() => append(emptyLine())}>
              + Add line
            </Button>
          </div>
          {order && (
            <p className="text-xs text-zinc-500">
              Kit detail edits apply to every kit this line spawned. Removing a line undoes it
              (kits deleted, stock reversed) — kits that are building/complete, rated, or have
              photos are protected.
            </p>
          )}
          {fields.map((field, index) => (
            <LineEditor
              key={field.id}
              index={index}
              control={control}
              register={register}
              watch={watch}
              setValue={setValue}
              errors={errors}
              onRemove={() => remove(index)}
              canRemove={fields.length > 1}
            />
          ))}
        </div>

        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={isSubmitting}>
            {order ? "Save changes" : "Record order"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function orderTotal(order: Order): string {
  const byCurrency = new Map<string, number>();
  for (const item of order.items) {
    byCurrency.set(
      item.currency_code,
      (byCurrency.get(item.currency_code) ?? 0) + item.quantity * item.unit_price_minor,
    );
  }
  if (order.shipping_cost_minor) {
    byCurrency.set(
      order.currency_code,
      (byCurrency.get(order.currency_code) ?? 0) + order.shipping_cost_minor,
    );
  }
  return (
    [...byCurrency].map(([currency, minor]) => formatMoney(minor, currency)).join(" + ") || "—"
  );
}

export function OrdersPage() {
  const queryClient = useQueryClient();
  const [modal, setModal] = useState<{ mode: "add" } | { mode: "edit"; order: Order } | null>(
    null,
  );
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [actionError, setActionError] = useState<string | null>(null);

  const {
    data: orders,
    isLoading,
    isError,
    error,
  } = useQuery({ queryKey: ["orders"], queryFn: api.listOrders });
  const { data: retailers } = useQuery({ queryKey: ["retailers"], queryFn: api.listRetailers });
  const { data: kits } = useQuery({ queryKey: ["kits"], queryFn: () => api.listKits() });
  const { data: tools } = useQuery({ queryKey: ["tools"], queryFn: api.listTools });
  const { data: consumables } = useQuery({
    queryKey: ["consumables"],
    queryFn: api.listConsumables,
  });
  const { data: upgrades } = useQuery({ queryKey: ["upgrades"], queryFn: api.listUpgrades });
  // Warms the shared cache so the form modal has it the moment it opens.
  useQuery(metaQuery);

  const retailerName = useMemo(
    () => new Map((retailers ?? []).map((retailer) => [retailer.id, retailer.name])),
    [retailers],
  );
  const itemName = useMemo(() => {
    const map = new Map<string, string>();
    for (const kit of kits ?? []) map.set(kit.id, kit.name);
    for (const row of [...(tools ?? []), ...(consumables ?? []), ...(upgrades ?? [])]) {
      map.set(row.id, row.name);
    }
    return map;
  }, [kits, tools, consumables, upgrades]);

  const invalidateAll = () =>
    Promise.all(
      ["orders", "kits", "tools", "consumables", "upgrades"].map((key) =>
        queryClient.invalidateQueries({ queryKey: [key] }),
      ),
    );

  const receive = async (order: Order) => {
    const label = retailerName.get(order.retailer_id) ?? "this retailer";
    if (
      !window.confirm(
        `Mark the ${formatDate(order.order_date)} order from ${label} as received?\n\n` +
          "Catalog stock will be applied and kits still in the ordering pipeline " +
          "move to Backlog.",
      )
    ) {
      return;
    }
    setActionError(null);
    try {
      await api.receiveOrder(order.id);
      await invalidateAll();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Receive failed");
    }
  };

  const remove = async (order: Order) => {
    const label = retailerName.get(order.retailer_id) ?? "this order";
    if (
      !window.confirm(
        `Delete the ${formatDate(order.order_date)} order from ${label}?\n\n` +
          "This undoes the entry: kits it spawned are deleted and any applied " +
          "stock is reversed. Progressed kits or consumed stock will block it.",
      )
    ) {
      return;
    }
    setActionError(null);
    try {
      await api.deleteOrder(order.id);
      await invalidateAll();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Delete failed");
    }
  };

  const toggle = (id: string) =>
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-2xl font-bold">Orders</h1>
        <div className="flex gap-2">
          <ExportCsvButton table="orders" />
          <Button onClick={() => setModal({ mode: "add" })}>+ New order</Button>
        </div>
      </div>

      <ErrorBanner message={actionError} />

      {isError ? (
        <ErrorBanner message={`Failed to load orders: ${(error as Error).message}`} />
      ) : orders?.length ? (
        <div className="overflow-x-auto rounded-lg border border-zinc-200 bg-white">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500">
                <th className="w-8 px-3 py-2" />
                <th className="px-3 py-2">Date</th>
                <th className="px-3 py-2">Retailer</th>
                <th className="px-3 py-2">Order #</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Items</th>
                <th className="px-3 py-2">Total</th>
                <th className="px-3 py-2">Tracking</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {orders.map((order) => (
                <Fragment key={order.id}>
                  <tr
                    className="cursor-pointer border-b border-zinc-100 last:border-0 hover:bg-zinc-50"
                    onClick={() => toggle(order.id)}
                  >
                    <td className="px-3 py-2 text-zinc-400">
                      {expanded.has(order.id) ? "▾" : "▸"}
                    </td>
                    <td className="px-3 py-2">{formatDate(order.order_date)}</td>
                    <td className="px-3 py-2 font-medium">
                      {retailerName.get(order.retailer_id) ?? "…"}
                    </td>
                    <td className="px-3 py-2 text-zinc-600">{order.order_number ?? "—"}</td>
                    <td className="px-3 py-2">
                      {order.received_at ? (
                        <span
                          className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700"
                          title={`Received ${formatDate(order.received_at)}`}
                        >
                          Received
                        </span>
                      ) : (
                        <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">
                          Pending
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      {order.items.reduce((total, item) => total + item.quantity, 0)} across{" "}
                      {order.items.length} line{order.items.length === 1 ? "" : "s"}
                    </td>
                    <td className="px-3 py-2">{orderTotal(order)}</td>
                    <td className="px-3 py-2">
                      {order.tracking_url ? (
                        <a
                          href={order.tracking_url}
                          target="_blank"
                          rel="noreferrer"
                          onClick={(event) => event.stopPropagation()}
                          className="text-indigo-600 hover:underline"
                        >
                          {order.tracking_number ?? "link"}
                        </a>
                      ) : (
                        (order.tracking_number ?? "—")
                      )}
                    </td>
                    <td className="px-3 py-2" onClick={(event) => event.stopPropagation()}>
                      <div className="flex justify-end gap-1">
                        {!order.received_at && (
                          <Button variant="primary" onClick={() => receive(order)}>
                            Receive
                          </Button>
                        )}
                        <Button
                          variant="secondary"
                          onClick={() => setModal({ mode: "edit", order })}
                        >
                          Edit
                        </Button>
                        <Button variant="danger" onClick={() => remove(order)}>
                          Delete
                        </Button>
                      </div>
                    </td>
                  </tr>
                  {expanded.has(order.id) && (
                    <tr className="border-b border-zinc-100 bg-zinc-50/60 last:border-0">
                      <td />
                      <td colSpan={7} className="px-3 py-2">
                        <ul className="space-y-1">
                          {order.items.map((item) => {
                            const label =
                              item.item_type === "kit"
                                ? (itemName.get(item.spawned_kit_ids[0] ?? "") ?? "kit")
                                : (itemName.get(item.catalog_ref_id ?? "") ?? item.item_type);
                            return (
                              <li key={item.id} className="flex items-center gap-3 text-sm">
                                <span className="w-24 rounded bg-zinc-200 px-1.5 py-0.5 text-center text-xs text-zinc-600">
                                  {item.item_type}
                                </span>
                                <span className="font-medium">{label}</span>
                                <span className="text-zinc-500">
                                  {item.quantity} ×{" "}
                                  {formatMoney(item.unit_price_minor, item.currency_code)}
                                </span>
                                {item.item_type === "kit" && (
                                  <span className="text-xs text-zinc-400">
                                    spawned {item.spawned_kit_ids.length} kit
                                    {item.spawned_kit_ids.length === 1 ? "" : "s"}
                                  </span>
                                )}
                              </li>
                            );
                          })}
                        </ul>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState>
          {isLoading ? "Loading…" : "No orders yet — record one and it will spawn your kits."}
        </EmptyState>
      )}

      {modal && (
        <OrderFormModal
          order={modal.mode === "edit" ? modal.order : undefined}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
