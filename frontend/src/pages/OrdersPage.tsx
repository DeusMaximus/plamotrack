import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Pencil, Plus, Search } from "lucide-react";
import { Fragment, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, metaQuery } from "../api/client";
import type { Order, OrderStage } from "../api/types";
import { ORDER_SORTS, ORDER_STAGES, type OrderSort } from "../api/types";
import { ExportCsvButton } from "../components/ExportCsvButton";
import { OrderFormModal } from "../components/OrderFormModal";
import { StatusBadge } from "../components/StatusBadge";
import {
  Button,
  Chip,
  EmptyState,
  ErrorBanner,
  IconButton,
  Input,
  PageTitle,
  Pager,
  Select,
  TABLE_HEAD_ROW_CLASS,
} from "../components/ui";
import i18n from "../i18n";
import { formatDate, formatMoney, formatNumber } from "../lib/format";
import { invalidateOrderViews } from "../lib/invalidate";
import { counted, countedPhrase, dateWithElapsed, itemTypeLabel } from "../lib/labels";
import { paginate, useEnumParam, usePageParam, useSearchParam, useTextParam } from "../lib/listState";
import { convertedTotal, orderTotal, shippingLine } from "../lib/orderMoney";
import { usePresentationVersion } from "../lib/presentation";

/** The order's stage chip (#95, §13.1, §13.4): the server's `stage` in the kit
 *  pipeline's colours — received is complete's green, shipped is in-transit's
 *  amber, a pre-order is pre-ordered's purple, pending is ordered's blue. The
 *  words are the Orders page's (Pending, Shipped…); Home's columns say the
 *  pipeline's (Ordered, In transit) — the artboards, both. */
function OrderStageChip({ stage }: { stage: OrderStage }) {
  const { t } = useTranslation();
  switch (stage) {
    case "received":
      return <Chip tone="text-status-complete">{t("orders.pillReceived")}</Chip>;
    case "in_transit":
      return <Chip tone="text-status-in-transit">{t("orders.pillShipped")}</Chip>;
    case "pre_ordered":
      // Derived, not stored (#95): a pending order whose kits are all
      // pre_ordered is the pre-order; once it ships nobody cares.
      return (
        <Chip tone="text-status-pre-ordered" title={t("orders.preOrderTooltip")}>
          {t("orders.pillPreOrder")}
        </Chip>
      );
    default:
      return <Chip tone="text-status-ordered">{t("orders.pillPending")}</Chip>;
  }
}

/** The filter's option label for each stage — the chip's word (§13.4). */
const STAGE_FILTER_LABEL = {
  pre_ordered: "orders.pillPreOrder",
  ordered: "orders.pillPending",
  in_transit: "orders.pillShipped",
  received: "orders.pillReceived",
} as const satisfies Record<OrderStage, string>;

