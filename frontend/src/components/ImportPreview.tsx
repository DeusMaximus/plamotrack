import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";
import { Trans, useTranslation } from "react-i18next";

import type { ImportPlan, PlannedRow, RowAction, TablePlan } from "../api/types";
import { ROW_ACTIONS } from "../api/types";
import i18n from "../i18n";
import { resolveDiagnostic } from "../lib/apiError";
import { formatDateTime, formatNumber } from "../lib/format";
import { counted, countedPhrase, importActionLabel, importFieldLabel, importTableLabel, matchedByLabel } from "../lib/labels";
import { usePresentationVersion } from "../lib/presentation";

/** Row actions in the pipeline's colours (§13.1): a create is complete's
 * green, an update in-transit's amber, an error danger, the rest quiet. */
const ACTION_TONES: Record<RowAction, string> = {
  create: "text-status-complete",
  update: "text-status-in-transit",
  unchanged: "text-muted",
  skip: "text-muted",
  error: "text-danger",
};

const PILL_CLASS = "rounded-sm bg-chip px-1.5 py-0.5 text-[11px] font-semibold";

function sourceLabel(source: string): string {
  const key = `importSource.${source}`;
  if (i18n.exists(key)) return i18n.t(key as "importSource.archive");
  if (source.startsWith("csv:")) {
    return i18n.t("importPreview.csvOf", { table: importTableLabel(source.slice(4)) });
  }
  return source;
}

/** The totals line's counted phrase — "3 new", "6 with errors". */
function actionCount(action: RowAction, count: number): string {
  return countedPhrase(`importCount.${action}`, count);
}

/** A table-header pill — "3 new", "6 error". A third grammatical slot, not a
 * restatement: the pill pairs the count with the badge word where the totals
 * line says "with errors" (#163 review, P3-1 — the pills borrowed the totals
 * group and silently reworded the one action whose two phrasings differ). */
function pillCount(action: RowAction, count: number): string {
  return countedPhrase(`importPill.${action}`, count);
}

function CountPills({ counts }: { counts: Record<RowAction, number> }) {
  const { t } = useTranslation();
  const shown = ROW_ACTIONS.filter((action) => (counts[action] ?? 0) > 0);
  if (shown.length === 0)
    return <span className="text-xs text-faint">{t("importPreview.nothingToDo")}</span>;
  return (
    <span className="flex flex-wrap items-center gap-1">
      {shown.map((action) => (
        <span
          key={action}
          className={`${PILL_CLASS} ${ACTION_TONES[action]}`}
        >
          {pillCount(action, counts[action])}
        </span>
      ))}
    </span>
  );
}

function RowDetail({ row }: { row: PlannedRow }) {
  const { t } = useTranslation();
  return (
    <tr className={row.action === "error" ? "bg-danger/5" : undefined}>
      <td className="px-3 py-1.5 text-end align-top text-xs text-faint tabular-nums">
        {row.row_number ? formatNumber(row.row_number) : "—"}
      </td>
      <td className="px-3 py-1.5 align-top">
        <span
          className={`${PILL_CLASS} ${ACTION_TONES[row.action]}`}
        >
          {importActionLabel(row.action)}
        </span>
      </td>
      <td className="px-3 py-1.5 align-top">
        <div className="text-text">{row.label}</div>
        {row.matched_by && (
          <div className="text-[11px] text-faint">
            {t("importPreview.matchedOn", { field: matchedByLabel(row.matched_by) })}
          </div>
        )}
        {row.errors.map((diagnostic, index) => (
          <div key={`${diagnostic.code}-${index}`} className="text-xs text-danger">
            {resolveDiagnostic(diagnostic)}
          </div>
        ))}
        {row.messages.map((diagnostic, index) => (
          <div key={`${diagnostic.code}-${index}`} className="text-[11px] text-status-in-transit">
            {resolveDiagnostic(diagnostic)}
          </div>
        ))}
        {row.changes.length > 0 && (
          <ul className="mt-1 space-y-0.5">
            {row.changes.map((change) => (
              <li key={change.field} className="text-[11px] text-muted">
                <span className="font-medium text-muted">{importFieldLabel(change.field)}</span>{" "}
                <span className="line-through">
                  {change.before || t("importPreview.emptyValue")}
                </span>
                {" → "}
                <span className="text-text">{change.after || t("importPreview.emptyValue")}</span>
              </li>
            ))}
          </ul>
        )}
      </td>
    </tr>
  );
}

