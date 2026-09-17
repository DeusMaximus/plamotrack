import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, summaryQuery } from "../api/client";
import type { Kit, KitStatus } from "../api/types";
import { KIT_SORTS, KIT_STATUSES, type KitSort } from "../api/types";
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
import { KitFormModal } from "../components/KitFormModal";
import { StatusBadge } from "../components/StatusBadge";
import {
  Button,
  CardList,
  CardMeta,
  CardRow,
  EmptyState,
  ErrorBanner,
  GradeChip,
  IconButton,
  Input,
  PageHeader,
  Pager,
  RatingStars,
  Select,
  TABLE_HEAD_ROW_CLASS,
} from "../components/ui";
import { formatDate } from "../lib/format";
import { invalidateKitViews } from "../lib/invalidate";
import { countedPhrase, dateWithElapsed, ratingTooltip, statusLabel } from "../lib/labels";
import { filterKits } from "../lib/listFilters";
import {
  paginate,
  useEnumParam,
  usePageParam,
  useSearchParam,
  useTextParam,
  useWriteParams,
} from "../lib/listState";
import { usePresentationVersion } from "../lib/presentation";
import { useShell } from "../lib/shell";
import { STATUS_TONES } from "../lib/tones";

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

/** The sorts in the order the page offers them — the default first — which is
 *  not `KIT_SORTS`' wire order. Keyed by the type, so a new sort stops compiling
 *  until it has a label. */
const SORT_LABEL = {
  recent: "kits.sortRecent",
  created: "kits.sortCreated",
  name: "kits.sortName",
} as const satisfies Record<KitSort, string>;
const SORT_ORDER = Object.keys(SORT_LABEL) as KitSort[];

