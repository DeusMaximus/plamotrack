import { useState } from "react";

import type { ImportPlan, PlannedRow, RowAction, TablePlan } from "../api/types";

const ACTION_LABELS: Record<RowAction, string> = {
  create: "new",
  update: "updated",
  unchanged: "unchanged",
  skip: "skipped",
  error: "error",
};

const ACTION_STYLES: Record<RowAction, string> = {
  create: "bg-green-100 text-green-700",
  update: "bg-amber-100 text-amber-700",
  unchanged: "bg-zinc-100 text-zinc-500",
  skip: "bg-zinc-100 text-zinc-500",
  error: "bg-red-100 text-red-700",
};

const ACTION_ORDER: RowAction[] = ["create", "update", "unchanged", "skip", "error"];

const TABLE_LABELS: Record<string, string> = {
  retailers: "Retailers",
  tools: "Tools",
  consumables: "Consumables",
  upgrades: "Upgrades",
  orders: "Orders",
  order_items: "Order lines",
  kits: "Kits",
  upgrade_applications: "Upgrade applications",
  kit_photos: "Photos",
};

const SOURCE_LABELS: Record<string, string> = {
  archive: "full archive",
  "csv-set": "set of CSV files",
  "starter-sheet": "starter sheet",
};

function sourceLabel(source: string): string {
  if (SOURCE_LABELS[source]) return SOURCE_LABELS[source];
  if (source.startsWith("csv:")) {
    return `${TABLE_LABELS[source.slice(4)] ?? source.slice(4)} CSV`;
  }
  return source;
}

function CountPills({ counts }: { counts: Record<RowAction, number> }) {
  const shown = ACTION_ORDER.filter((action) => (counts[action] ?? 0) > 0);
  if (shown.length === 0) return <span className="text-xs text-zinc-400">nothing to do</span>;
  return (
    <span className="flex flex-wrap items-center gap-1">
      {shown.map((action) => (
        <span
          key={action}
          className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${ACTION_STYLES[action]}`}
        >
          {counts[action]} {ACTION_LABELS[action]}
        </span>
      ))}
    </span>
  );
}

function RowDetail({ row }: { row: PlannedRow }) {
  return (
    <tr className={row.action === "error" ? "bg-red-50/50" : undefined}>
      <td className="px-3 py-1.5 text-right align-top text-xs text-zinc-400 tabular-nums">
        {row.row_number || "—"}
      </td>
      <td className="px-3 py-1.5 align-top">
        <span
          className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${ACTION_STYLES[row.action]}`}
        >
          {ACTION_LABELS[row.action]}
        </span>
      </td>
      <td className="px-3 py-1.5 align-top">
        <div className="text-zinc-800">{row.label}</div>
        {row.matched_by && (
          <div className="text-[11px] text-zinc-400">matched on {row.matched_by}</div>
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
                <span className="line-through">{change.before || "(empty)"}</span>
                {" → "}
                <span className="text-zinc-800">{change.after || "(empty)"}</span>
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
        <span className="text-sm font-medium">{TABLE_LABELS[table.table] ?? table.table}</span>
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
  const totals = plan.tables.reduce<Record<string, number>>((acc, table) => {
    for (const action of ACTION_ORDER) {
      acc[action] = (acc[action] ?? 0) + (table.counts[action] ?? 0);
    }
    return acc;
  }, {});
  const deleted = Object.values(plan.derived.rows_deleted).reduce((a, b) => a + b, 0);

  return (
    <div className="space-y-3">
      {plan.blocking_errors.length > 0 && (
        <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          <p className="font-medium">This import can't run yet</p>
          <ul className="mt-1 list-inside list-disc space-y-0.5">
            {plan.blocking_errors.map((message) => (
              <li key={message}>{message}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 text-sm">
        <p className="text-zinc-700">
          Read as a <span className="font-medium">{sourceLabel(plan.source)}</span>
          {plan.manifest?.exported_at && (
            <span className="text-zinc-500">
              {" "}
              exported {new Date(plan.manifest.exported_at).toLocaleString()}
            </span>
          )}
          .
        </p>
        <p className="mt-1 text-zinc-600">
          <span className="font-medium text-green-700">{totals.create ?? 0} new</span>
          {" · "}
          <span className="font-medium text-amber-700">{totals.update ?? 0} updated</span>
          {" · "}
          {totals.unchanged ?? 0} unchanged
          {(totals.skip ?? 0) > 0 && ` · ${totals.skip} skipped`}
          {(totals.error ?? 0) > 0 && (
            <span className="font-medium text-red-700"> · {totals.error} with errors</span>
          )}
        </p>
        {deleted > 0 && (
          <p className="mt-1 font-medium text-red-700">
            {deleted} existing record{deleted === 1 ? "" : "s"} will be deleted first.
          </p>
        )}
        {plan.derived.kits_spawned > 0 && (
          <p className="mt-1 text-zinc-600">
            {plan.derived.kits_spawned} kit{plan.derived.kits_spawned === 1 ? "" : "s"} will be
            created from order lines that don't bring their own.
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
