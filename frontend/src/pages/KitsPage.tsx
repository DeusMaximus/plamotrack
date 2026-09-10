import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import type { Kit, KitStatus } from "../api/types";
import { KIT_SORTS, KIT_STATUSES, type KitSort } from "../api/types";
import { ExportCsvButton } from "../components/ExportCsvButton";
import { KitFormModal } from "../components/KitFormModal";
import { StatusBadge } from "../components/StatusBadge";
import {
  Button,
  EmptyState,
  ErrorBanner,
  IconButton,
  Input,
  PageTitle,
  Pager,
  RatingStars,
  Select,
  TABLE_HEAD_ROW_CLASS,
} from "../components/ui";
import { formatDate } from "../lib/format";
import { invalidateKitViews } from "../lib/invalidate";
import { dateWithElapsed, ratingTooltip, statusLabel } from "../lib/labels";
import { paginate, useEnumParam, usePageParam, useSearchParam, useTextParam } from "../lib/listState";
import { usePresentationVersion } from "../lib/presentation";

/** The completion cell: the date, and when a start exists too, the elapsed days
 *  beside it (deliberately elapsed, not time-at-the-bench — a shelved build reads
 *  long, and that is the documented shape of the two-column decision on #94). */
function completedCell(kit: Kit): string {
  if (!kit.build_completed_at) return "—";
  const date = formatDate(kit.build_completed_at);
  if (!kit.build_started_at) return date;
  const days = Math.round(
    (new Date(kit.build_completed_at).getTime() - new Date(kit.build_started_at).getTime()) /
      86_400_000,
  );
  return dateWithElapsed(date, days);
}

/** Rows per page on the list pages (§13.4). */
const PAGE_SIZE = 10;