type KitListState = { status: KitStatus | ""; series: string; sort: KitSort };
const NO_FILTERS: KitListState = { status: "", series: "", sort: "recent" };

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
  const writeParams = useWriteParams();
  const [modal, setModal] = useState<{ mode: "add" } | { mode: "edit"; kit: Kit } | null>(null);
  // Card rows and the filter sheet are the phone's (§13.7); the sheet's state
  // is not the shell's, so a sheet open across a rotation stays a dialog.
  const phone = useShell() === "phone";
  const [sheetOpen, setSheetOpen] = useState(false);

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

  const visible = useMemo(
    () => filterKits(kits ?? [], { status: statusFilter, series: seriesFilter, search }),
    [kits, statusFilter, seriesFilter, search],
  );
  const paged = paginate(visible, page, PAGE_SIZE);
  const editLabel = (kit: Kit) => t("common.editNamed", { name: kit.name });

  return (
    <div className="space-y-4">
      <PageHeader
        title={t("kits.title")}
        count={kits === undefined ? undefined : visible.length}
        secondary={<ExportCsvButton table="kits" />}
        actions={
          <Button icon={Plus} onClick={() => setModal({ mode: "add" })}>
            {t("kits.addButton")}
          </Button>
        }
      />

      {/* One search box in every shell — the same node, so a rotation keeps its
          text and its focus. Beside it, a phone has the one *Filter and sort*
          control (§13.7); wider, the filters themselves. */}
      <div className="flex flex-wrap gap-2 max-md:flex-nowrap">
        <div className="relative w-full max-w-xs max-md:w-auto max-md:max-w-none max-md:flex-1">
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
        {phone ? (
          <FilterSheetButton
            active={Number(statusFilter !== "") + Number(seriesFilter !== "")}
            onClick={() => setSheetOpen(true)}
          />
        ) : (
          <>
            <Select
              aria-label={t("list.filterByStatus")}
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value as KitStatus | "")}
              className="!w-auto max-w-40"
              data-focus-key={FILTERS_FOCUS}
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
        <ErrorBanner message={t("kits.loadFailed", { message: (error as Error).message })} />
      ) : isLoading ? (
        <EmptyState>{t("common.loading")}</EmptyState>
      ) : visible.length === 0 ? (
        <EmptyState>
          {kits?.length === 0 ? t("kits.emptyNone") : t("kits.emptyFiltered")}
        </EmptyState>
      ) : phone ? (
        <CardList footer={<Pager paged={paged} onPage={setPage} />}>
          {paged.rows.map((kit) => (
            <CardRow
              key={kit.id}
              title={kit.name}
              action={
                <IconButton
                  label={editLabel(kit)}
                  onClick={() => setModal({ mode: "edit", kit })}
                  data-focus-key={`kit:${kit.id}`}
                >
                  <Pencil size={16} aria-hidden />
                </IconButton>
              }
            >
              <CardMeta>
                <StatusBadge status={kit.status} />
                <GradeChip grade={kit.grade} />
                {kit.scale && <span className="shrink-0">{kit.scale}</span>}
                {kit.series && <span className="min-w-0 truncate">{kit.series}</span>}
              </CardMeta>
            </CardRow>
          ))}
        </CardList>
      ) : (
        // `@container`: the table folds to the width this box has, not the
        // device's (§13.7). Below 48rem (768 px) — the 732 px the full table
        // needs on the demo data, and a little — Grade and Scale leave their columns for
        // the name's second line, the card row's shape. Every iPad in portrait
        // is under it beside the rail; beside the sidebar the box is 976 px at
        // 1280, so the desktop never is.
        <div className="@container overflow-x-auto rounded-md border border-border bg-surface">
          <table className="w-full text-sm">
            <thead>
              <tr className={TABLE_HEAD_ROW_CLASS}>
                <th className="px-3 py-2.5">{t("kits.headerKit")}</th>
                <th className="px-3 py-2.5 @max-[48rem]:hidden">{t("kits.grade")}</th>
                <th className="px-3 py-2.5 @max-[48rem]:hidden">{t("kits.scale")}</th>
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
                    {/* Always there: folded, it is where the grade and scale go,
                        whether or not a number or series follows. Unfolded and
                        empty it has no line box, so no height. */}
                    <div className="text-xs text-muted">
                      <span className="hidden @max-[48rem]:inline">
                        <GradeChip grade={kit.grade} />
                        {kit.scale && <span className="ms-2">{kit.scale}</span>}
                        {(kit.kit_number || kit.series) && t("common.dotSeparator")}
                      </span>
                      {[kit.kit_number, kit.series].filter(Boolean).join(t("common.dotSeparator"))}
                    </div>
                  </td>
                  <td className="px-3 py-2 @max-[48rem]:hidden">{kit.grade}</td>
                  <td className="px-3 py-2 @max-[48rem]:hidden">
                    {kit.scale ?? "—"}
                  </td>
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
                  {/* One control per row (§13.4): edit opens the dialog, where Delete lives.
                      `touch:px-0`: the 44 px target carries its own margin around
                      the icon, so a touch table needs no more width than a mouse's
                      — one fold line serves both. */}
                  <td className="px-2 py-2 text-end touch:px-0">
                    <IconButton
                      label={editLabel(kit)}
                      onClick={() => setModal({ mode: "edit", kit })}
                      data-focus-key={`kit:${kit.id}`}
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
      {sheetOpen && (
        <KitFilterSheet
          kits={kits ?? []}
          search={search}
          seriesOptions={seriesOptions}
          current={{ status: statusFilter, series: seriesFilter, sort }}
          onApply={(next) => {
            // One navigation for all of it, the page reset with it (§13.4) — and
            // each parameter dropped at its default, so the URL the sheet leaves
            // is the one the desktop's selects and a Home link would.
            writeParams({
              status: next.status || null,
              series: next.series || null,
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

/** The Kits filter sheet (§13.7): status as toggles with the collection's count
 *  of each (`GET /summary`), series as a native select, the sort segmented. It
 *  holds a draft; the button counts what the draft would show, through the same
 *  `filterKits` the page reads, with the page's search still applied. */
function KitFilterSheet({
  kits,
  search,
  seriesOptions,
  current,
  onApply,
  onClose,
}: {
  kits: Kit[];
  search: string;
  seriesOptions: string[];
  current: KitListState;
  onApply: (next: KitListState) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState(current);
  const { data: summary } = useQuery(summaryQuery);
  const total = summary && KIT_STATUSES.reduce((sum, status) => sum + summary.kits[status], 0);
  const matching = filterKits(kits, { status: draft.status, series: draft.series, search }).length;

  return (
    <FilterSheet
      applyLabel={countedPhrase("kits.showCount", matching)}
      onApply={() => onApply(draft)}
      onClear={() => setDraft(NO_FILTERS)}
      onClose={onClose}
    >
      <SheetSection label={t("kits.status")}>
        <ToggleGrid>
          <ToggleOption
            pressed={draft.status === ""}
            count={total}
            onClick={() => setDraft({ ...draft, status: "" })}
          >
            {t("kits.allStatuses")}
          </ToggleOption>
          {KIT_STATUSES.map((status) => (
            <ToggleOption
              key={status}
              pressed={draft.status === status}
              tone={STATUS_TONES[status]}
              count={summary?.kits[status]}
              onClick={() => setDraft({ ...draft, status })}
            >
              {statusLabel(status)}
            </ToggleOption>
          ))}
        </ToggleGrid>
      </SheetSection>
      {seriesOptions.length > 0 && (
        <SheetSection label={t("kits.series")}>
          <Select
            aria-label={t("kits.filterBySeries")}
            value={draft.series}
            onChange={(event) => setDraft({ ...draft, series: event.target.value })}
          >
            <option value="">{t("kits.allSeries")}</option>
            {seriesOptions.map((value) => (
              <option key={value} value={value}>
                {value}
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
