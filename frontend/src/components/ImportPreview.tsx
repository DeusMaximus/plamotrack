import { useState } from "react";
import { Trans, useTranslation } from "react-i18next";

import type { ImportPlan, PlannedRow, RowAction, TablePlan } from "../api/types";
import { ROW_ACTIONS } from "../api/types";
import i18n from "../i18n";
import { formatDateTime } from "../lib/format";
import { importActionLabel, importTableLabel } from "../lib/labels";

const ACTION_STYLES: Record<RowAction, string> = {
  create: "bg-green-100 text-green-700",
  update: "bg-amber-100 text-amber-700",
  unchanged: "bg-zinc-100 text-zinc-500",
  skip: "bg-zinc-100 text-zinc-500",
  error: "bg-red-100 text-red-700",
};

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
  return i18n.t(`importCount.${action}`, { count });
}

/** A table-header pill — "3 new", "6 error". A third grammatical slot, not a
 * restatement: the pill pairs the count with the badge word where the totals
 * line says "with errors" (#163 review, P3-1 — the pills borrowed the totals
 * group and silently reworded the one action whose two phrasings differ). */
function pillCount(action: RowAction, count: number): string {
  return i18n.t(`importPill.${action}`, { count });
}

function CountPills({ counts }: { counts: Record<RowAction, number> }) {
  const { t } = useTranslation();
  const shown = ROW_ACTIONS.filter((action) => (counts[action] ?? 0) > 0);
  if (shown.length === 0)
    return <span className="text-xs text-zinc-400">{t("importPreview.nothingToDo")}</span>;
  return (
    <span className="flex flex-wrap items-center gap-1">
      {shown.map((action) => (
        <span
          key={action}
          className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${ACTION_STYLES[action]}`}
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
    <tr className={row.action === "error" ? "bg-red-50/50" : undefined}>
      <td className="px-3 py-1.5 text-right align-top text-xs text-zinc-400 tabular-nums">
        {row.row_number || "—"}
      </td>
      <td className="px-3 py-1.5 align-top">
        <span
          className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${ACTION_STYLES[row.action]}`}
        >
          {importActionLabel(row.action)}
        </span>
      </td>
      <td className="px-3 py-1.5 align-top">
        <div className="text-zinc-800">{row.label}</div>
        {row.matched_by && (
          <div className="text-[11px] text-zinc-400">
            {t("importPreview.matchedOn", { field: row.matched_by })}
          </div>
        )}
        {row.error && <div className="text-xs text-red-600">{row.error}</div>}
        {row.messages.map((message) => (
          <div key={message} className="text-[11px] text-amber-700">
            {message}
          </div>
        ))}
        {row.changes.length > 0 && (
          <ul className="mt-1 space-y-0.5">
            {row.changes.map((change) => (
              <li key={change.field} className="text-[11px] text-zinc-500">
                <span className="font-medium text-zinc-600">{change.field}</span>{" "}
                <span className="line-through">
                  {change.before || t("importPreview.emptyValue")}
                </span>
                {" → "}
                <span className="text-zinc-800">{change.after || t("importPreview.emptyValue")}</span>
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
    <div className="rounded-lg border border-zinc-200 bg-white">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-zinc-50"
        aria-expanded={open}
      >
        <span className="w-3 text-xs text-zinc-400">{open ? "▾" : "▸"}</span>
        <span className="text-sm font-medium">{importTableLabel(table.table)}</span>
        <span className="ml-auto">
          <CountPills counts={table.counts} />
        </span>
      </button>
      {open && (
        <div className="max-h-80 overflow-y-auto border-t border-zinc-100">
          <table className="w-full text-sm">
            <tbody className="divide-y divide-zinc-100">
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
        <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          <p className="font-medium">{t("importPreview.blockedTitle")}</p>
          <ul className="mt-1 list-inside list-disc space-y-0.5">
            {plan.blocking_errors.map((message) => (
              <li key={message}>{message}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 text-sm">
        <p className="text-zinc-700">
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
              muted: <span className="text-zinc-500" />,
            }}
          />
        </p>
        <p className="mt-1 text-zinc-600">
          <span className="font-medium text-green-700">
            {actionCount("create", totals.create ?? 0)}
          </span>
          {t("common.dotSeparator")}
          <span className="font-medium text-amber-700">
            {actionCount("update", totals.update ?? 0)}
          </span>
          {t("common.dotSeparator")}
          {actionCount("unchanged", totals.unchanged ?? 0)}
          {(totals.skip ?? 0) > 0 && t("common.dotSeparator") + actionCount("skip", totals.skip)}
          {(totals.error ?? 0) > 0 && (
            <span className="font-medium text-red-700">
              {t("common.dotSeparator")}
              {actionCount("error", totals.error)}
            </span>
          )}
        </p>
        {deleted > 0 && (
          <p className="mt-1 font-medium text-red-700">
            {t("importPreview.recordsDeleted", { count: deleted })}
          </p>
        )}
        {plan.derived.kits_spawned > 0 && (
          <p className="mt-1 text-zinc-600">
            {t("importPreview.kitsSpawned", { count: plan.derived.kits_spawned })}
          </p>
        )}
        {/* Red, alongside the deletion count: no row in the table below names these
            kits, so this line is the only warning the operator gets. */}
        {plan.derived.kits_removed > 0 && (
          <p className="mt-1 font-medium text-red-700">
            {t("importPreview.kitsRemoved", { count: plan.derived.kits_removed })}
          </p>
        )}
        {/* Also named by no row — the per-order messages below say which way. */}
        {plan.derived.kits_advanced > 0 && (
          <p className="mt-1 text-zinc-600">
            {t("importPreview.kitsAdvanced", { count: plan.derived.kits_advanced })}
          </p>
        )}
        <p className="mt-1 text-xs text-zinc-500">{plan.derived.stock_note}</p>
      </div>

      {plan.warnings.length > 0 && (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          <ul className="list-inside list-disc space-y-0.5">
            {plan.warnings.map((message) => (
              <li key={message}>{message}</li>
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
