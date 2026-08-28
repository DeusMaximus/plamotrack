import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import type {
  Control,
  FieldErrors,
  UseFormRegister,
  UseFormSetValue,
  UseFormWatch,
} from "react-hook-form";
import { Controller, useFieldArray, useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";

import { api, ApiError, metaQuery } from "../api/client";
import type {
  ItemType,
  Order,
  OrderItemUpsert,
  OrderUpdate,
} from "../api/types";
import { ITEM_TYPES } from "../api/types";
import type { CatalogSelection } from "../components/CatalogItemPicker";
import { CatalogItemPicker } from "../components/CatalogItemPicker";
import i18n from "../i18n";
import { counted, countedPhrase, dateWithElapsed, itemTypeLabel, itemTypeTitle } from "../lib/labels";
import { usePresentationVersion } from "../lib/presentation";
import { ExportCsvButton } from "../components/ExportCsvButton";
import { Modal } from "../components/Modal";
import { Button, EmptyState, ErrorBanner, Field, Input, Select } from "../components/ui";
import {
  currencyOptions,
  formatDate,
  formatMoney,
  formatNumber,
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
  /** Carried per line because the API stores it per kit and an edit that bumps a
   *  line's quantity spawns the extra kits with this status — but no longer shown
   *  per line (#120): the browser sets it order-wide. On a create the Pre-order
   *  toggle overwrites every line at submit; on an edit it round-trips the first
   *  spawned kit's status, and a line added mid-edit inherits the order's own
   *  derived pre-order state, so a new kit joins its shipment rather than
   *  defaulting against it. */
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
  /** The ship date (#95), same shape. Since #120 both date fields also cover the
   *  *transition* on an order that doesn't hold the instant yet — the submit
   *  handler dispatches to ship/receive instead of the PATCH for that case. */
  shipped_date: string;
  /** Create only (#120): one order-wide flag, applied to every kit line at
   *  submit. Pre-order vs ordered is a fact about the shipment, not the line —
   *  a retailer splitting a shipment becomes two plamotrack orders. */
  pre_order: boolean;
  items: LineValues[];
}

function emptyLine(currency: string, kitStatus: LineValues["kit_status"] = "ordered"): LineValues {
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
    kit_status: kitStatus,
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
    // Not read on an edit — the toggle is create-only (#120); after entry the
    // order's pre-order state is derived from its kits (`isPreOrder`).
    pre_order: false,
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
                name: catalogName.get(item.catalog_ref_id) ?? i18n.t("orders.unknownItem"),
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

function toOrderItem(
  line: LineValues,
  referenceCurrency: string,
  kitRestated: boolean,
): OrderItemUpsert {
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
    // A stored line whose kit fields this edit never touched says nothing about
    // them (#67): the server compares stated details against the live first kit
    // and applies any difference, and a value echoed from a stale read is
    // indistinguishable from a typed one. Omitting `kit` is how the form avoids
    // reverting an out-of-band change with values it merely displayed. A new
    // line (no id) always states details — it has kits to spawn.
    if (line.id !== undefined && !kitRestated) {
      return { ...base, item_type: "kit" };
    }
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
        scale: line.catalog.scale || null,
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
  const { t } = useTranslation();
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
          {ITEM_TYPES.map((type) => (
            <option key={type} value={type}>
              {itemTypeTitle(type)}
            </option>
          ))}
        </Select>
        <Field label="" className="!mb-0 w-20">
          <Input
            type="number"
            min={1}
            aria-label={t("orders.quantity")}
            {...register(`items.${index}.quantity`, { required: true, min: 1 })}
          />
        </Field>
        <Input
          type="number"
          step={stepFor(lineCurrency)}
          min={0}
          aria-label={t("orders.unitPrice")}
          placeholder={t("orders.unitPrice")}
          className="!w-28"
          {...register(`items.${index}.unit_price`, { required: t("validation.requiredField") })}
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
            aria-label={t("orders.removeLine")}
            className="rounded p-1 text-zinc-400 hover:bg-zinc-200 hover:text-zinc-600"
          >
            ✕
          </button>
        )}
      </div>

      {itemType === "kit" ? (
        // A third for the name, two thirds for the three short fields. No status
        // select here any more (#120): pre-order is order-wide, set by the toggle
        // on a create — a per-line picker rendered an order-level fact as if each
        // line could ship on its own.
        <div className="grid grid-cols-3 gap-2">
          <Input
            placeholder={t("orders.kitNamePlaceholder")}
            {...register(`items.${index}.kit_name`, { required: t("validation.kitNameRequired") })}
          />
          <div className="col-span-2 grid grid-cols-3 gap-2">
            <Input
              placeholder={t("orders.gradePlaceholder")}
              {...register(`items.${index}.kit_grade`, { required: t("validation.gradeRequired") })}
            />
            <Input
              aria-label={t("orders.scalePlaceholder")}
              placeholder={t("orders.scalePlaceholder")}
              title={t("orders.scaleTooltip")}
              {...register(`items.${index}.kit_scale`)}
            />
            <Input placeholder={t("orders.kitNumberPlaceholder")} {...register(`items.${index}.kit_number`)} />
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
              if (!value) return t("validation.catalogSelection");
              if (value.mode === "new") {
                if (!value.name.trim()) return t("validation.newItemName");
                if (itemType === "upgrade" && !value.manufacturer.trim())
                  return t("validation.newUpgradeManufacturer");
                // Everything else — tools, consumables, display items — needs a
                // category. Display items alone may leave the manufacturer blank.
                if (itemType !== "upgrade" && !value.category.trim())
                  return t("validation.newItemCategory");
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
            aria-label={t("orders.convertedPrice")}
            placeholder={t("orders.convertedPrice")}
            className="!w-28"
            {...register(`items.${index}.converted_price`)}
          />
          <span className="text-sm text-zinc-600">{snapshotCode}</span>
          <span className="text-xs text-zinc-500">{t("orders.snapshotNote")}</span>
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
  const { t } = useTranslation();
  const { data: meta } = useQuery(metaQuery);
  // The order the caller has is the list's cached copy, stale for as long as
  // the page has been open (#67). Refetch it on every open and hydrate from
  // the answer — this shrinks the stale window from "page age" to "during this
  // edit"; the dirty-only kit payload below is what closes the rest.
  // isFetchedAfterMount is the load-bearing half: `data` alone serves whatever
  // the cache holds *while* refetching, which is the stale copy this exists to
  // replace. The gate below waits for an answer this open actually fetched.
  const {
    data: freshOrder,
    isFetchedAfterMount,
    error: freshOrderError,
  } = useQuery({
    queryKey: ["order", order?.id],
    queryFn: () => api.getOrder(order!.id),
    enabled: order !== undefined,
    refetchOnMount: "always",
    staleTime: 0,
    // A 404 will never succeed on retry — the order is gone, and three backoff
    // rounds only delay the message below. Anything else keeps the default.
    retry: (failureCount, err) =>
      !(err instanceof ApiError && err.status === 404) && failureCount < 3,
  });
  const queryClient = useQueryClient();
  const orderGone = freshOrderError instanceof ApiError && freshOrderError.status === 404;
  useEffect(() => {
    // The row the user clicked came from a list that predates the deletion —
    // refresh it so the stale row goes the same way the order did.
    if (orderGone) queryClient.invalidateQueries({ queryKey: ["orders"] });
  }, [orderGone, queryClient]);
  const { data: tools } = useQuery({ queryKey: ["tools"], queryFn: api.listTools });
  const { data: consumables } = useQuery({
    queryKey: ["consumables"],
    queryFn: api.listConsumables,
  });
  const { data: upgrades } = useQuery({ queryKey: ["upgrades"], queryFn: api.listUpgrades });
  const { data: displayItems } = useQuery({
    queryKey: ["display-items"],
    queryFn: api.listDisplayItems,
  });

  // Kit details are no longer in this list: they arrive on the order itself, so
  // there is no second cache to be stale. What's left is only the catalog naming
  // for existing lines, which the order payload genuinely doesn't carry.
  //
  // These are still presence checks, and presence is all they can be — TanStack
  // serves a cached array instantly and refetches behind it, so "arrived" never
  // means "fresh". That was survivable for kit details only because it isn't kit
  // details any more; a stale catalog name is a display string the form rewrites
  // nothing with (#65).
  // An error is not "still loading" (PR #154 review, P3-1): a failed fresh read
  // must say so, or a deleted order leaves this dialog on Loading… forever.
  // Closing is the recovery — on the 404 the invalidation above has already
  // removed the stale row, so there is nothing left to retry against.
  if (order && freshOrderError) {
    return (
      <Modal title={t("orders.editTitle")} onClose={onClose} wide>
        <ErrorBanner
          message={
            orderGone
              ? t("orders.orderGone")
              : t("orders.loadOrderFailed", {
                  message:
                    freshOrderError instanceof Error
                      ? freshOrderError.message
                      : t("orders.requestFailedFallback"),
                })
          }
        />
      </Modal>
    );
  }
  const hydrated =
    !order || (freshOrder && isFetchedAfterMount && tools && consumables && upgrades && displayItems);
  if (!meta || !hydrated) {
    return (
      <Modal title={order ? t("orders.editTitle") : t("orders.newTitle")} onClose={onClose} wide>
        <EmptyState>{t("common.loading")}</EmptyState>
      </Modal>
    );
  }
  return (
    <OrderForm
      order={order ? freshOrder : undefined}
      onClose={onClose}
      referenceCurrency={meta.reference_currency}
      catalog={[
        ...(tools ?? []),
        ...(consumables ?? []),
        ...(upgrades ?? []),
        ...(displayItems ?? []),
      ]}
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
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [newRetailerName, setNewRetailerName] = useState<string | null>(null);
  // Two guards on the inline create, for two different readers: the ref is what
  // stops a second click that lands before React has re-rendered (#49 — a
  // double-click made two shops); the state is what greys the button out.
  const addingRetailer = useRef(false);
  const [retailerPending, setRetailerPending] = useState(false);
  // One-way latches for the transition dispatch below (#120): if the PATCH lands
  // but a following ship/receive call fails, the resubmit must not replay the
  // call that succeeded — the server 409s the repeat, which would turn a fixable
  // date typo into a dead end. Refs, not state: nothing renders from them, and
  // the form unmounts on close so a fresh open starts clean.
  const applied = useRef({ shipped: false, received: false });
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
        pre_order: false,
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
      setError(err instanceof ApiError ? err.message : t("orders.addRetailerFailed"));
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
        ? values.items.map((line, index) => {
            // Per-line: were any of the KIT fields on this row actually edited?
            // The other line fields (quantity, price) travel regardless — only
            // the kit details are omit-able, because only they propagate (#67).
            const lineDirtyFields = dirtyFields.items?.[index];
            const kitRestated = anyDirty([
              lineDirtyFields?.kit_name,
              lineDirtyFields?.kit_grade,
              lineDirtyFields?.kit_scale,
              lineDirtyFields?.kit_number,
              lineDirtyFields?.kit_status,
            ]);
            return toOrderItem(line, referenceCurrency, kitRestated);
          })
        : undefined,
    };
    // The same two date fields do two jobs (#120). On an order that already
    // holds the instant they PATCH a *correction* — only when actually touched,
    // because a date field can't restate the stored instant losslessly, so an
    // edit that never opened it must not send it back (round-tripping would
    // flatten a real arrival time to midnight). On an order that doesn't, they
    // become the ship/receive *transition* below, after the PATCH: those stay
    // separate service calls, because receiving applies stock and advances kits
    // under a row lock (rule 2) — nothing a plain field edit may trigger
    // implicitly. Dates go out as local midnight in the browser's offset (#93).
    if (order?.received_at && dirtyFields.received_date && values.received_date) {
      payload.received_at = localMidnightISO(values.received_date);
    }
    if (order?.shipped_at && dirtyFields.shipped_date && values.shipped_date) {
      payload.shipped_at = localMidnightISO(values.shipped_date);
    }
    try {
      if (order) {
        await api.updateOrder(order.id, payload);
        // Ship before receive: an order may take both in one save, and shipping
        // is the earlier fact — receive advances the just-shipped kits onward.
        // Today = "it happened now": no body, so the server stamps the actual
        // moment rather than midnight, exactly as the old dialogs did.
        if (
          !order.shipped_at &&
          !applied.current.shipped &&
          dirtyFields.shipped_date &&
          values.shipped_date
        ) {
          await api.shipOrder(
            order.id,
            values.shipped_date !== todayISO()
              ? { shipped_at: localMidnightISO(values.shipped_date) }
              : undefined,
          );
          applied.current.shipped = true;
        }
        if (
          !order.received_at &&
          !applied.current.received &&
          dirtyFields.received_date &&
          values.received_date
        ) {
          await api.receiveOrder(
            order.id,
            values.received_date !== todayISO()
              ? { received_at: localMidnightISO(values.received_date) }
              : undefined,
          );
          applied.current.received = true;
        }
      } else {
        // The order-wide flag applied to every kit line (#120). In hand wins:
        // the server would land pre_ordered kits in backlog anyway on a received
        // order, but there is no reason to assert a status the form greyed out.
        const entryStatus: LineValues["kit_status"] =
          values.pre_order && !values.received ? "pre_ordered" : "ordered";
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
          items: values.items.map((line) =>
            toOrderItem(
              line.item_type === "kit" ? { ...line, kit_status: entryStatus } : line,
              referenceCurrency,
              true, // a create always states kit details — there is nothing stored to echo
            ),
          ),
        });
      }
      await Promise.all(
        ["orders", "kits", "tools", "consumables", "upgrades", "display-items"].map((key) =>
          queryClient.invalidateQueries({ queryKey: [key] }),
        ),
      );
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("common.requestFailed"));
    }
  });

  return (
    <Modal title={order ? t("orders.editTitle") : t("orders.newTitle")} onClose={onClose} wide>
      <form onSubmit={onSubmit} className="space-y-4">
        <ErrorBanner message={error} />

        <div className="grid grid-cols-3 gap-3">
          <Field label={t("orders.retailer")} required error={errors.retailer_id?.message}>
            {newRetailerName === null ? (
              <div className="flex gap-1">
                <Select {...register("retailer_id", { required: t("orders.pickRetailer") })}>
                  <option value="">{t("orders.selectRetailer")}</option>
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
                  placeholder={t("orders.newRetailerPlaceholder")}
                />
                <Button type="button" onClick={addRetailer} disabled={retailerPending}>
                  {t("common.add")}
                </Button>
                <Button type="button" variant="secondary" onClick={() => setNewRetailerName(null)}>
                  ✕
                </Button>
              </div>
            )}
          </Field>
          <Field label={t("orders.orderDate")} required>
            <Input type="date" {...register("order_date", { required: true })} />
          </Field>
          <Field label={t("orders.currency")} required>
            <Input
              list="currencies"
              {...register("currency_code", {
                required: true,
                pattern: { value: /^[A-Z]{3}$/, message: t("validation.currencyCode") },
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
          <Field label={t("orders.orderNumber")}>
            <Input
              {...register("order_number")}
              placeholder={t("orders.orderNumberPlaceholder")}
            />
          </Field>
          <Field label={t("orders.shippingCost")}>
            <Input
              type="number"
              step={stepFor(watch("currency_code"))}
              min={0}
              {...register("shipping_cost")}
            />
          </Field>
          <Field label={t("orders.deliveryService")}>
            <Input {...register("delivery_service")} placeholder={t("orders.deliveryServicePlaceholder")} />
          </Field>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <Field label={t("orders.trackingNumber")}>
            <Input {...register("tracking_number")} />
          </Field>
          <Field label={t("orders.trackingUrl")}>
            <Input {...register("tracking_url")} placeholder={t("common.urlPlaceholder")} />
          </Field>
        </div>

        {!order && (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <label className="flex items-center gap-2 text-sm text-zinc-700">
              <input
                type="checkbox"
                {...register("received", {
                  // In hand and pre-order contradict each other; ticking this
                  // clears the other rather than leaving a hidden yes standing.
                  onChange: (event) => {
                    if ((event.target as HTMLInputElement).checked) {
                      setValue("pre_order", false);
                    }
                  },
                })}
                className="h-4 w-4 accent-indigo-600"
              />
              {t("orders.alreadyInHand")}
            </label>
            {watch("received") && (
              <label className="flex items-center gap-2 text-sm text-zinc-700">
                {t("orders.receivedOnPrefix")}
                <Input
                  type="date"
                  max={todayISO()}
                  {...register("received_date")}
                  className="w-auto"
                />
              </label>
            )}
            {/* One flag for the whole order (#120): a retailer splitting a
                shipment becomes two plamotrack orders, so per-line pre-order
                status rendered an order-level fact as a line-level choice. */}
            <label
              className={`flex items-center gap-2 text-sm ${watch("received") ? "text-zinc-400" : "text-zinc-700"}`}
              title={watch("received") ? t("orders.inHandNotPreOrder") : undefined}
            >
              <input
                type="checkbox"
                disabled={watch("received")}
                {...register("pre_order")}
                className="h-4 w-4 accent-indigo-600"
              />
              {t("orders.preOrderToggle")}
            </label>
          </div>
        )}
        {/* Both dates in one place regardless of state (#120): on an order that
            already holds the instant the field corrects it; on one that doesn't,
            filling it performs the ship/receive transition on save. Which call
            goes out is decided in the submit handler above. */}
        {order && (
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Field label={t("orders.shippedOn")}>
                <Input type="date" max={todayISO()} {...register("shipped_date")} />
              </Field>
              <p className="mt-1 text-xs text-zinc-500">
                {order.shipped_at ? t("orders.shippedCorrectHelp") : t("orders.shippedSetHelp")}
              </p>
            </div>
            <div>
              <Field label={t("orders.receivedOn")}>
                <Input type="date" max={todayISO()} {...register("received_date")} />
              </Field>
              <p className="mt-1 text-xs text-zinc-500">
                {order.received_at ? t("orders.receivedCorrectHelp") : t("orders.receivedSetHelp")}
              </p>
            </div>
          </div>
        )}

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-zinc-700">{t("orders.itemsHeading")}</h3>
            <Button
              type="button"
              variant="secondary"
              onClick={() =>
                append(
                  emptyLine(
                    getValues("currency_code"),
                    // A line added mid-edit joins the order's shipment, so it
                    // inherits the order's derived pre-order state (#120). On a
                    // create the toggle overwrites this at submit anyway.
                    order && isPreOrder(order) ? "pre_ordered" : "ordered",
                  ),
                )
              }
            >
              {t("orders.addLine")}
            </Button>
          </div>
          {order && (
            <p className="text-xs text-zinc-500">{t("orders.editLinesHelp")}</p>
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
            {t("common.cancel")}
          </Button>
          <Button type="submit" disabled={isSubmitting}>
            {order ? t("orders.saveChanges") : t("orders.recordOrder")}
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
  // Re-render when the instance's presentation settings arrive or change —
  // the plain format helpers below read them per call (#174 review, P3-1).
  usePresentationVersion();
  const { t } = useTranslation();
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
  const { data: displayItems } = useQuery({
    queryKey: ["display-items"],
    queryFn: api.listDisplayItems,
  });
  // Warms the shared cache so the form modal has it the moment it opens.
  useQuery(metaQuery);

  const retailerName = useMemo(
    () => new Map((retailers ?? []).map((retailer) => [retailer.id, retailer.name])),
    [retailers],
  );
  const itemName = useMemo(() => {
    const map = new Map<string, string>();
    for (const kit of kits ?? []) map.set(kit.id, kit.name);
    for (const row of [
      ...(tools ?? []),
      ...(consumables ?? []),
      ...(upgrades ?? []),
      ...(displayItems ?? []),
    ]) {
      map.set(row.id, row.name);
    }
    return map;
  }, [kits, tools, consumables, upgrades, displayItems]);

  const invalidateAll = () =>
    Promise.all(
      ["orders", "kits", "tools", "consumables", "upgrades", "display-items"].map((key) =>
        queryClient.invalidateQueries({ queryKey: [key] }),
      ),
    );

  const remove = async (order: Order) => {
    const label = retailerName.get(order.retailer_id) ?? t("orders.thisOrder");
    if (
      !window.confirm(
        t("orders.confirmDelete", { date: formatDate(order.order_date), retailer: label }),
      )
    ) {
      return;
    }
    setActionError(null);
    try {
      await api.deleteOrder(order.id);
      await invalidateAll();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : t("common.deleteFailed"));
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
        <h1 className="text-2xl font-bold">{t("orders.title")}</h1>
        <div className="flex gap-2">
          <ExportCsvButton table="orders" />
          <Button onClick={() => setModal({ mode: "add" })}>{t("orders.newOrder")}</Button>
        </div>
      </div>

      <ErrorBanner message={actionError} />

      {isError ? (
        <ErrorBanner message={t("orders.loadFailed", { message: (error as Error).message })} />
      ) : orders?.length ? (
        <div className="overflow-x-auto rounded-lg border border-zinc-200 bg-white">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-zinc-200 text-start text-xs uppercase tracking-wide text-zinc-500">
                <th className="w-8 px-3 py-2" />
                <th className="px-3 py-2">{t("orders.headerDate")}</th>
                <th className="px-3 py-2">{t("orders.headerRetailer")}</th>
                <th className="px-3 py-2">{t("orders.headerOrderNumber")}</th>
                <th className="px-3 py-2">{t("orders.headerStatus")}</th>
                <th className="px-3 py-2">{t("orders.headerShipped")}</th>
                <th className="px-3 py-2">{t("orders.headerReceived")}</th>
                <th className="px-3 py-2">{t("orders.headerItems")}</th>
                <th className="px-3 py-2">{t("orders.headerTotal")}</th>
                <th className="px-3 py-2">{t("orders.headerTracking")}</th>
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
                        aria-label={t(
                          expanded.has(order.id) ? "orders.hideLineItems" : "orders.showLineItems",
                          {
                            date: formatDate(order.order_date),
                            retailer:
                              retailerName.get(order.retailer_id) ?? t("orders.unknownRetailer"),
                          },
                        )}
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
                    {/* No date tooltips on the pills any more — the Shipped and
                        Received columns beside them carry the dates for every
                        row at once, which is what the tooltip couldn't (#120). */}
                    <td className="px-3 py-2">
                      {order.received_at ? (
                        <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">
                          {t("orders.pillReceived")}
                        </span>
                      ) : order.shipped_at ? (
                        <span className="rounded-full bg-sky-100 px-2 py-0.5 text-xs font-medium text-sky-700">
                          {t("orders.pillShipped")}
                        </span>
                      ) : isPreOrder(order) ? (
                        // Derived, not stored (#95): a pending order whose kits are
                        // all pre_ordered is the pre-order; once it ships nobody
                        // cares, so there is nothing to persist.
                        <span
                          className="whitespace-nowrap rounded-full bg-violet-100 px-2 py-0.5 text-xs font-medium text-violet-700"
                          title={t("orders.preOrderTooltip")}
                        >
                          {t("orders.pillPreOrder")}
                        </span>
                      ) : (
                        <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">
                          {t("orders.pillPending")}
                        </span>
                      )}
                    </td>
                    {/* nowrap: "in transit · 6 d" split across lines reads as two
                        facts, and the dates never benefit from wrapping. */}
                    <td
                      className="whitespace-nowrap px-3 py-2 text-zinc-500"
                      title={t("orders.shippedTooltip")}
                    >
                      {order.shipped_at ? formatDate(order.shipped_at) : "—"}
                    </td>
                    <td
                      className="whitespace-nowrap px-3 py-2 text-zinc-500"
                      title={t("orders.receivedTooltip")}
                    >
                      {receivedCell(order)}
                    </td>
                    <td className="px-3 py-2">
                      {t(
                        "orders.acrossLines",
                        counted(
                          {
                            total: formatNumber(
                              order.items.reduce((total, item) => total + item.quantity, 0),
                            ),
                          },
                          order.items.length,
                        ),
                      )}
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
                          {order.tracking_number ?? t("orders.trackingLinkFallback")}
                        </a>
                      ) : (
                        (order.tracking_number ?? "—")
                      )}
                    </td>
                    <td className="px-3 py-2" onClick={(event) => event.stopPropagation()}>
                      {/* Ship and Receive are no longer row actions (#120) — both
                          transitions live in the Edit dialog, next to the fields
                          that correct them and the details a real status change
                          travels with. */}
                      <div className="flex justify-end gap-1">
                        <Button
                          variant="secondary"
                          onClick={() => setModal({ mode: "edit", order })}
                        >
                          {t("common.edit")}
                        </Button>
                        <Button variant="danger" onClick={() => remove(order)}>
                          {t("common.delete")}
                        </Button>
                      </div>
                    </td>
                  </tr>
                  {expanded.has(order.id) && (
                    <tr className="border-b border-zinc-100 bg-zinc-50/60 last:border-0">
                      <td />
                      <td colSpan={10} className="px-3 py-2">
                        <ul className="space-y-1">
                          {order.items.map((item) => {
                            const label =
                              item.item_type === "kit"
                                ? (itemName.get(item.spawned_kit_ids[0] ?? "") ?? itemTypeLabel("kit"))
                                : (itemName.get(item.catalog_ref_id ?? "") ??
                                  itemTypeLabel(item.item_type));
                            return (
                              <li key={item.id} className="flex items-center gap-3 text-sm">
                                <span className="w-24 rounded bg-zinc-200 px-1.5 py-0.5 text-center text-xs text-zinc-600">
                                  {itemTypeLabel(item.item_type)}
                                </span>
                                <span className="font-medium">{label}</span>
                                <span className="text-zinc-500">
                                  {formatNumber(item.quantity)} ×{" "}
                                  {formatMoney(item.unit_price_minor, item.currency_code)}
                                </span>
                                {item.item_type === "kit" && (
                                  <span className="text-xs text-zinc-400">
                                    {t("orders.spawnedKits", counted({}, item.spawned_kit_ids.length))}
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
          {isLoading ? t("common.loading") : t("orders.empty")}
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

/** The received cell, mirroring the Kits table's Started/Completed pair (#120):
 *  the delivery date, and when a ship date exists too, the days in transit
 *  beside it. Shipped-but-not-received counts transit live instead — the
 *  at-a-glance pipeline timing the status pill's tooltip could only show one
 *  row at a time. Elapsed like the kits column: calendar distance, rounded. */
function receivedCell(order: Order): string {
  if (!order.received_at) {
    if (!order.shipped_at) return "—";
    const days = Math.round((Date.now() - new Date(order.shipped_at).getTime()) / 86_400_000);
    // Both "N d" phrasings now carry the U+00A0 the Kits column always had —
    // the one-byte normalization of this cell's plain space (#164, disclosed).
    return days <= 0
      ? i18n.t("orders.inTransitToday")
      : countedPhrase("orders.inTransitDays", days);
  }
  const date = formatDate(order.received_at);
  if (!order.shipped_at) return date;
  const days = Math.round(
    (new Date(order.received_at).getTime() - new Date(order.shipped_at).getTime()) / 86_400_000,
  );
  return dateWithElapsed(date, days);
}

/** A pending order whose kits are all still pre_ordered is the pre-order (#95).
 *  Derived from the kits already in the payload — nothing is persisted, because
 *  the distinction stops mattering the moment the order ships. Catalog-only
 *  orders carry no signal and read as ordinary pending, by decision. */
function isPreOrder(order: Order): boolean {
  const statuses = order.items.flatMap((item) => item.kits.map((kit) => kit.status));
  return statuses.length > 0 && statuses.every((status) => status === "pre_ordered");
}
