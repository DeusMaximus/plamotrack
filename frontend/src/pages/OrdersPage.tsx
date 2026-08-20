import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useMemo, useRef, useState } from "react";
import type {
  Control,
  FieldErrors,
  UseFormRegister,
  UseFormSetValue,
  UseFormWatch,
} from "react-hook-form";
import { Controller, useFieldArray, useForm } from "react-hook-form";

import { api, ApiError, metaQuery } from "../api/client";
import type {
  ItemType,
  Order,
  OrderItemUpsert,
  OrderUpdate,
} from "../api/types";
import type { CatalogSelection } from "../components/CatalogItemPicker";
import { CatalogItemPicker } from "../components/CatalogItemPicker";
import { ExportCsvButton } from "../components/ExportCsvButton";
import { Modal } from "../components/Modal";
import { Button, EmptyState, ErrorBanner, Field, Input, Select } from "../components/ui";
import {
  currencyOptions,
  formatDate,
  formatMoney,
  isoToLocalDateInput,
  localMidnightISO,
  majorToMinor,
  minorToMajor,
  stepFor,
  todayISO,
} from "../lib/format";

interface LineValues {
  id?: string;
  item_type: ItemType;
  quantity: number;
  /** The currency this line was purchased in. Held per line, not read off the
   *  order header: the schema stores one code per line and REST, MCP and CSV can
   *  all write an order whose lines disagree. Reading the header instead meant a
   *  ¥1200 line on an A$ order was re-scaled to A$120.00 by any edit at all. */
  currency_code: string;
  unit_price: string;
  /** The §6 snapshot, in major units of `converted_currency_code`. "" = none. */
  converted_price: string;
  /** The currency the stored snapshot was taken in — which may not be today's
   *  reference currency, and that difference is the whole point of §6. */
  converted_currency_code: string | null;
  kit_name: string;
  kit_grade: string;
  /** "" = derive from the grade, matching the API. A kit whose scale was set
   *  deliberately must survive an edit that never mentions it. */
  kit_scale: string;
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
  /** The arrival date (#93). On a create it rides the `received` flag; on an edit
   *  of a received order it corrects the stored receipt — sent only when dirty,
   *  because a date-only field can't restate the stored *instant* losslessly. */
  received_date: string;
  /** The ship date (#95), edit-only and the same dirty-only correction shape —
   *  shipping itself goes through the Ship dialog, not this form. */
  shipped_date: string;
  items: LineValues[];
}

function emptyLine(currency: string): LineValues {
  return {
    item_type: "kit",
    quantity: 1,
    currency_code: currency,
    unit_price: "",
    converted_price: "",
    converted_currency_code: null,
    kit_name: "",
    kit_grade: "",
    kit_scale: "",
    kit_number: "",
    kit_status: "ordered",
    catalog: null,
  };
}

/** Any `true` anywhere inside react-hook-form's nested dirty-field tree.
 *
 * Checking the object's own truthiness isn't enough: an untouched line can still be
 * present as `{}`, and a nested `catalog` shows up as an object rather than a flag. */
function anyDirty(value: unknown): boolean {
  if (value === null || typeof value !== "object") return value === true;
  return Object.values(value).some(anyDirty);
}

