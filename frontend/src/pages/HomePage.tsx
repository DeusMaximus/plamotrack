import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Pencil } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { api, metaQuery, summaryQuery } from "../api/client";
import type { Kit, Order } from "../api/types";
import { KitFormModal } from "../components/KitFormModal";
import { OrderFormModal } from "../components/OrderFormModal";
import { StatusBadge } from "../components/StatusBadge";
import { EmptyState, ErrorBanner, IconButton, MICRO_LABEL_CLASS, PageTitle, RatingStars } from "../components/ui";
import { formatDate, formatNumber } from "../lib/format";
import {
  MAIL_CAP,
  MAIL_STAGES,
  STRIP_LIMIT,
  buildDay,
  bucketMail,
  completedOn,
  mailCardLines,
  needsCatalogNames,
  type LineSummary,
  type MailStage,
} from "../lib/home";
import { invalidateKitViews, invalidateOrderViews } from "../lib/invalidate";
import { countedPhrase, itemTypeLabel, ratingTooltip } from "../lib/labels";
import { usePresentationVersion } from "../lib/presentation";

/** The start page (design §13.2, #233): status at a glance, the bench first.
 *  Every count in a heading is the server's (`GET /summary`) — the total the
 *  list page behind the *view all* link shows — and every strip is a
 *  `sort=recent` list with a `limit`, so "recent" means one thing for this
 *  page, the list pages and an agent. Every card carries one visible edit
 *  control opening the same dialog the list pages use; there is no drag. */

/** Per-column copy, keyed by the wire stage (the catalogue keeps flat leaves). */
const MAIL_COPY = {
  pre_ordered: { empty: "home.mailEmptyPreOrdered", viewAll: "home.viewAllPreOrdered" },
  ordered: { empty: "home.mailEmptyOrdered", viewAll: "home.viewAllOrdered" },
  in_transit: { empty: "home.mailEmptyInTransit", viewAll: "home.viewAllInTransit" },
} as const satisfies Record<MailStage, { empty: string; viewAll: string }>;

type Dialog = { kind: "kit"; kit: Kit } | { kind: "order"; order: Order } | null;