function TableSection({ table }: { table: TablePlan }) {
  const noise = table.rows.every((row) => row.action === "unchanged" || row.action === "skip");
  const [open, setOpen] = useState(!noise);
  // An error is the one thing you must not have to click to discover.
  const rows = table.rows.some((row) => row.action === "error")
    ? [...table.rows].sort((a, b) => (a.action === "error" ? -1 : b.action === "error" ? 1 : 0))
    : table.rows;

  return (
    <div className="rounded-md border border-border bg-surface">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-2 px-3 py-2 text-start hover:bg-chip"
        aria-expanded={open}
      >
        <span className="flex w-3 items-center text-faint">
          {open ? (
            <ChevronDown size={14} aria-hidden />
          ) : (
            <ChevronRight size={14} aria-hidden className="rtl:-scale-x-100" />
          )}
        </span>
        <span className="text-sm font-medium">{importTableLabel(table.table)}</span>
        <span className="ms-auto">
          <CountPills counts={table.counts} />
        </span>
      </button>
      {open && (
        <div className="max-h-80 overflow-y-auto border-t border-rule">
          <table className="w-full text-sm">
            <tbody className="divide-y divide-rule">
              {rows.map((row) => (
                <RowDetail key={`${row.row_number}-${row.label}`} row={row} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function ImportPreview({ plan }: { plan: ImportPlan }) {
  // Re-render when the instance's presentation settings arrive or change —
  // the plain format helpers below read them per call (#174 review, P3-1).
  usePresentationVersion();
  const { t } = useTranslation();
  const totals = plan.tables.reduce<Record<string, number>>((acc, table) => {
    for (const action of ROW_ACTIONS) {
      acc[action] = (acc[action] ?? 0) + (table.counts[action] ?? 0);
    }
    return acc;
  }, {});
  const deleted = Object.values(plan.derived.rows_deleted).reduce((a, b) => a + b, 0);

  return (
    <div className="space-y-3">
      {plan.blocking_errors.length > 0 && (
        <div className="rounded-sm border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
          <p className="font-medium">{t("importPreview.blockedTitle")}</p>
          <ul className="mt-1 list-inside list-disc space-y-0.5">
            {plan.blocking_errors.map((diagnostic, index) => (
              <li key={`${diagnostic.code}-${index}`}>{resolveDiagnostic(diagnostic)}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="rounded-md border border-border bg-surface-alt px-3 py-2 text-sm">
        <p className="text-text">
          <Trans
            i18nKey={
              plan.manifest?.exported_at ? "importPreview.readAsExported" : "importPreview.readAs"
            }
            values={{
              source: sourceLabel(plan.source),
              exportedAt: plan.manifest?.exported_at
                ? formatDateTime(plan.manifest.exported_at)
                : undefined,
            }}
            components={{
              src: <span className="font-medium" />,
              muted: <span className="text-muted" />,
            }}
          />
        </p>
        <p className="mt-1 text-muted">
          <span className="font-medium text-status-complete">
            {actionCount("create", totals.create ?? 0)}
          </span>
          {t("common.dotSeparator")}
          <span className="font-medium text-status-in-transit">
            {actionCount("update", totals.update ?? 0)}
          </span>
          {t("common.dotSeparator")}
          {actionCount("unchanged", totals.unchanged ?? 0)}
          {(totals.skip ?? 0) > 0 && t("common.dotSeparator") + actionCount("skip", totals.skip)}
          {(totals.error ?? 0) > 0 && (
            <span className="font-medium text-danger">
              {t("common.dotSeparator")}
              {actionCount("error", totals.error)}
            </span>
          )}
        </p>
        {deleted > 0 && (
          <p className="mt-1 font-medium text-danger">
            {t("importPreview.recordsDeleted", counted({}, deleted))}
          </p>
        )}
        {plan.derived.kits_spawned > 0 && (
          <p className="mt-1 text-muted">
            {t("importPreview.kitsSpawned", counted({}, plan.derived.kits_spawned))}
          </p>
        )}
        {/* Red, alongside the deletion count: no row in the table below names these
            kits, so this line is the only warning the operator gets. */}
        {plan.derived.kits_removed > 0 && (
          <p className="mt-1 font-medium text-danger">
            {t("importPreview.kitsRemoved", counted({}, plan.derived.kits_removed))}
          </p>
        )}
        {/* Also named by no row — the per-order messages below say which way. */}
        {plan.derived.kits_advanced > 0 && (
          <p className="mt-1 text-muted">
            {t("importPreview.kitsAdvanced", counted({}, plan.derived.kits_advanced))}
          </p>
        )}
        {plan.derived.stock_note && (
          <p className="mt-1 text-xs text-muted">
            {resolveDiagnostic(plan.derived.stock_note)}
          </p>
        )}
      </div>

      {plan.warnings.length > 0 && (
        <div className="rounded-sm border border-status-in-transit/40 bg-status-in-transit/10 px-3 py-2 text-xs text-status-in-transit">
          <ul className="list-inside list-disc space-y-0.5">
            {plan.warnings.map((diagnostic, index) => (
              <li key={`${diagnostic.code}-${index}`}>{resolveDiagnostic(diagnostic)}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="space-y-2">
        {plan.tables.map((table) => (
          <TableSection key={table.table} table={table} />
        ))}
      </div>
    </div>
  );
}