function orderToFormValues(order: Order, catalogName: Map<string, string>): OrderFormValues {
  return {
    retailer_id: order.retailer_id,
    order_date: order.order_date,
    order_number: order.order_number ?? "",
    currency_code: order.currency_code,
    // `=== null`, not falsy: free shipping is a recorded 0, and reading it as
    // "no value" turned it back into null on the next save.
    shipping_cost:
      order.shipping_cost_minor === null
        ? ""
        : minorToMajor(order.shipping_cost_minor, order.currency_code),
    delivery_service: order.delivery_service ?? "",
    tracking_number: order.tracking_number ?? "",
    tracking_url: order.tracking_url ?? "",
    received: order.received_at !== null,
    received_date: order.received_at === null ? "" : isoToLocalDateInput(order.received_at),
    shipped_date: order.shipped_at === null ? "" : isoToLocalDateInput(order.shipped_at),
    items: order.items.map((item) => {
      // Read off the order being edited, not a cached kit list. The line can only
      // show one set of kit fields, so it shows the first spawned kit's — the
      // service compares against that same kit to decide what an edit restated,
      // and the API orders them so "first" is stable across reads (#65).
      const firstKit = item.kits[0];
      return {
        id: item.id,
        item_type: item.item_type,
        quantity: item.quantity,
        currency_code: item.currency_code,
        unit_price: minorToMajor(item.unit_price_minor, item.currency_code),
        // In the snapshot's own currency, not the line's — a JPY purchase with an
        // AUD snapshot would otherwise be read with yen's zero decimal places.
        converted_price:
          item.converted_price_minor === null || item.converted_currency_code === null
            ? ""
            : minorToMajor(item.converted_price_minor, item.converted_currency_code),
        converted_currency_code: item.converted_currency_code,
        kit_name: firstKit?.name ?? "",
        kit_grade: firstKit?.grade ?? "",
        kit_scale: firstKit?.scale ?? "",
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

/** Whether the browser may compute this line's §6 snapshot instead of carrying one.
 *
 * Only a line being *created* in the instance's own currency qualifies: at entry,
 * in that currency, the converted amount is the price, and no rate is involved.
 * Anything already stored is left to the field below — the reference currency, the
 * purchase currency and the unit price are all things a recorded snapshot is
 * allowed to disagree with (issue #3), so none of them may overrule one. */
function snapshotIsDerivable(
  lineId: string | undefined,
  lineCurrency: string,
  referenceCurrency: string,
): boolean {
  return lineId === undefined && lineCurrency === referenceCurrency;
}

function toOrderItem(line: LineValues, referenceCurrency: string): OrderItemUpsert {
  const currency = line.currency_code;
  const unitPriceMinor = majorToMinor(line.unit_price, currency);
  // A snapshot already taken keeps its own currency; a newly typed one is in the
  // instance's. Either way the amount below is read with that code's decimals.
  const snapshotCode = line.converted_currency_code ?? referenceCurrency;
  let converted: number | null;
  if (snapshotIsDerivable(line.id, currency, referenceCurrency)) {
    converted = unitPriceMinor;
  } else if (line.converted_price.trim() === "") {
    // Explicit null, not omission: on an edit the server reads that as "clear it",
    // which is what an emptied field means. A blank field on a line that never had
    // a snapshot lands on the same null and invents nothing.
    converted = null;
  } else {
    converted = majorToMinor(line.converted_price, snapshotCode);
  }
  const base = {
    id: line.id,
    quantity: Number(line.quantity),
    unit_price_minor: unitPriceMinor,
    currency_code: currency,
    converted_price_minor: converted,
    converted_currency_code: converted === null ? null : snapshotCode,
  };
  if (line.item_type === "kit") {
    return {
      ...base,
      item_type: "kit",
      kit: {
        name: line.kit_name,
        grade: line.kit_grade,
        // Blank sends null, which the API reads two different ways by design: on a
        // *new* line it means "derive from the grade", and on an edit it means "not
        // mentioned", so the stored kits keep whatever they have. A kit can be given
        // no scale at all from the Kits page, and deriving that back into 1/144 on
        // the way past is exactly what #69 was.
        //
        // So clearing this field no longer clears anything — that belongs on the
        // Kits page, which can say null and mean it. Same for the kit number below.
        scale: line.kit_scale.trim() || null,
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
  referenceCurrency,
}: {
  index: number;
  control: Control<OrderFormValues>;
  register: UseFormRegister<OrderFormValues>;
  watch: UseFormWatch<OrderFormValues>;
  setValue: UseFormSetValue<OrderFormValues>;
  errors: FieldErrors<OrderFormValues>;
  onRemove: () => void;
  canRemove: boolean;
  referenceCurrency: string;
}) {
  const itemType = watch(`items.${index}.item_type`);
  const lineErrors = errors.items?.[index];
  // This line's own currency, never the order header's. Every amount below is
  // read and written with it, so a line recorded in another currency keeps its
  // decimals and its code through an edit that never mentions either.
  const lineCurrency = watch(`items.${index}.currency_code`);
  // Shown exactly when the browser can't derive the snapshot itself — so what the
  // form displays and what toOrderItem submits are decided by the same rule.
  const snapshotCode = watch(`items.${index}.converted_currency_code`) ?? referenceCurrency;
  const showSnapshot = !snapshotIsDerivable(
    watch(`items.${index}.id`),
    lineCurrency,
    referenceCurrency,
  );

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
          step={stepFor(lineCurrency)}
          min={0}
          aria-label="Unit price"
          placeholder="Unit price"
          className="!w-28"
          {...register(`items.${index}.unit_price`, { required: "required" })}
        />
        {/* Stated, not editable: the header picker sets it for new lines, and a
            recorded line keeps what it was bought in. Shown so a mixed-currency
            order — which REST, MCP and CSV can all create — is legible here. */}
        <span className="text-sm text-zinc-600">{lineCurrency}</span>
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
        // A third for the name, two thirds for the four short fields — four of
        // them in half the row left the status select too narrow to read.
        <div className="grid grid-cols-3 gap-2">
          <Input
            placeholder="Kit name *"
            {...register(`items.${index}.kit_name`, { required: "Kit name is required" })}
          />
          <div className="col-span-2 grid grid-cols-4 gap-2">
            <Input
              placeholder="Grade *"
              {...register(`items.${index}.kit_grade`, { required: "Grade is required" })}
            />
            <Input
              aria-label="Scale"
              placeholder="Scale"
              title="Blank = derived from the grade"
              {...register(`items.${index}.kit_scale`)}
            />
            <Input placeholder="Kit #" {...register(`items.${index}.kit_number`)} />
            <Select {...register(`items.${index}.kit_status`)}>
              <option value="ordered">Ordered</option>
              <option value="pre_ordered">Pre-ordered</option>
            </Select>
          </div>
          {(lineErrors?.kit_name || lineErrors?.kit_grade) && (
            <span className="col-span-3 text-xs text-red-600">
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

      {showSnapshot && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm text-zinc-500">≈</span>
          <Input
            type="number"
            // The snapshot's own currency, not the order's — §6 lets them differ.
            step={stepFor(snapshotCode)}
            min={0}
            aria-label="Converted price"
            placeholder="Converted price"
            className="!w-28"
            {...register(`items.${index}.converted_price`)}
          />
          <span className="text-sm text-zinc-600">{snapshotCode}</span>
          <span className="text-xs text-zinc-500">
            what this cost at entry — recorded once, never recalculated. Blank for none.
          </span>
        </div>
      )}
    </div>
  );
}

/** Gate, so the form below is only ever *mounted* with everything it reconstructs
 * the stored order from.
 *
 * It has to be a separate component rather than an early return inside the form:
 * hooks run before any return, so `useForm` would already have captured its
 * defaultValues, and react-hook-form does not revisit defaults when a query later
 * resolves. Not rendering isn't the same as not mounting.
 *
 * `meta` supplies the reference currency. The other four are what an *edit* rebuilds
 * a line from — a kit line's name, grade, scale and number live on the spawned kits,
 * and a catalog line's label on the catalog row. Mounting before they arrive filled
 * the form with blanks and then wrote those blanks back, so a cold edit silently
 * stripped kit_number and scale. A new order needs none of them, hence the `!order`.
 *
 * In practice OrdersPage warms all five, so the loading state is rarely seen —
 * "rarely" being exactly why the bug would have survived. */
function OrderFormModal({ order, onClose }: { order?: Order; onClose: () => void }) {
  const { data: meta } = useQuery(metaQuery);
  const { data: tools } = useQuery({ queryKey: ["tools"], queryFn: api.listTools });
  const { data: consumables } = useQuery({
    queryKey: ["consumables"],
    queryFn: api.listConsumables,
  });
  const { data: upgrades } = useQuery({ queryKey: ["upgrades"], queryFn: api.listUpgrades });

  // Kit details are no longer in this list: they arrive on the order itself, so
  // there is no second cache to be stale. What's left is only the catalog naming
  // for existing lines, which the order payload genuinely doesn't carry.
  //
  // These are still presence checks, and presence is all they can be — TanStack
  // serves a cached array instantly and refetches behind it, so "arrived" never
  // means "fresh". That was survivable for kit details only because it isn't kit
  // details any more; a stale catalog name is a display string the form rewrites
  // nothing with (#65).
  const hydrated = !order || (tools && consumables && upgrades);
  if (!meta || !hydrated) {
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
      catalog={[...(tools ?? []), ...(consumables ?? []), ...(upgrades ?? [])]}
    />
  );
}

function OrderForm({
  order,
  onClose,
  referenceCurrency,
  catalog,
}: {
  order?: Order;
  onClose: () => void;
  referenceCurrency: string;
  catalog: { id: string; name: string }[];
}) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [newRetailerName, setNewRetailerName] = useState<string | null>(null);
  // Two guards on the inline create, for two different readers: the ref is what
  // stops a second click that lands before React has re-rendered (#49 — a
  // double-click made two shops); the state is what greys the button out.
  const addingRetailer = useRef(false);
  const [retailerPending, setRetailerPending] = useState(false);
  const { data: retailers } = useQuery({ queryKey: ["retailers"], queryFn: api.listRetailers });

  // Snapshotted once per open, deliberately: react-hook-form owns these values
  // from mount onwards and re-deriving them would discard what the user typed.
  // Safe to key on the order id alone because the gate above has already resolved
  // `kits` and `catalog` — they cannot arrive after the first render.
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
        received_date: todayISO(),
        shipped_date: "",
        items: [emptyLine(referenceCurrency)],
      };
    }
    const catalogName = new Map(catalog.map((row) => [row.id, row.name]));
    return orderToFormValues(order, catalogName);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- snapshot once per open
  }, [order?.id]);

  const {
    register,
    control,
    getValues,
    handleSubmit,
    watch,
    setValue,
    formState: { errors, isSubmitting, dirtyFields },
  } = useForm<OrderFormValues>({ defaultValues: defaults });
  const { fields, append, remove } = useFieldArray({ control, name: "items" });

  const addRetailer = async () => {
    const name = newRetailerName?.trim();
    if (!name || addingRetailer.current) return;
    addingRetailer.current = true;
    setRetailerPending(true);
    try {
      const created = await api.createRetailer({ name });
      await queryClient.invalidateQueries({ queryKey: ["retailers"] });
      setValue("retailer_id", created.id);
      setNewRetailerName(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not add retailer");
    } finally {
      addingRetailer.current = false;
      setRetailerPending(false);
    }
  };

  const onSubmit = handleSubmit(async (values) => {
    setError(null);
    // A length change covers add and remove, which `dirtyFields` cannot describe —
    // it tracks fields, and a deleted line has none.
    const lineDirty =
      !order || values.items.length !== order.items.length || anyDirty(dirtyFields.items);
    const payload: OrderUpdate = {
      retailer_id: values.retailer_id,
      order_date: values.order_date,
      order_number: values.order_number || null,
      currency_code: values.currency_code,
      // Only an empty field means "no shipping cost". A typed 0 is free postage,
      // which is a different fact and has to survive the round trip.
      shipping_cost_minor:
        values.shipping_cost.trim() === ""
          ? null
          : majorToMinor(values.shipping_cost, values.currency_code),
      delivery_service: values.delivery_service || null,
      tracking_number: values.tracking_number || null,
      tracking_url: values.tracking_url || null,
      // Omitted entirely when the edit never touched a line. `items: undefined`
      // means "leave the lines alone" to the API, and sending them anyway is how a
      // tracking-number change reached the kits at all (#65) — every save re-ran
      // the whole dispatch diff. A new order still sends its lines below; only an
      // edit can decline to.
      items: lineDirty
        ? values.items.map((line) => toOrderItem(line, referenceCurrency))
        : undefined,
    };
    // Correction only, and only when actually touched: a date field can't restate
    // the stored receipt *instant* losslessly, so an edit that never opened it
    // must not send it back — round-tripping would flatten a real arrival time
    // to midnight. Sent as local midnight in the browser's own offset (#93).
    if (order?.received_at && dirtyFields.received_date && values.received_date) {
      payload.received_at = localMidnightISO(values.received_date);
    }
    if (order?.shipped_at && dirtyFields.shipped_date && values.shipped_date) {
      payload.shipped_at = localMidnightISO(values.shipped_date);
    }
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
          // Today = "it arrived now": omit the date so the server stamps the
          // actual moment rather than midnight. A backdate is sent explicitly.
          received_at:
            values.received && values.received_date && values.received_date !== todayISO()
              ? localMidnightISO(values.received_date)
              : undefined,
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
                <Button type="button" onClick={addRetailer} disabled={retailerPending}>
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
                onChange: (event) => {
                  // Lines being created here follow the picker, so entering an
                  // order in one currency stays a single choice. A line that is
                  // already recorded keeps the code it was bought in — restating
                  // that from the header is the defect this whole change is about.
                  const next = (event.target as HTMLInputElement).value;
                  getValues("items").forEach((line, index) => {
                    if (line.id === undefined) {
                      setValue(`items.${index}.currency_code`, next);
                    }
                  });
                },
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
            <Input
              type="number"
              step={stepFor(watch("currency_code"))}
              min={0}
              {...register("shipping_cost")}
            />
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
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <label className="flex items-center gap-2 text-sm text-zinc-700">
              <input
                type="checkbox"
                {...register("received")}
                className="h-4 w-4 accent-indigo-600"
              />
              Already in hand (store purchase / delivery arrived) — stock counts immediately
            </label>
            {watch("received") && (
              <label className="flex items-center gap-2 text-sm text-zinc-700">
                on
                <Input
                  type="date"
                  max={todayISO()}
                  {...register("received_date")}
                  className="w-auto"
                />
              </label>
            )}
          </div>
        )}
        {order?.received_at && (
          <div className="grid grid-cols-3 gap-3">
            <Field label="Received on">
              <Input type="date" max={todayISO()} {...register("received_date")} />
            </Field>
            <p className="col-span-2 self-end pb-2 text-xs text-zinc-500">
              Correcting this re-dates the kits this delivery brought in — unless they have
              been moved since, in which case they keep their own dates.
            </p>
          </div>
        )}
        {order?.shipped_at && (
          <div className="grid grid-cols-3 gap-3">
            <Field label="Shipped on">
              <Input type="date" max={todayISO()} {...register("shipped_date")} />
            </Field>
            <p className="col-span-2 self-end pb-2 text-xs text-zinc-500">
              Correcting this re-dates kits still marked In Transit by that shipment; kits
              moved since keep their own dates.
            </p>
          </div>
        )}

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-zinc-700">Items</h3>
            <Button
              type="button"
              variant="secondary"
              onClick={() => append(emptyLine(getValues("currency_code")))}
            >
              + Add line
            </Button>
          </div>
          {order && (
            <p className="text-xs text-zinc-500">
              A kit detail you change here is applied to every kit this line spawned; one you
              leave alone stays as it is on each of them, so kits edited individually keep
              their own. Removing a line undoes it (kits deleted, stock reversed) — kits that
              are building/complete, rated, or have photos are protected.
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
              referenceCurrency={referenceCurrency}
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
  // Names for the list below only. The editor deliberately does *not* read kit
  // details from here any more — it takes them from the order it is editing, so a
  // stale entry can never be written back (#65). Stale here is a label in a table.
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

  // Receiving asks for the arrival date (#93), so it gets a real dialog rather
  // than window.confirm — a store purchase logged tonight arrived today, but a
  // box unpacked from last week didn't. Shipping mirrors it (#95).
  const [receiving, setReceiving] = useState<Order | null>(null);
  const [shipping, setShipping] = useState<Order | null>(null);

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
                    {/* Narrower padding than its neighbours: the 24x24 control
                        is wider than the bare glyph it replaced, and the default
                        px-3 pushed the table enough to wrap retailer names. */}
                    <td className="px-1 py-2 text-zinc-400">
                      {/* A real button, because the row's own click handler is
                          unreachable from a keyboard — nothing focuses a <tr>.
                          The row click stays as a convenience for the mouse, so
                          this stops propagation or the two would cancel out. */}
                      <button
                        type="button"
                        aria-expanded={expanded.has(order.id)}
                        // Names the retailer as well as the date: two orders
                        // placed on one day would otherwise share an accessible
                        // name, and the date alone just restates the cell beside
                        // it. The receive/delete confirmations already say the
                        // retailer for the same reason.
                        aria-label={`${expanded.has(order.id) ? "Hide" : "Show"} line items for the ${formatDate(order.order_date)} order from ${retailerName.get(order.retailer_id) ?? "an unknown retailer"}`}
                        // 24x24: WCAG 2.2 target-size minimum. The row click is
                        // an equivalent alternative and would technically exempt
                        // it, but leaning on that inside an accessibility fix is
                        // not worth the four characters it saves.
                        className="flex h-6 w-6 items-center justify-center rounded leading-none hover:bg-zinc-200 hover:text-zinc-600 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                        onClick={(event) => {
                          event.stopPropagation();
                          toggle(order.id);
                        }}
                      >
                        {expanded.has(order.id) ? "▾" : "▸"}
                      </button>
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
                      ) : order.shipped_at ? (
                        <span
                          className="rounded-full bg-sky-100 px-2 py-0.5 text-xs font-medium text-sky-700"
                          title={`Shipped ${formatDate(order.shipped_at)}`}
                        >
                          Shipped
                        </span>
                      ) : isPreOrder(order) ? (
                        // Derived, not stored (#95): a pending order whose kits are
                        // all pre_ordered is the pre-order; once it ships nobody
                        // cares, so there is nothing to persist.
                        <span
                          className="rounded-full bg-violet-100 px-2 py-0.5 text-xs font-medium text-violet-700"
                          title="All kits on this order are pre-ordered — not due yet"
                        >
                          Pre-order
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
                        {!order.received_at && !order.shipped_at && (
                          <Button variant="secondary" onClick={() => setShipping(order)}>
                            Ship
                          </Button>
                        )}
                        {!order.received_at && (
                          <Button variant="primary" onClick={() => setReceiving(order)}>
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
      {receiving && (
        <ReceiveOrderModal
          order={receiving}
          retailerLabel={retailerName.get(receiving.retailer_id) ?? "this retailer"}
          onClose={() => setReceiving(null)}
          onReceived={invalidateAll}
        />
      )}
      {shipping && (
        <ShipOrderModal
          order={shipping}
          retailerLabel={retailerName.get(shipping.retailer_id) ?? "this retailer"}
          onClose={() => setShipping(null)}
          onShipped={invalidateAll}
        />
      )}
    </div>
  );
}

/** A pending order whose kits are all still pre_ordered is the pre-order (#95).
 *  Derived from the kits already in the payload — nothing is persisted, because
 *  the distinction stops mattering the moment the order ships. Catalog-only
 *  orders carry no signal and read as ordinary pending, by decision. */
function isPreOrder(order: Order): boolean {
  const statuses = order.items.flatMap((item) => item.kits.map((kit) => kit.status));
  return statuses.length > 0 && statuses.every((status) => status === "pre_ordered");
}

function ReceiveOrderModal({
  order,
  retailerLabel,
  onClose,
  onReceived,
}: {
  order: Order;
  retailerLabel: string;
  onClose: () => void;
  onReceived: () => Promise<unknown>;
}) {
  const [date, setDate] = useState(todayISO());
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      // Today = "it arrived now": no body, so the server stamps the actual
      // moment. A backdate is midnight local, in the browser's own offset (#93).
      await api.receiveOrder(
        order.id,
        date && date !== todayISO() ? { received_at: localMidnightISO(date) } : undefined,
      );
      await onReceived();
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Receive failed");
      setBusy(false);
    }
  };

  return (
    <Modal title="Receive order" onClose={onClose}>
      <div className="space-y-4">
        <ErrorBanner message={error} />
        <p className="text-sm text-zinc-700">
          Mark the {formatDate(order.order_date)} order from {retailerLabel} as received?
          Catalog stock will be applied and kits still in the ordering pipeline move to
          Backlog.
        </p>
        <Field label="Received on">
          <Input
            type="date"
            max={todayISO()}
            value={date}
            onChange={(event) => setDate(event.target.value)}
          />
        </Field>
        <p className="text-xs text-zinc-500">
          Defaults to today — pick the actual delivery date when logging one after the fact.
        </p>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button type="button" onClick={submit} disabled={busy}>
            Receive
          </Button>
        </div>
      </div>
    </Modal>
  );
}

function ShipOrderModal({
  order,
  retailerLabel,
  onClose,
  onShipped,
}: {
  order: Order;
  retailerLabel: string;
  onClose: () => void;
  onShipped: () => Promise<unknown>;
}) {
  const [date, setDate] = useState(todayISO());
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      // Today = "it shipped now": no body, so the server stamps the actual
      // moment. A backdate is midnight local, in the browser's own offset (#93).
      await api.shipOrder(
        order.id,
        date && date !== todayISO() ? { shipped_at: localMidnightISO(date) } : undefined,
      );
      await onShipped();
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Ship failed");
      setBusy(false);
    }
  };

  return (
    <Modal title="Mark shipped" onClose={onClose}>
      <div className="space-y-4">
        <ErrorBanner message={error} />
        <p className="text-sm text-zinc-700">
          Mark the {formatDate(order.order_date)} order from {retailerLabel} as shipped? Kits
          still waiting on the retailer move to In Transit. Stock is not touched — that
          happens when the order is received.
        </p>
        <Field label="Shipped on">
          <Input
            type="date"
            max={todayISO()}
            value={date}
            onChange={(event) => setDate(event.target.value)}
          />
        </Field>
        <p className="text-xs text-zinc-500">
          Defaults to today — pick the date from the shipping notification when logging one
          after the fact.
        </p>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button type="button" onClick={submit} disabled={busy}>
            Ship
          </Button>
        </div>
      </div>
    </Modal>
  );
}