export function HomePage() {
  // Counts, dates and day numbers render through the instance's formatting
  // locale, so this subtree re-renders when the settings row arrives (#177
  // review, P3-1 — the Outlet element identity keeps a Layout render out).
  usePresentationVersion();
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [dialog, setDialog] = useState<Dialog>(null);

  const summary = useQuery(summaryQuery);
  const bench = useQuery({
    queryKey: ["kits", { status: "building", sort: "recent" }],
    queryFn: () => api.listKits({ status: "building", sort: "recent" }),
  });
  const backlog = useQuery({
    queryKey: ["kits", { status: "backlog", sort: "recent", limit: STRIP_LIMIT }],
    queryFn: () => api.listKits({ status: "backlog", sort: "recent", limit: STRIP_LIMIT }),
  });
  const completed = useQuery({
    queryKey: ["kits", { status: "complete", sort: "recent", limit: STRIP_LIMIT }],
    queryFn: () => api.listKits({ status: "complete", sort: "recent", limit: STRIP_LIMIT }),
  });
  // Every pending order, by the last status change: a personal collection has a
  // handful in the mail, the stage is derived per row, and the cap is per column.
  const pending = useQuery({
    queryKey: ["orders", { pendingOnly: true, sort: "recent" }],
    queryFn: () => api.listOrders({ pendingOnly: true, sort: "recent" }),
  });
  const { data: retailers } = useQuery({ queryKey: ["retailers"], queryFn: api.listRetailers });
  // Warms the shared cache so the order dialog has the reference currency on open.
  useQuery(metaQuery);

  // The four catalog lists only when a card would name a catalog line; a
  // kit-only mailbox never asks for them. Same keys as the Orders page, so a
  // visit there has already paid for them.
  const wantNames = needsCatalogNames(pending.data ?? []);
  const { data: tools } = useQuery({ queryKey: ["tools"], queryFn: api.listTools, enabled: wantNames });
  const { data: consumables } = useQuery({
    queryKey: ["consumables"],
    queryFn: api.listConsumables,
    enabled: wantNames,
  });
  const { data: upgrades } = useQuery({
    queryKey: ["upgrades"],
    queryFn: api.listUpgrades,
    enabled: wantNames,
  });
  const { data: displayItems } = useQuery({
    queryKey: ["display-items"],
    queryFn: api.listDisplayItems,
    enabled: wantNames,
  });
  const catalogName = useMemo(() => {
    const map = new Map<string, string>();
    for (const row of [
      ...(tools ?? []),
      ...(consumables ?? []),
      ...(upgrades ?? []),
      ...(displayItems ?? []),
    ]) {
      map.set(row.id, row.name);
    }
    return (id: string) => map.get(id);
  }, [tools, consumables, upgrades, displayItems]);
  const retailerName = useMemo(
    () => new Map((retailers ?? []).map((retailer) => [retailer.id, retailer.name])),
    [retailers],
  );
  const mail = useMemo(() => bucketMail(pending.data ?? []), [pending.data]);

  const removeKit = async (kit: Kit) => {
    await api.deleteKit(kit.id);
    await invalidateKitViews(queryClient);
  };
  const removeOrder = async (order: Order) => {
    await api.deleteOrder(order.id);
    await invalidateOrderViews(queryClient);
  };

  const failed = [summary, bench, backlog, completed, pending].find((query) => query.isError);
  const counts = summary.data;
  const inTheMail = counts
    ? MAIL_STAGES.reduce((total, stage) => total + counts.orders[stage], 0)
    : undefined;

  return (
    <div className="space-y-7">
      <PageTitle>{t("home.title")}</PageTitle>
      {failed && (
        <ErrorBanner message={t("home.loadFailed", { message: (failed.error as Error).message })} />
      )}

      {/* On the bench: every kit in `building`, as wide cards — the bench is
          small by nature, so it is never capped. */}
      <section aria-labelledby="home-bench">
        <SectionHead
          id="home-bench"
          label={t("home.onTheBench")}
          count={counts?.kits.building}
          testId="home-count-building"
        />
        {bench.data === undefined ? (
          <EmptyState>{t("common.loading")}</EmptyState>
        ) : bench.data.length === 0 ? (
          <p className="text-sm text-muted">{t("home.benchEmpty")}</p>
        ) : (
          <div className="grid gap-4 md:grid-cols-2">
            {bench.data.map((kit) => (
              <BenchCard key={kit.id} kit={kit} onEdit={() => setDialog({ kind: "kit", kit })} />
            ))}
          </div>
        )}
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <section aria-labelledby="home-backlog" className="min-w-0">
          <SectionHead
            id="home-backlog"
            label={t("home.backlog")}
            count={counts?.kits.backlog}
            testId="home-count-backlog"
          />
          <KitStrip
            kits={backlog.data}
            total={counts?.kits.backlog}
            empty={t("home.backlogEmpty")}
            viewAll={(total) => countedPhrase("home.viewAllBacklog", total)}
            to="/kits?status=backlog&sort=recent"
            meta={(kit) => (
              <>
                <GradeChip grade={kit.grade} />
                {kit.scale && <span>{kit.scale}</span>}
              </>
            )}
            onEdit={(kit) => setDialog({ kind: "kit", kit })}
          />
        </section>
        <section aria-labelledby="home-completed" className="min-w-0">
          <SectionHead
            id="home-completed"
            label={t("home.recentlyCompleted")}
            count={counts?.kits.complete}
            testId="home-count-complete"
          />
          <KitStrip
            kits={completed.data}
            total={counts?.kits.complete}
            empty={t("home.completedEmpty")}
            viewAll={(total) => countedPhrase("home.viewAllCompleted", total)}
            to="/kits?status=complete&sort=recent"
            meta={(kit) => (
              <>
                {kit.rating != null ? (
                  <RatingStars rating={kit.rating} title={ratingTooltip(kit.rating)} />
                ) : (
                  <span aria-hidden className="text-faint">
                    —
                  </span>
                )}
                <span>{formatDate(completedOn(kit))}</span>
              </>
            )}
            onEdit={(kit) => setDialog({ kind: "kit", kit })}
          />
        </section>
      </div>

      <section aria-labelledby="home-mail">
        <SectionHead
          id="home-mail"
          label={t("home.inTheMail")}
          count={inTheMail}
          testId="home-count-mail"
        />
        <div className="grid gap-4 md:grid-cols-3">
          {MAIL_STAGES.map((stage) => (
            <MailColumn
              key={stage}
              stage={stage}
              orders={pending.data === undefined ? undefined : mail[stage]}
              total={counts?.orders[stage]}
              retailerName={retailerName}
              catalogName={catalogName}
              onEdit={(order) => setDialog({ kind: "order", order })}
            />
          ))}
        </div>
      </section>

      {dialog?.kind === "kit" && (
        <KitFormModal kit={dialog.kit} onClose={() => setDialog(null)} onDelete={removeKit} />
      )}
      {dialog?.kind === "order" && (
        <OrderFormModal
          order={dialog.order}
          onClose={() => setDialog(null)}
          onDelete={removeOrder}
        />
      )}
    </div>
  );
}

