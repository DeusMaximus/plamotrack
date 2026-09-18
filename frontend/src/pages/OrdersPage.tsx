import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Pencil, Plus, Search } from "lucide-react";
import {
  Fragment,
  createContext,
  useContext,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";

import { api, metaQuery, summaryQuery } from "../api/client";
import type { Order, OrderItem, OrderStage, Retailer } from "../api/types";
import { ORDER_SORTS, ORDER_STAGES, type OrderSort } from "../api/types";
import { ExportCsvButton } from "../components/ExportCsvButton";
import {
  FILTERS_FOCUS,
  FilterSheet,
  FilterSheetButton,
  Segmented,
  SheetSection,
  ToggleGrid,
  ToggleOption,
} from "../components/FilterSheet";
import { OrderFormModal } from "../components/OrderFormModal";
import { StatusBadge } from "../components/StatusBadge";
import {
  Button,
  Chip,
  EmptyState,
  ErrorBanner,
  GradeChip,
  IconButton,
  Input,
  PAGE_ACTION_FOCUS,
  PageHeader,
  Pager,
  Select,
  TABLE_HEAD_ROW_CLASS,
} from "../components/ui";
import i18n from "../i18n";
import { dateInDigits, formatDate, formatMoney, formatNumber } from "../lib/format";
import { invalidateOrderViews } from "../lib/invalidate";
import { counted, countedPhrase, dateWithElapsed, itemTypeLabel } from "../lib/labels";
import { filterOrders } from "../lib/listFilters";
import {
  paginate,
  useEnumParam,
  usePageParam,
  useSearchParam,
  useTextParam,
  useWriteParams,
} from "../lib/listState";
import { convertedTotal, orderTotal, shippingLine } from "../lib/orderMoney";
import { usePresentationVersion } from "../lib/presentation";
import { useShell } from "../lib/shell";

/** The order's stage chip (#95, §13.1, §13.4): the server's `stage` in the kit
 *  pipeline's colours — received is complete's green, shipped is in-transit's
 *  amber, a pre-order is pre-ordered's purple, pending is ordered's blue. The
 *  words are the Orders page's (Pending, Shipped…); Home's columns say the
 *  pipeline's (Ordered, In transit) — the artboards, both. */
function OrderStageChip({ stage }: { stage: OrderStage }) {
  const { t } = useTranslation();
  return (
    <Chip
      tone={STAGE_TONES[stage]}
      // Derived, not stored (#95): a pending order whose kits are all
      // pre_ordered is the pre-order; once it ships nobody cares.
      title={stage === "pre_ordered" ? t("orders.preOrderTooltip") : undefined}
    >
      {t(STAGE_FILTER_LABEL[stage])}
    </Chip>
  );
}

const STAGE_TONES: Record<OrderStage, string> = {
  pre_ordered: "text-status-pre-ordered",
  ordered: "text-status-ordered",
  in_transit: "text-status-in-transit",
  received: "text-status-complete",
};

/** The filter's option label for each stage — the chip's word (§13.4). */
const STAGE_FILTER_LABEL = {
  pre_ordered: "orders.pillPreOrder",
  ordered: "orders.pillPending",
  in_transit: "orders.pillShipped",
  received: "orders.pillReceived",
} as const satisfies Record<OrderStage, string>;

/** The sorts in the order the page offers them, the default first; keyed by
 *  the type, so a new sort stops compiling until it has a label. */
const SORT_LABEL = {
  placed: "orders.sortPlaced",
  recent: "orders.sortRecent",
} as const satisfies Record<OrderSort, string>;
const SORT_ORDER = Object.keys(SORT_LABEL) as OrderSort[];

type OrderListState = { stage: OrderStage | ""; retailer: string; sort: OrderSort };
const NO_FILTERS: OrderListState = { stage: "", retailer: "", sort: "placed" };

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
  const writeParams = useWriteParams();
  // Cards and the filter sheet are the phone's (§13.7); the sheet's state is
  // not the shell's, so a sheet open across a rotation stays a dialog.
  const phone = useShell() === "phone";
  const [sheetOpen, setSheetOpen] = useState(false);

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

  const visible = useMemo(
    () =>
      filterOrders(
        orders ?? [],
        { stage: stageFilter, retailer: retailerFilter, search },
        retailerName,
      ),
    [orders, stageFilter, retailerFilter, search, retailerName],
  );
  const paged = paginate(visible, page, PAGE_SIZE);
  const retailerOptions = useMemo(
    () => [...(retailers ?? [])].sort((a, b) => a.name.localeCompare(b.name)),
    [retailers],
  );

  // The same two names in every shell (§13.7) — the table's and the card's
  // controls are found by them. The toggle names the retailer as well as the
  // date: two orders placed on one day would otherwise share an accessible
  // name, and the date alone just restates the cell beside it. The
  // receive/delete confirmations already say the retailer for the same reason.
  const toggleLabel = (order: Order) =>
    t(expanded.has(order.id) ? "orders.hideLineItems" : "orders.showLineItems", {
      date: formatDate(order.order_date),
      retailer: retailerName.get(order.retailer_id) ?? t("orders.unknownRetailer"),
    });
  const editLabel = (order: Order) =>
    t("common.editNamed", {
      name: `${retailerName.get(order.retailer_id) ?? t("orders.thisOrder")} ${formatDate(order.order_date)}`,
    });

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
      <PageHeader
        title={t("orders.title")}
        count={orders === undefined ? undefined : visible.length}
        secondary={<ExportCsvButton table="orders" />}
        actions={
          <Button icon={Plus} onClick={() => setModal({ mode: "add" })} data-focus-key={PAGE_ACTION_FOCUS}>
            {t("orders.newOrder")}
          </Button>
        }
      />

      {/* One search box in every shell — the same node, so a rotation keeps its
          text and its focus. Beside it, a phone has the one *Filter and sort*
          control (§13.7); wider, the filters themselves. */}
      <div className="flex flex-wrap gap-2 max-md:flex-nowrap">
        <div className="relative w-full max-w-sm max-md:w-auto max-md:max-w-none max-md:flex-1">
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
        {phone ? (
          <FilterSheetButton
            active={Number(stageFilter !== "") + Number(retailerFilter !== "")}
            onClick={() => setSheetOpen(true)}
          />
        ) : (
          <>
            <Select
              aria-label={t("orders.filterByStatus")}
              value={stageFilter}
              onChange={(event) => setStageFilter(event.target.value as OrderStage | "")}
              className="!w-auto"
              data-focus-key={FILTERS_FOCUS}
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
                data-focus-stand-in={FILTERS_FOCUS}
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
              data-focus-stand-in={FILTERS_FOCUS}
            >
              {SORT_ORDER.map((value) => (
                <option key={value} value={value}>
                  {t(SORT_LABEL[value])}
                </option>
              ))}
            </Select>
          </>
        )}
      </div>

      {isError ? (
        <ErrorBanner message={t("orders.loadFailed", { message: (error as Error).message })} />
      ) : paged.total > 0 && phone ? (
        <>
          <ul className="space-y-2">
            {paged.rows.map((order) => (
              <OrderCard
                key={order.id}
                order={order}
                retailer={retailerName.get(order.retailer_id) ?? "…"}
                itemName={itemName}
                expanded={expanded.has(order.id)}
                toggleLabel={toggleLabel(order)}
                onToggle={() => toggle(order.id)}
                editLabel={editLabel(order)}
                onEdit={() => setModal({ mode: "edit", order })}
              />
            ))}
          </ul>
          <Pager paged={paged} onPage={setPage} className="" />
        </>
      ) : paged.total > 0 ? (
        // `@container`: the table folds to the width this box has, not the
        // device's (§13.7), in two steps. Below 66rem (1056 px) the order number
        // rides under the retailer's name; below 60rem (960 px) Shipped and
        // Received go under the status chip and Tracking into the expanded
        // lines. A fold moves what a column said, it never drops it.
        //
        // The lines are what the table needs with ordinary rows in it, and a
        // little: not the demo's 953 px, because an order that was shipped *and*
        // received says "27/08/2026 · 9 d" where the demo says a date. With that
        // and a seventeen-character order number the three shapes need 1040, 935
        // and 625 px — lists.spec.ts seeds those rows and gives the box every
        // width. A line is a guess about rows nobody has typed yet, so what it
        // cannot know gives way by its value — a date written in words wraps
        // (`dateWrap`), a long reference breaks (`Reference`) — and past that the
        // box still scrolls.
        //
        // By the box at every width, the desktop included (the owner's call,
        // 2026-09-18): beside the sidebar the box is the viewport less 306 px, so
        // from 1280 to 1361 px the order number is under the retailer — where
        // `main` had the table 60 px wider than its box and the edit control off
        // its edge — and from 1362 px (a 1366 px laptop, a 13-inch iPad) the
        // table is whole. Beside the rail an 11-inch iPad Pro in landscape has it
        // whole, a 1180 px one and a mini the first fold, 1024–1080 px and every
        // portrait the second.
        <div className="@container overflow-x-auto rounded-md border border-border bg-surface">
          <ReferenceRuler>
          <table className="w-full text-sm">
            <thead>
              <tr className={TABLE_HEAD_ROW_CLASS}>
                <th className="w-8 px-3 py-2" />
                <th className="px-3 py-2.5">{t("orders.headerDate")}</th>
                <th className="px-3 py-2.5">{t("orders.headerRetailer")}</th>
                <th className="px-3 py-2.5 @max-[66rem]:hidden">
                  {t("orders.headerOrderNumber")}
                </th>
                <th className="px-3 py-2.5">{t("orders.headerStatus")}</th>
                <th className="px-3 py-2.5 @max-[60rem]:hidden">
                  {t("orders.headerShipped")}
                </th>
                <th className="px-3 py-2.5 @max-[60rem]:hidden">
                  {t("orders.headerReceived")}
                </th>
                <th className="px-3 py-2.5">{t("orders.headerItems")}</th>
                <th className="px-3 py-2.5">{t("orders.headerTotal")}</th>
                <th className="px-3 py-2.5 @max-[60rem]:hidden">
                  {t("orders.headerTracking")}
                </th>
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
                        aria-label={toggleLabel(order)}
                        data-focus-key={`order-lines:${order.id}`}
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
                      {order.order_number && (
                        <div className="hidden text-xs font-normal text-muted @max-[66rem]:block">
                          <Reference text={order.order_number} kind="orderNumber" />
                        </div>
                      )}
                    </td>
                    <td className="px-3 py-2 text-muted @max-[66rem]:hidden">
                      {order.order_number ? (
                        <Reference text={order.order_number} kind="orderNumber" />
                      ) : (
                        "—"
                      )}
                    </td>
                    {/* No date tooltips on the pills any more — the Shipped and
                        Received columns beside them carry the dates for every
                        row at once, which is what the tooltip couldn't (#120). */}
                    <td className="px-3 py-2">
                      <OrderStageChip stage={order.stage} />
                      <StageDates order={order} className="mt-1 hidden @max-[60rem]:block" />
                    </td>
                    {/* nowrap: "in transit · 6 d" split across lines reads as two
                        facts, and a date in digits never benefits from wrapping —
                        one in words does (`dateWrap`). */}
                    <td
                      className={`${dateWrap(order.shipped_at)} px-3 py-2 text-muted @max-[60rem]:hidden`}
                      title={t("orders.shippedTooltip")}
                    >
                      {order.shipped_at ? formatDate(order.shipped_at) : "—"}
                    </td>
                    <td
                      className={`${dateWrap(order.received_at)} px-3 py-2 text-muted @max-[60rem]:hidden`}
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
                    <td className="px-3 py-2 @max-[60rem]:hidden">
                      <Tracking order={order} />
                    </td>
                    {/* `touch:px-0`: the 44 px target carries its own margin around
                        the icon, so a touch table needs no more width than a
                        mouse's — one pair of fold lines serves both. */}
                    <td
                      className="px-2 py-2 text-end touch:px-0"
                      onClick={(event) => event.stopPropagation()}
                    >
                      {/* One control per row (§13.4). Ship, Receive and Delete all
                          live in the Edit dialog (#120), next to the fields that
                          correct them and the details a real status change
                          travels with. */}
                      <IconButton
                        label={editLabel(order)}
                        onClick={() => setModal({ mode: "edit", order })}
                        data-focus-key={`order:${order.id}`}
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
          </ReferenceRuler>
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
      {sheetOpen && (
        <OrderFilterSheet
          orders={orders ?? []}
          search={search}
          retailerName={retailerName}
          retailerOptions={retailerOptions}
          current={{ stage: stageFilter, retailer: retailerFilter, sort }}
          onApply={(next) => {
            // One navigation for all of it, the page reset with it (§13.4) — and
            // each parameter dropped at its default, so the URL the sheet leaves
            // is the one the desktop's selects and a Home link would.
            writeParams({
              status: next.stage || null,
              retailer: next.retailer || null,
              sort: next.sort === NO_FILTERS.sort ? null : next.sort,
              page: null,
            });
            setSheetOpen(false);
          }}
          onClose={() => setSheetOpen(false)}
        />
      )}
    </div>
  );
}

/** The Orders filter sheet (§13.7): the stage as toggles with the collection's
 *  count of each (`GET /summary`), the retailer as a native select, the sort
 *  segmented. It holds a draft; the button counts what the draft would show,
 *  through the same `filterOrders` the page reads, the page's search applied. */
function OrderFilterSheet({
  orders,
  search,
  retailerName,
  retailerOptions,
  current,
  onApply,
  onClose,
}: {
  orders: Order[];
  search: string;
  retailerName: ReadonlyMap<string, string>;
  retailerOptions: Retailer[];
  current: OrderListState;
  onApply: (next: OrderListState) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState(current);
  const { data: summary } = useQuery(summaryQuery);
  const total = summary && ORDER_STAGES.reduce((sum, stage) => sum + summary.orders[stage], 0);
  const matching = filterOrders(
    orders,
    { stage: draft.stage, retailer: draft.retailer, search },
    retailerName,
  ).length;

  return (
    <FilterSheet
      applyLabel={countedPhrase("orders.showCount", matching)}
      onApply={() => onApply(draft)}
      onClear={() => setDraft(NO_FILTERS)}
      onClose={onClose}
    >
      <SheetSection label={t("orders.headerStatus")}>
        <ToggleGrid>
          <ToggleOption
            pressed={draft.stage === ""}
            count={total}
            onClick={() => setDraft({ ...draft, stage: "" })}
          >
            {t("orders.allStatuses")}
          </ToggleOption>
          {ORDER_STAGES.map((stage) => (
            <ToggleOption
              key={stage}
              pressed={draft.stage === stage}
              tone={STAGE_TONES[stage]}
              count={summary?.orders[stage]}
              onClick={() => setDraft({ ...draft, stage })}
            >
              {t(STAGE_FILTER_LABEL[stage])}
            </ToggleOption>
          ))}
        </ToggleGrid>
      </SheetSection>
      {retailerOptions.length > 0 && (
        <SheetSection label={t("orders.headerRetailer")}>
          <Select
            aria-label={t("orders.filterByRetailer")}
            value={draft.retailer}
            onChange={(event) => setDraft({ ...draft, retailer: event.target.value })}
          >
            <option value="">{t("orders.allRetailers")}</option>
            {retailerOptions.map((retailer) => (
              <option key={retailer.id} value={retailer.id}>
                {retailer.name}
              </option>
            ))}
          </Select>
        </SheetSection>
      )}
      <SheetSection label={t("list.sortLabel")}>
        <Segmented
          options={SORT_ORDER.map((value) => ({ value, label: t(SORT_LABEL[value]) }))}
          value={draft.sort}
          onChange={(next) => setDraft({ ...draft, sort: next })}
        />
      </SheetSection>
    </FilterSheet>
  );
}

/** What the Shipped and Received columns say, for where they are not columns:
 *  under the status chip of a folded table row, beside it on a phone's card.
 *  In transit it is the ship date and the days so far; received, the delivery
 *  date with the days it took, and the ship date under it — both columns moved,
 *  neither dropped. Nothing for an order that has not shipped: the columns say
 *  "—" there, and the chip already says why. */
function StageDates({ order, className = "" }: { order: Order; className?: string }) {
  const { t } = useTranslation();
  if (!order.shipped_at && !order.received_at) return null;
  return (
    <div className={`text-xs text-muted ${className}`}>
      {order.received_at ? (
        <>
          <div className={dateWrap(order.received_at)} title={t("orders.receivedTooltip")}>
            {receivedCell(order)}
          </div>
          {order.shipped_at && (
            <div className={dateWrap(order.shipped_at)} title={t("orders.shippedTooltip")}>
              {t("orders.shippedDate", { date: formatDate(order.shipped_at) })}
            </div>
          )}
        </>
      ) : (
        <div className={dateWrap(order.shipped_at)} title={t("orders.shippedTooltip")}>
          {formatDate(order.shipped_at as string)}
          {t("common.dotSeparator")}
          {receivedCell(order)}
        </div>
      )}
    </div>
  );
}

/** The tracking number, a link when the order has a URL for it. The link is in
 *  a column, in the expanded lines once the column folds away, and in a card's
 *  lines — so it carries the order's key, and where the lines are closed the
 *  control that opens them stands in for it (`lib/focusKey.ts`). */
function Tracking({ order }: { order: Order }) {
  const { t } = useTranslation();
  const number = order.tracking_number ? (
    <Reference text={order.tracking_number} kind="tracking" />
  ) : null;
  if (!order.tracking_url) return number ?? <>—</>;
  return (
    <a
      href={order.tracking_url}
      target="_blank"
      rel="noreferrer"
      onClick={(event) => event.stopPropagation()}
      data-focus-key={`order-tracking:${order.id}`}
      data-focus-stand-in={`order-lines:${order.id}`}
      className="text-accent hover:underline"
    >
      {number ?? t("orders.trackingLinkFallback")}
    </a>
  );
}

/** What the fold lines were measured with (§13.7), in the width the browser
 *  draws it: a tracking number of thirteen characters with nowhere to break
 *  (Japan Post's, 115 px at the table's 14 px — 8.2em), and an order number
 *  that breaks at its hyphens into pieces no wider than "12345678-" (82 px,
 *  5.9em). A reference wider than that — a USPS number is twenty-two digits, a
 *  marketplace's order number nineteen with no hyphen, and thirteen letters are
 *  wider than thirteen digits (Codex #266, findings 2 and 5) — is one
 *  unbreakable word, and held whole it pushed the row's edit control out of the
 *  box at widths where nothing folds. So a reference wider than the budget may
 *  break anywhere, down to lines as wide as the budget and no narrower; one
 *  within it is left exactly as it was, a plain word, and the table's ordinary
 *  rows lay out as they always did.
 *
 *  **Measured, not counted** (finding 5: a count of characters stood in for
 *  this once): the width of the widest piece the browser will not break, from
 *  a copy the browser lays out at `min-content` in `ReferenceRuler` — one box
 *  per table, out of flow, no size, clipped, at the table's font and figures,
 *  with each reference's text as a pseudo-element's content rather than text
 *  of its own. Every one of those is a lesson. A copy laid out inside the cell
 *  was scrollable overflow; inside a fold's `display: none` half it had no
 *  width to measure; as DOM text it was the deepest match for `getByText`,
 *  which prefers it to the visible text; and a canvas's `measureText` cannot be
 *  told the table's `tabular-nums`, so its digits are narrower than the cell's.
 *  In em, so one measurement serves the column's copy and the fold's smaller
 *  one alike, and the root font size can be anything (finding 6).
 *
 *  By the value and not for every row, and for two reasons now: `overflow-wrap:
 *  anywhere` lowers a column's minimum width and a table squeezes every column
 *  that has give; and in Chromium it also changes the text's shaping — kerning
 *  stops at a break opportunity, and there is one after every character — so
 *  "EJ482113905JP" is 105 px as a plain word and 110 px under `anywhere`, and
 *  wrapped at the cell's edge with nothing squeezed at all. */
const REFERENCE_BUDGET = {
  orderNumber: { em: 6, wrap: "inline-block min-w-[6em] wrap-anywhere" }, // "12345678-" is 5.9em
  tracking: { em: 8.3, wrap: "inline-block min-w-[8.3em] wrap-anywhere" }, // Japan Post's 13 are 8.2em
} as const;

const RulerContext = createContext<HTMLElement | null>(null);

/** Where a table's references are measured: rendered once inside the table's
 *  box, at the table's font and figures. `Reference` puts its sizer here
 *  through a portal. A `Reference` with no ruler above it — a card's lines —
 *  measures nothing and stays a plain word, which there is inside a
 *  `wrap-anywhere` flex item. */
function ReferenceRuler({ children }: { children: ReactNode }) {
  const [ruler, setRuler] = useState<HTMLElement | null>(null);
  return (
    <RulerContext.Provider value={ruler}>
      {children}
      <div ref={setRuler} aria-hidden className="absolute h-0 w-0 overflow-hidden text-sm tabular-nums" />
    </RulerContext.Provider>
  );
}

function Reference({ text, kind }: { text: string; kind: keyof typeof REFERENCE_BUDGET }) {
  const ruler = useContext(RulerContext);
  const sizer = useRef<HTMLSpanElement>(null);
  const [wide, setWide] = useState(false);
  useLayoutEffect(() => {
    const element = sizer.current;
    if (!element) return;
    const measure = () => {
      const em = parseFloat(getComputedStyle(element).fontSize);
      setWide(element.getBoundingClientRect().width / em > REFERENCE_BUDGET[kind].em);
    };
    measure();
    // And when its size changes — the web font arriving after the first paint.
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [text, kind, ruler]);
  return (
    <>
      <span className={wide ? REFERENCE_BUDGET[kind].wrap : undefined}>{text}</span>
      {ruler &&
        createPortal(
          <span
            ref={sizer}
            data-text={text}
            className="invisible block w-min whitespace-normal before:content-[attr(data-text)]"
          />,
          ruler,
        )}
    </>
  );
}

/** A date the locale writes in digits stays on one line, with what follows it
 *  ("27/08/2026 · 9 d" — #120); one it writes in words may wrap (`dateInDigits`
 *  says why). "Thursday, 27 August 2026 · 9 d" held to a line left this table
 *  121 px wider than its box at 1280 px. No date — "—", "in transit · 6 d" — is
 *  the short case. */
function dateWrap(iso: string | null | undefined): string {
  return iso && !dateInDigits(iso) ? "" : "whitespace-nowrap";
}

const hasTracking = (order: Order) => Boolean(order.tracking_number || order.tracking_url);

/** A line's name: the spawned kit's or the catalog item's, else what it is. */
function lineLabel(item: OrderItem, itemName: Map<string, string>): string {
  return item.item_type === "kit"
    ? (itemName.get(item.spawned_kit_ids[0] ?? "") ?? itemTypeLabel("kit"))
    : (itemName.get(item.catalog_ref_id ?? "") ?? itemTypeLabel(item.item_type));
}

/** An order on a phone (§13.7): the retailer and the total; the stage chip with
 *  its shipped or received detail; the date, the number and the item count.
 *  Tapping the card opens its lines as clicking the table's row does — and as
 *  there, the keyboard's and a screen reader's way in is a real button under
 *  the table's own name, because nothing focuses a `<div>`. Edit is its own
 *  control, under the table's name for it. */
function OrderCard({
  order,
  retailer,
  itemName,
  expanded,
  toggleLabel,
  onToggle,
  editLabel,
  onEdit,
}: {
  order: Order;
  retailer: string;
  itemName: Map<string, string>;
  expanded: boolean;
  toggleLabel: string;
  onToggle: () => void;
  editLabel: string;
  onEdit: () => void;
}) {
  const { t } = useTranslation();
  const converted = convertedTotal(order);
  const quantity = order.items.reduce((total, item) => total + item.quantity, 0);
  return (
    <li className="rounded-md border border-border bg-surface">
      <div className="flex cursor-pointer items-center" onClick={onToggle}>
        <button
          type="button"
          aria-expanded={expanded}
          aria-label={toggleLabel}
          data-focus-key={`order-lines:${order.id}`}
          className="inline-flex h-11 w-9 shrink-0 items-center justify-center rounded-sm text-faint focus:outline-none focus:ring-1 focus:ring-accent"
          onClick={(event) => {
            event.stopPropagation();
            onToggle();
          }}
        >
          {expanded ? (
            <ChevronDown size={16} aria-hidden />
          ) : (
            <ChevronRight size={16} aria-hidden className="rtl:-scale-x-100" />
          )}
        </button>
        <div className="flex min-w-0 flex-1 flex-col gap-1.5 py-2.5">
          {/* The retailer is who the order is, and the total is as long as the
              order has currencies — "JPY 2,800 + USD 45.00 + EUR 34.00" beside
              a name that could shrink left it 0 px (Codex #266, finding 1). So
              the name keeps 8rem whatever stands beside it, and a total that
              leaves it less goes to a line of its own, where it may wrap too.
              8rem or the whole line, whichever is less: the rem grows with the
              browser's font-size preference and the card does not, and at 32 px
              an unconditional 8rem was 256 px in a 94 px column, the name's
              start pushed off the left of the screen (finding 6). The lines
              under it wrap the same way rather than ending in an ellipsis: a
              card is the only place a phone says these, and a date written in
              words is as long as the instance's settings make it. */}
          <div className="flex flex-wrap items-baseline justify-end gap-x-2.5 gap-y-0.5 text-[15px] font-semibold">
            <span className="min-w-[min(8rem,100%)] flex-1 truncate">{retailer}</span>
            <span className="text-end tabular-nums">{orderTotal(order)}</span>
          </div>
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px] text-muted">
            <OrderStageChip stage={order.stage} />
            {(order.received_at || order.shipped_at) && (
              <span>
                {order.received_at
                  ? receivedCell(order)
                  : `${formatDate(order.shipped_at as string)}${t("common.dotSeparator")}${receivedCell(order)}`}
              </span>
            )}
            {converted && <span className="ms-auto tabular-nums">{converted}</span>}
          </div>
          <div className="text-[12.5px] text-muted wrap-anywhere">
            {[
              formatDate(order.order_date),
              order.order_number,
              t("orders.itemCount", counted({}, quantity)),
            ]
              .filter(Boolean)
              .join(t("common.dotSeparator"))}
          </div>
        </div>
        <span onClick={(event) => event.stopPropagation()}>
          <IconButton label={editLabel} onClick={onEdit} data-focus-key={`order:${order.id}`}>
            <Pencil size={16} aria-hidden />
          </IconButton>
        </span>
      </div>
      {expanded && <CardLines order={order} itemName={itemName} />}
    </li>
  );
}

/** The card's lines (§13.7): what `LinesBox` says, two rows a line instead of
 *  four columns — the name and the amount, then what it is and where it stands.
 *  Shipping closes the lines, and tracking closes the box: a card has no
 *  tracking column for it to be in. */
function CardLines({ order, itemName }: { order: Order; itemName: Map<string, string> }) {
  const { t } = useTranslation();
  const shipping = shippingLine(order);
  const foot = "flex items-baseline justify-between gap-2.5 border-t border-rule px-3 py-2.5 text-[12.5px] text-muted";
  return (
    <div className="mx-3 mb-3 overflow-hidden rounded-sm border border-rule bg-surface-alt">
      {order.items.map((item, index) => {
        const firstKit = item.kits[0];
        return (
          <div key={item.id} className={`space-y-1 px-3 py-2.5 ${index === 0 ? "" : "border-t border-rule"}`}>
            <div className="flex items-baseline justify-between gap-2.5 text-sm">
              <span className="min-w-0 truncate font-medium">{lineLabel(item, itemName)}</span>
              <span className="shrink-0 tabular-nums text-muted">
                {formatNumber(item.quantity)} × {formatMoney(item.unit_price_minor, item.currency_code)}
              </span>
            </div>
            <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px] text-muted">
              <span>{itemTypeLabel(item.item_type)}</span>
              {item.item_type === "kit" ? (
                <>
                  {firstKit && <GradeChip grade={firstKit.grade} />}
                  {firstKit && <StatusBadge status={firstKit.status} />}
                  {item.spawned_kit_ids.length > 1 &&
                    t("orders.spawnedKits", counted({}, item.spawned_kit_ids.length))}
                </>
              ) : (
                !order.received_at && t("orders.stockOnReceipt")
              )}
            </div>
          </div>
        );
      })}
      {shipping && (
        <div className={`${foot} bg-surface`}>
          <span>
            {shipping.service
              ? t("orders.shippingLineWith", { service: shipping.service })
              : t("orders.shippingLine")}
          </span>
          <span className="tabular-nums">{shipping.amount ?? "—"}</span>
        </div>
      )}
      {hasTracking(order) && (
        <div className={`${foot} bg-surface`}>
          <span>{t("orders.headerTracking")}</span>
          <span className="min-w-0 text-end text-text wrap-anywhere">
            <Tracking order={order} />
          </span>
        </div>
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
        const label = lineLabel(item, itemName);
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
      {/* Where the Tracking column goes when the table folds it away (§13.7). */}
      {hasTracking(order) && (
        <div className="col-span-4 hidden items-center justify-between gap-3.5 border-t border-rule bg-surface px-3 py-2 text-xs text-muted @max-[60rem]:flex">
          <span>{t("orders.headerTracking")}</span>
          <span className="min-w-0 text-end text-text wrap-anywhere">
            <Tracking order={order} />
          </span>
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