/** Rows per page on the list pages (§13.4). */
const PAGE_SIZE = 10;

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
  // The list's state is the URL (§13.4, #232): the sort is the server's — one
  // definition of "recently changed" for the page, Home and the MCP tool — and
  // the status, retailer and search narrow the loaded list here.
  // `status` holds the server's stage vocabulary (§13.2, #233) — the value a
  // Home "view all" link carries and the field every row already has.
  const [stageFilter, setStageFilter] = useEnumParam<OrderStage | "">(
    "status",
    ["", ...ORDER_STAGES],
    "",
  );
  const [retailerFilter, setRetailerFilter] = useTextParam("retailer");
  const [search, setSearch] = useSearchParam("q");
  const [sort, setSort] = useEnumParam<OrderSort>("sort", ORDER_SORTS, "placed");
  const [page, setPage] = usePageParam();

  const {
    data: orders,
    isLoading,
    isError,
    error,
  } = useQuery({ queryKey: ["orders", { sort }], queryFn: () => api.listOrders({ sort }) });
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

  const removeOrder = async (order: Order) => {
    await api.deleteOrder(order.id);
    await invalidateOrderViews(queryClient);
  };

  const visible = useMemo(() => {
    let rows = orders ?? [];
    if (stageFilter) rows = rows.filter((order) => order.stage === stageFilter);
    if (retailerFilter) rows = rows.filter((order) => order.retailer_id === retailerFilter);
    const needle = search.trim().toLowerCase();
    if (needle) {
      rows = rows.filter((order) =>
        [retailerName.get(order.retailer_id), order.order_number, order.tracking_number]
          .filter((value): value is string => Boolean(value))
          .some((value) => value.toLowerCase().includes(needle)),
      );
    }
    return rows;
  }, [orders, stageFilter, retailerFilter, search, retailerName]);
  const paged = paginate(visible, page, PAGE_SIZE);
  const retailerOptions = useMemo(
    () => [...(retailers ?? [])].sort((a, b) => a.name.localeCompare(b.name)),
    [retailers],
  );

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
        <PageTitle count={orders === undefined ? undefined : visible.length}>
          {t("orders.title")}
        </PageTitle>
        <div className="flex gap-2">
          <ExportCsvButton table="orders" />
          <Button icon={Plus} onClick={() => setModal({ mode: "add" })}>
            {t("orders.newOrder")}
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        <div className="relative w-full max-w-sm">
          <Search
            size={15}
            aria-hidden
            className="pointer-events-none absolute start-2.5 top-1/2 -translate-y-1/2 text-faint"
          />
          <Input
            type="search"
            aria-label={t("common.search")}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t("orders.searchPlaceholder")}
            className="ps-8"
          />
        </div>
        <Select
          aria-label={t("orders.filterByStatus")}
          value={stageFilter}
          onChange={(event) => setStageFilter(event.target.value as OrderStage | "")}
          className="!w-auto"
        >
          <option value="">{t("orders.allStatuses")}</option>
          {ORDER_STAGES.map((stage) => (
            <option key={stage} value={stage}>
              {t(STAGE_FILTER_LABEL[stage])}
            </option>
          ))}
        </Select>
        {retailerOptions.length > 0 && (
          <Select
            aria-label={t("orders.filterByRetailer")}
            value={retailerFilter}
            onChange={(event) => setRetailerFilter(event.target.value)}
            className="!w-auto max-w-52"
          >
            <option value="">{t("orders.allRetailers")}</option>
            {retailerOptions.map((retailer) => (
              <option key={retailer.id} value={retailer.id}>
                {retailer.name}
              </option>
            ))}
          </Select>
        )}
        <Select
          aria-label={t("list.sortLabel")}
          value={sort}
          onChange={(event) => setSort(event.target.value as OrderSort)}
          className="!w-auto"
        >
          <option value="placed">{t("orders.sortPlaced")}</option>
          <option value="recent">{t("orders.sortRecent")}</option>
        </Select>
      </div>

      {isError ? (
        <ErrorBanner message={t("orders.loadFailed", { message: (error as Error).message })} />
      ) : paged.total > 0 ? (
        <div className="overflow-x-auto rounded-md border border-border bg-surface">
          <table className="w-full text-sm">
            <thead>
              <tr className={TABLE_HEAD_ROW_CLASS}>
                <th className="w-8 px-3 py-2" />
                <th className="px-3 py-2.5">{t("orders.headerDate")}</th>
                <th className="px-3 py-2.5">{t("orders.headerRetailer")}</th>
                <th className="px-3 py-2.5">{t("orders.headerOrderNumber")}</th>
                <th className="px-3 py-2.5">{t("orders.headerStatus")}</th>
                <th className="px-3 py-2.5">{t("orders.headerShipped")}</th>
                <th className="px-3 py-2.5">{t("orders.headerReceived")}</th>
                <th className="px-3 py-2.5">{t("orders.headerItems")}</th>
                <th className="px-3 py-2.5">{t("orders.headerTotal")}</th>
                <th className="px-3 py-2.5">{t("orders.headerTracking")}</th>
                <th className="px-3 py-2.5" />
              </tr>
            </thead>
            <tbody>
              {paged.rows.map((order) => (
                <Fragment key={order.id}>
                  <tr
                    className="cursor-pointer border-b border-rule last:border-0 hover:bg-chip"
                    onClick={() => toggle(order.id)}
                  >
                    {/* Narrower padding than its neighbours: the 24x24 control
                        is wider than the bare glyph it replaced, and the default
                        px-3 pushed the table enough to wrap retailer names. */}
                    <td className="px-1 py-2 text-faint">
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
                        className="flex h-6 w-6 items-center justify-center rounded-sm leading-none hover:bg-chip hover:text-text focus:outline-none focus:ring-2 focus:ring-accent"
                        onClick={(event) => {
                          event.stopPropagation();
                          toggle(order.id);
                        }}
                      >
                        {expanded.has(order.id) ? (
                          <ChevronDown size={14} aria-hidden />
                        ) : (
                          <ChevronRight size={14} aria-hidden className="rtl:-scale-x-100" />
                        )}
                      </button>
                    </td>
                    <td className="px-3 py-2">{formatDate(order.order_date)}</td>
                    <td className="px-3 py-2 font-medium">
                      {retailerName.get(order.retailer_id) ?? "…"}
                    </td>
                    <td className="px-3 py-2 text-muted">{order.order_number ?? "—"}</td>
                    {/* No date tooltips on the pills any more — the Shipped and
                        Received columns beside them carry the dates for every
                        row at once, which is what the tooltip couldn't (#120). */}
                    <td className="px-3 py-2">
                      <OrderStageChip stage={order.stage} />
                    </td>
                    {/* nowrap: "in transit · 6 d" split across lines reads as two
                        facts, and the dates never benefit from wrapping. */}
                    <td
                      className="whitespace-nowrap px-3 py-2 text-muted"
                      title={t("orders.shippedTooltip")}
                    >
                      {order.shipped_at ? formatDate(order.shipped_at) : "—"}
                    </td>
                    <td
                      className="whitespace-nowrap px-3 py-2 text-muted"
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
                    <td className="px-3 py-2 tabular-nums">
                      <div>{orderTotal(order)}</div>
                      {convertedTotal(order) && (
                        <div className="text-xs text-muted">{convertedTotal(order)}</div>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      {order.tracking_url ? (
                        <a
                          href={order.tracking_url}
                          target="_blank"
                          rel="noreferrer"
                          onClick={(event) => event.stopPropagation()}
                          className="text-accent hover:underline"
                        >
                          {order.tracking_number ?? t("orders.trackingLinkFallback")}
                        </a>
                      ) : (
                        (order.tracking_number ?? "—")
                      )}
                    </td>
                    <td className="px-2 py-2 text-end" onClick={(event) => event.stopPropagation()}>
                      {/* One control per row (§13.4). Ship, Receive and Delete all
                          live in the Edit dialog (#120), next to the fields that
                          correct them and the details a real status change
                          travels with. */}
                      <IconButton
                        label={t("common.editNamed", {
                          name: `${retailerName.get(order.retailer_id) ?? t("orders.thisOrder")} ${formatDate(order.order_date)}`,
                        })}
                        onClick={() => setModal({ mode: "edit", order })}
                      >
                        <Pencil size={15} aria-hidden />
                      </IconButton>
                    </td>
                  </tr>
                  {expanded.has(order.id) && (
                    <tr className="border-b border-rule last:border-0">
                      <td />
                      <td colSpan={10} className="px-3 pb-3.5 pt-0">
                        <LinesBox order={order} itemName={itemName} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
          <Pager paged={paged} onPage={setPage} />
        </div>
      ) : (
        <EmptyState>
          {isLoading
            ? t("common.loading")
            : orders?.length
              ? t("orders.emptyFiltered")
              : t("orders.empty")}
        </EmptyState>
      )}

      {modal && (
        <OrderFormModal
          order={modal.mode === "edit" ? modal.order : undefined}
          onClose={() => setModal(null)}
          onDelete={removeOrder}
        />
      )}
    </div>
  );
}

/** The expanded lines box (§13.4): a kit line carries its kit's status, a catalog
 *  line says when its stock lands (§3.9), and shipping closes the box. One grid
 *  for every line, so the type, status and amount columns are shared tracks — a
 *  line's status chip cannot push its own type column over (Codex #236 P3-6). */
function LinesBox({ order, itemName }: { order: Order; itemName: Map<string, string> }) {
  const { t } = useTranslation();
  const shipping = shippingLine(order);
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_6rem_max-content_8rem] overflow-hidden rounded-sm border border-rule bg-surface-alt text-[13px]">
      {order.items.map((item, index) => {
        const label =
          item.item_type === "kit"
            ? (itemName.get(item.spawned_kit_ids[0] ?? "") ?? itemTypeLabel("kit"))
            : (itemName.get(item.catalog_ref_id ?? "") ?? itemTypeLabel(item.item_type));
        const firstKit = item.kits[0];
        const cell = `flex items-center py-2 ${index === 0 ? "" : "border-t border-rule"}`;
        return (
          <Fragment key={item.id}>
            <span className={`${cell} min-w-0 ps-3 font-medium`}>
              <span className="truncate">{label}</span>
            </span>
            <span className={`${cell} ps-3.5 text-xs text-muted`}>{itemTypeLabel(item.item_type)}</span>
            <span className={`${cell} gap-2 ps-3.5 text-xs text-muted`}>
              {item.item_type === "kit" ? (
                <>
                  {firstKit && <StatusBadge status={firstKit.status} />}
                  {item.spawned_kit_ids.length > 1 &&
                    t("orders.spawnedKits", counted({}, item.spawned_kit_ids.length))}
                </>
              ) : (
                !order.received_at && t("orders.stockOnReceipt")
              )}
            </span>
            <span className={`${cell} justify-end pe-3 ps-3.5 text-muted tabular-nums`}>
              {formatNumber(item.quantity)} × {formatMoney(item.unit_price_minor, item.currency_code)}
            </span>
          </Fragment>
        );
      })}
      {shipping && (
        <div className="col-span-4 flex items-center justify-between gap-3.5 border-t border-rule bg-surface px-3 py-2 text-xs text-muted">
          <span>
            {shipping.service
              ? t("orders.shippingLineWith", { service: shipping.service })
              : t("orders.shippingLine")}
          </span>
          <span className="tabular-nums">{shipping.amount ?? "—"}</span>
        </div>
      )}
    </div>
  );
}

/** The received cell, mirroring the Kits table's Started/Completed pair (#120):
 *  the delivery date, and when a ship date exists too, the days in transit
 *  beside it. Shipped-but-not-received counts transit live instead — the
 *  at-a-glance pipeline timing the status pill's tooltip could only show one
 *  row at a time. Elapsed like the kits column: calendar distance, rounded-sm. */
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