/** A section's micro-label and its true count (§13.2) — the count is the
 *  server's summary, so it can be on screen before the rows are. */
function SectionHead({
  id,
  label,
  count,
  testId,
}: {
  id: string;
  label: string;
  count: number | undefined;
  testId: string;
}) {
  return (
    <div className="mb-3 flex items-baseline gap-2.5">
      <h2 id={id} className={MICRO_LABEL_CLASS}>
        {label}
      </h2>
      {count !== undefined && (
        <span className="text-xs font-semibold tabular-nums text-muted" data-testid={testId}>
          {formatNumber(count)}
        </span>
      )}
    </div>
  );
}

/** The grade, as the compact chip the artboards draw beside a kit's name. */
function GradeChip({ grade }: { grade: string }) {
  return (
    <span className="inline-flex h-5 items-center rounded-sm bg-chip px-1.5 text-[11.5px] font-semibold tracking-wide text-text">
      {grade}
    </span>
  );
}

/** A kit on the bench: name, grade, scale, kit number, the start date with the
 *  day counter, the latest note, and the edit control in the corner. */
function BenchCard({ kit, onEdit }: { kit: Kit; onEdit: () => void }) {
  const { t } = useTranslation();
  return (
    <article className="relative flex min-w-0 flex-col gap-2.5 rounded-md border border-border-strong bg-surface px-5 pb-4 pt-4.5">
      <IconButton
        label={t("common.editNamed", { name: kit.name })}
        className="absolute end-2.5 top-2.5"
        onClick={onEdit}
      >
        <Pencil size={15} aria-hidden />
      </IconButton>
      <h3 className="pe-10 text-lg font-semibold leading-tight tracking-tight text-text">
        {kit.name}
      </h3>
      <div className="flex items-center gap-2 text-[12.5px] tabular-nums text-muted">
        <GradeChip grade={kit.grade} />
        {kit.scale && <span>{kit.scale}</span>}
        {kit.kit_number && <span>{kit.kit_number}</span>}
      </div>
      <div className="flex items-baseline gap-2.5 text-[13px] tabular-nums text-muted">
        {kit.build_started_at ? (
          <>
            <span>{t("home.startedOn", { date: formatDate(kit.build_started_at) })}</span>
            <span className="font-semibold text-accent">
              {t("home.dayNumber", {
                dayDisplay: formatNumber(buildDay(kit.build_started_at, new Date())),
              })}
            </span>
          </>
        ) : (
          <span>{t("home.noStartDate")}</span>
        )}
      </div>
      <p className="truncate text-[13px] text-muted" title={kit.build_notes ?? undefined}>
        {kit.build_notes ?? t("home.noNotes")}
      </p>
    </article>
  );
}