export function KitsPage() {
  // Re-render when the instance's presentation settings arrive or change —
  // the plain format helpers below read them per call (#174 review, P3-1).
  usePresentationVersion();
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  // The list's state is the URL (§13.4, #232): a "view all" link from Home
  // and a bookmark land on a filtered, sorted page. The sort is the server's
  // — one definition of "recent" for the page, Home and the MCP tool — the
  // filters and the search narrow the loaded list here.
  const [statusFilter, setStatusFilter] = useEnumParam<KitStatus | "">(
    "status",
    ["", ...KIT_STATUSES],
    "",
  );
  const [seriesFilter, setSeriesFilter] = useTextParam("series");
  const [search, setSearch] = useSearchParam("q");
  const [sort, setSort] = useEnumParam<KitSort>("sort", KIT_SORTS, "recent");
  const [page, setPage] = usePageParam();
  const [modal, setModal] = useState<{ mode: "add" } | { mode: "edit"; kit: Kit } | null>(null);

  const {
    data: kits,
    isLoading,
    isError,
    error,
  } = useQuery({ queryKey: ["kits", { sort }], queryFn: () => api.listKits({ sort }) });

  const removeKit = async (kit: Kit) => {
    await api.deleteKit(kit.id);
    await invalidateKitViews(queryClient);
  };

  // Distinct series among the loaded kits, for the filter dropdown. Alphabetical:
  // a filter is scanned by eye, unlike the form's typeahead, which ranks by use.
  const seriesOptions = useMemo(() => {
    const values = new Set<string>();
    for (const kit of kits ?? []) if (kit.series) values.add(kit.series);
    return [...values].sort((a, b) => a.localeCompare(b));
  }, [kits]);

  const visible = useMemo(() => {
    let rows = kits ?? [];
    if (statusFilter) rows = rows.filter((kit) => kit.status === statusFilter);
    if (seriesFilter) rows = rows.filter((kit) => kit.series === seriesFilter);
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      rows = rows.filter(
        (kit) =>
          kit.name.toLowerCase().includes(q) || (kit.kit_number ?? "").toLowerCase().includes(q),
      );
    }
    return rows;
  }, [kits, statusFilter, seriesFilter, search]);
  const paged = paginate(visible, page, PAGE_SIZE);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <PageTitle count={kits === undefined ? undefined : visible.length}>{t("kits.title")}</PageTitle>
        <div className="flex gap-2">
          <ExportCsvButton table="kits" />
          <Button icon={Plus} onClick={() => setModal({ mode: "add" })}>
            {t("kits.addButton")}
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        <div className="relative w-full max-w-xs">
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
            placeholder={t("kits.searchPlaceholder")}
            className="ps-8"
          />
        </div>
        <Select
          aria-label={t("list.filterByStatus")}
          value={statusFilter}
          onChange={(event) => setStatusFilter(event.target.value as KitStatus | "")}
          className="!w-auto max-w-40"
        >
          <option value="">{t("kits.allStatuses")}</option>
          {KIT_STATUSES.map((status) => (
            <option key={status} value={status}>
              {statusLabel(status)}
            </option>
          ))}
        </Select>
        {seriesOptions.length > 0 && (
          <Select
            aria-label={t("kits.filterBySeries")}
            value={seriesFilter}
            onChange={(event) => setSeriesFilter(event.target.value)}
            className="!w-auto max-w-52"
          >
            <option value="">{t("kits.allSeries")}</option>
            {seriesOptions.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </Select>
        )}
        <Select
          aria-label={t("list.sortLabel")}
          value={sort}
          onChange={(event) => setSort(event.target.value as KitSort)}
          className="!w-auto"
        >
          <option value="recent">{t("kits.sortRecent")}</option>
          <option value="created">{t("kits.sortCreated")}</option>
          <option value="name">{t("kits.sortName")}</option>
        </Select>
      </div>

      {isError ? (
        <ErrorBanner message={t("kits.loadFailed", { message: (error as Error).message })} />
      ) : isLoading ? (
        <EmptyState>{t("common.loading")}</EmptyState>
      ) : visible.length === 0 ? (
        <EmptyState>
          {kits?.length === 0 ? t("kits.emptyNone") : t("kits.emptyFiltered")}
        </EmptyState>
      ) : (
        <div className="overflow-x-auto rounded-md border border-border bg-surface">
          <table className="w-full text-sm">
            <thead>
              <tr className={TABLE_HEAD_ROW_CLASS}>
                <th className="px-3 py-2.5">{t("kits.headerKit")}</th>
                <th className="px-3 py-2.5">{t("kits.grade")}</th>
                <th className="px-3 py-2.5">{t("kits.scale")}</th>
                <th className="px-3 py-2.5">{t("kits.status")}</th>
                <th className="px-3 py-2.5">{t("kits.headerRating")}</th>
                <th className="px-3 py-2.5">{t("kits.headerStarted")}</th>
                <th className="px-3 py-2.5">{t("kits.headerCompleted")}</th>
                <th className="px-3 py-2.5" />
              </tr>
            </thead>
            <tbody>
              {paged.rows.map((kit) => (
                <tr key={kit.id} className="border-b border-rule last:border-0 hover:bg-chip">
                  <td className="px-3 py-2">
                    <div className="font-medium">{kit.name}</div>
                    {(kit.kit_number || kit.series) && (
                      <div className="text-xs text-muted">
                        {[kit.kit_number, kit.series]
                          .filter(Boolean)
                          .join(t("common.dotSeparator"))}
                      </div>
                    )}
                  </td>
                  <td className="px-3 py-2">{kit.grade}</td>
                  <td className="px-3 py-2">{kit.scale ?? "—"}</td>
                  {/* Display only (#120): status changes go through Edit, where the
                      dates, rating and notes a real transition travels with live. The
                      inline select this replaces invited a half-done change. */}
                  <td className="px-3 py-2">
                    <StatusBadge status={kit.status} />
                  </td>
                  <td className="px-3 py-2">
                    {kit.rating ? (
                      <RatingStars rating={kit.rating} title={ratingTooltip(kit.rating)} />
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="px-3 py-2 text-muted" title={t("kits.buildStarted")}>
                    {kit.build_started_at ? formatDate(kit.build_started_at) : "—"}
                  </td>
                  <td className="px-3 py-2 text-muted" title={t("kits.completedTitle")}>
                    {completedCell(kit)}
                  </td>
                  {/* One control per row (§13.4): edit opens the dialog, where Delete lives. */}
                  <td className="px-2 py-2 text-end">
                    <IconButton
                      label={t("common.editNamed", { name: kit.name })}
                      onClick={() => setModal({ mode: "edit", kit })}
                    >
                      <Pencil size={15} aria-hidden />
                    </IconButton>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pager paged={paged} onPage={setPage} />
        </div>
      )}

      {modal && (
        <KitFormModal
          kit={modal.mode === "edit" ? modal.kit : undefined}
          onClose={() => setModal(null)}
          onDelete={removeKit}
        />
      )}
    </div>
  );
}