/** The Backlog / Recently completed strip: the most recent rows, a pencil on
 *  each, and the *view all* link that lands on Kits filtered and sorted. */
function KitStrip({
  kits,
  total,
  empty,
  viewAll,
  to,
  meta,
  onEdit,
}: {
  kits: Kit[] | undefined;
  total: number | undefined;
  empty: string;
  viewAll: (total: number) => string;
  to: string;
  meta: (kit: Kit) => React.ReactNode;
  onEdit: (kit: Kit) => void;
}) {
  const { t } = useTranslation();
  if (kits === undefined) return <EmptyState>{t("common.loading")}</EmptyState>;
  return (
    <div className="min-w-0 overflow-hidden rounded-md border border-border bg-surface">
      {kits.length === 0 && <div className="px-3.5 py-6 text-center text-sm text-muted">{empty}</div>}
      {kits.map((kit, index) => (
        <div
          key={kit.id}
          className={`flex h-10 items-center gap-3 px-3.5 ${index === 0 ? "" : "border-t border-rule"}`}
        >
          <span className="min-w-0 flex-1 truncate text-sm font-medium text-text">{kit.name}</span>
          <span className="flex items-center gap-2.5 text-[12.5px] tabular-nums text-muted">
            {meta(kit)}
          </span>
          <IconButton label={t("common.editNamed", { name: kit.name })} onClick={() => onEdit(kit)}>
            <Pencil size={15} aria-hidden />
          </IconButton>
        </div>
      ))}
      {total !== undefined && total > 0 && (
        <Link
          to={to}
          className={`flex h-9 items-center gap-1.5 px-3.5 text-[13px] font-medium text-accent hover:text-text ${
            kits.length === 0 ? "" : "border-t border-rule"
          }`}
        >
          {viewAll(total)}
          <ArrowRight size={14} aria-hidden className="rtl:-scale-x-100" />
        </Link>
      )}
    </div>
  );
}

/** One *In the mail* column: the stage as its chip, the count, up to
 *  `MAIL_CAP` cards, and *view all* into Orders filtered the same way. */
function MailColumn({
  stage,
  orders,
  total,
  retailerName,
  catalogName,
  onEdit,
}: {
  stage: MailStage;
  orders: Order[] | undefined;
  total: number | undefined;
  retailerName: Map<string, string>;
  catalogName: (id: string) => string | undefined;
  onEdit: (order: Order) => void;
}) {
  const { t } = useTranslation();
  const shown = orders?.slice(0, MAIL_CAP);
  return (
    <div className="min-w-0">
      <div className="mb-2.5 flex items-baseline gap-2">
        <StatusBadge status={stage} />
        {total !== undefined && (
          <span
            className="text-xs font-medium tabular-nums text-muted"
            data-testid={`home-count-${stage}`}
          >
            {formatNumber(total)}
          </span>
        )}
      </div>
      <div className="flex flex-col gap-2.5">
        {shown === undefined ? (
          <EmptyState>{t("common.loading")}</EmptyState>
        ) : shown.length === 0 ? (
          <div className="rounded-md border border-dashed border-border-strong px-3 py-5 text-center text-xs text-muted">
            {t(MAIL_COPY[stage].empty)}
          </div>
        ) : (
          shown.map((order) => (
            <OrderCard
              key={order.id}
              order={order}
              stage={stage}
              retailer={retailerName.get(order.retailer_id) ?? t("orders.unknownRetailer")}
              catalogName={catalogName}
              onEdit={() => onEdit(order)}
            />
          ))
        )}
        {total !== undefined && shown !== undefined && total > shown.length && (
          <Link
            to={`/orders?status=${stage}&sort=recent`}
            className="flex h-9 items-center gap-1.5 px-1 text-[13px] font-medium text-accent hover:text-text"
          >
            {countedPhrase(MAIL_COPY[stage].viewAll, total)}
            <ArrowRight size={14} aria-hidden className="rtl:-scale-x-100" />
          </Link>
        )}
      </div>
    </div>
  );
}

/** An order in the mail: retailer, the date of its last status change (placed,
 *  or shipped with the carrier), its first line, the rest, and the tracking
 *  number once shipped. The edit control opens the order dialog, where the
 *  ship and receive transitions live (#120). */
function OrderCard({
  order,
  stage,
  retailer,
  catalogName,
  onEdit,
}: {
  order: Order;
  stage: MailStage;
  retailer: string;
  catalogName: (id: string) => string | undefined;
  onEdit: () => void;
}) {
  const { t } = useTranslation();
  const lines = mailCardLines(order, catalogName);
  const when =
    stage === "in_transit" && order.shipped_at
      ? order.delivery_service
        ? t("home.shippedOnVia", {
            date: formatDate(order.shipped_at),
            service: order.delivery_service,
          })
        : t("home.shippedOn", { date: formatDate(order.shipped_at) })
      : t("home.placedOn", { date: formatDate(order.order_date) });
  const tracking = stage === "in_transit" ? order.tracking_number : null;
  return (
    <article className="relative flex min-w-0 flex-col gap-1 rounded-md border border-border bg-surface px-3.5 py-3">
      <IconButton
        label={t("home.editOrder", { retailer, date: formatDate(order.order_date) })}
        className="absolute end-2 top-2"
        onClick={onEdit}
      >
        <Pencil size={15} aria-hidden />
      </IconButton>
      <div className="flex items-baseline justify-between gap-2 pe-8 text-[12.5px] tabular-nums text-muted">
        <span className="truncate font-semibold text-text">{retailer}</span>
        <span className="shrink-0">{when}</span>
      </div>
      {lines.headline && (
        <div className="truncate pe-7 text-sm font-medium text-text">
          <LineLabel line={lines.headline} />
        </div>
      )}
      {lines.rest.kind === "one" && (
        <div className="truncate text-[12.5px] text-muted">
          <LineLabel line={lines.rest.line} and />
        </div>
      )}
      {lines.rest.kind === "many" && (
        <div className="text-[12.5px] text-muted">
          {countedPhrase("home.andMoreLines", lines.rest.count)}
        </div>
      )}
      {tracking &&
        (order.tracking_url ? (
          <a
            href={order.tracking_url}
            target="_blank"
            rel="noreferrer"
            className="font-mono text-[11.5px] text-muted hover:text-accent"
          >
            {tracking}
          </a>
        ) : (
          <span className="font-mono text-[11.5px] text-muted">{tracking}</span>
        ))}
    </article>
  );
}

/** A line as a card names it: "2 × name" past one, the item type while a
 *  catalog name is still loading, "and …" for the one other line, and the
 *  *pre-order* tag on a mixed order. */
function LineLabel({ line, and = false }: { line: LineSummary; and?: boolean }) {
  const { t } = useTranslation();
  const name = line.label ?? itemTypeLabel(line.itemType);
  const text =
    line.quantity > 1
      ? t("home.quantityOf", { quantityDisplay: formatNumber(line.quantity), name })
      : name;
  return (
    <>
      {and ? t("home.andLine", { line: text }) : text}
      {line.preOrder && (
        <span className="ms-1.5 inline-flex h-4.5 items-center rounded-sm bg-chip px-1.5 align-middle text-[11px] font-semibold text-status-pre-ordered">
          {t("home.preOrderTag")}
        </span>
      )}
    </>
  );
}
