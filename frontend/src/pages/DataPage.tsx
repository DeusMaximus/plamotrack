import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { api, ApiError, downloadFile } from "../api/client";
import type { ImportMode, ImportPlan, ImportResult } from "../api/types";
import { ImportPreview } from "../components/ImportPreview";
import { Button, ErrorBanner, Select } from "../components/ui";

const MODES: { id: ImportMode; label: string; blurb: string }[] = [
  {
    id: "merge",
    label: "Merge",
    blurb: "Update anything that matches, add anything new. The usual choice.",
  },
  {
    id: "add_only",
    label: "Add only",
    blurb: "Add what's new and leave everything you already have untouched.",
  },
  {
    id: "replace_all",
    label: "Replace everything",
    blurb: "Delete the whole collection first, then restore this file over the top.",
  },
];

function Card({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-lg border border-zinc-200 bg-white p-4">
      <h2 className="text-sm font-semibold text-zinc-800">{title}</h2>
      <p className="mt-0.5 text-xs text-zinc-500">{description}</p>
      <div className="mt-3">{children}</div>
    </section>
  );
}

const TABLE_EXPORTS = [
  { key: "kits", label: "Kits" },
  { key: "orders", label: "Orders" },
  { key: "order_items", label: "Order lines" },
  { key: "tools", label: "Tools" },
  { key: "consumables", label: "Consumables" },
  { key: "upgrades", label: "Upgrades" },
  { key: "retailers", label: "Retailers" },
];

export function DataPage() {
  const queryClient = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);

  const [file, setFile] = useState<File | null>(null);
  const [mode, setMode] = useState<ImportMode>("merge");
  const [plan, setPlan] = useState<ImportPlan | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [confirmText, setConfirmText] = useState("");
  const [busy, setBusy] = useState<"preview" | "apply" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  function reset() {
    setFile(null);
    setPlan(null);
    setResult(null);
    setConfirmText("");
    setError(null);
    if (fileInput.current) fileInput.current.value = "";
  }

  function pickFile(next: File | null) {
    setFile(next);
    // Any change invalidates the preview — never let an Apply run against a plan
    // the user is no longer looking at.
    setPlan(null);
    setResult(null);
    setError(null);
  }

  async function download(path: string, name: string) {
    setError(null);
    try {
      await downloadFile(path, name);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }

  async function runPreview() {
    if (!file) return;
    setBusy("preview");
    setError(null);
    setResult(null);
    try {
      setPlan(await api.previewImport(file, mode));
    } catch (err) {
      setPlan(null);
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  async function runApply() {
    if (!file || !plan) return;
    setBusy("apply");
    setError(null);
    try {
      const applied = await api.applyImport(
        file,
        mode,
        plan.plan_hash,
        mode === "replace_all" ? confirmText.trim().toUpperCase() : undefined,
      );
      setResult(applied);
      setPlan(null);
      setFile(null);
      setConfirmText("");
      if (fileInput.current) fileInput.current.value = "";
      await queryClient.invalidateQueries();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  const blocked = (plan?.blocking_errors.length ?? 0) > 0;
  const needsConfirm = mode === "replace_all" && confirmText.trim().toUpperCase() !== "REPLACE";

  return (
    <div className="max-w-4xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Data</h1>
        <p className="mt-0.5 text-sm text-zinc-500">
          Back up your collection, move it somewhere else, or bring it in from a spreadsheet.
        </p>
      </div>

      <ErrorBanner message={error} />

      <Card
        title="Export"
        description="Plain CSV — yours to keep, open anywhere, and import straight back."
      >
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => download("/export/archive", "plamotrack-export.zip")}>
            Download full archive (.zip)
          </Button>
          {TABLE_EXPORTS.map((table) => (
            <Button
              key={table.key}
              variant="secondary"
              onClick={() => download(`/export/${table.key}.csv`, `${table.key}.csv`)}
            >
              {table.label} .csv
            </Button>
          ))}
        </div>
      </Card>

      <Card
        title="Blank templates"
        description="Starting points for entering a collection by hand."
      >
        <div className="flex flex-wrap gap-2">
          <Button
            variant="secondary"
            onClick={() =>
              download("/export/starter-sheet.csv", "plamotrack-starter-sheet.csv")
            }
          >
            Starter sheet (.csv)
          </Button>
          <Button
            variant="secondary"
            onClick={() => download("/export/templates", "plamotrack-templates.zip")}
          >
            Full template pack (.zip)
          </Button>
        </div>
        <p className="mt-2 text-xs text-zinc-500">
          The starter sheet is one row per kit — name, grade, where you bought it — and the app
          works out the retailers, orders, and order lines from that. The template pack is one
          blank file per table, for when you want to control everything.
        </p>
      </Card>

      <Card
        title="Import"
        description="Nothing is written until you've seen exactly what will change."
      >
        <div
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDragging(false);
            pickFile(event.dataTransfer.files[0] ?? null);
          }}
          className={`rounded-lg border-2 border-dashed px-4 py-6 text-center ${
            dragging ? "border-indigo-400 bg-indigo-50" : "border-zinc-300 bg-zinc-50"
          }`}
        >
          <input
            ref={fileInput}
            type="file"
            accept=".csv,.zip"
            onChange={(event) => pickFile(event.target.files?.[0] ?? null)}
            className="hidden"
            id="import-file"
          />
          {file ? (
            <div className="space-y-1">
              <p className="text-sm font-medium text-zinc-800">{file.name}</p>
              <p className="text-xs text-zinc-500">{(file.size / 1024).toFixed(1)} KB</p>
              <button
                type="button"
                onClick={reset}
                className="text-xs text-indigo-600 hover:underline"
              >
                choose a different file
              </button>
            </div>
          ) : (
            <div className="space-y-1">
              <p className="text-sm text-zinc-600">Drop a .csv or .zip here</p>
              <label
                htmlFor="import-file"
                className="cursor-pointer text-xs text-indigo-600 hover:underline"
              >
                or browse for one
              </label>
            </div>
          )}
        </div>

        <div className="mt-3 flex flex-wrap items-end gap-3">
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-zinc-600">
              If something already exists
            </span>
            <Select
              value={mode}
              onChange={(event) => {
                setMode(event.target.value as ImportMode);
                setPlan(null);
                setResult(null);
              }}
              className="w-56"
            >
              {MODES.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.label}
                </option>
              ))}
            </Select>
          </label>
          <Button onClick={runPreview} disabled={!file || busy !== null}>
            {busy === "preview" ? "Reading…" : "Preview changes"}
          </Button>
        </div>
        <p className="mt-1.5 text-xs text-zinc-500">
          {MODES.find((option) => option.id === mode)?.blurb}
        </p>

        {plan && (
          <div className="mt-4 space-y-3">
            <ImportPreview plan={plan} />

            {mode === "replace_all" && !blocked && (
              <label className="block rounded-md border border-red-200 bg-red-50 px-3 py-2">
                <span className="mb-1 block text-xs font-medium text-red-700">
                  This deletes your current collection. Type REPLACE to confirm.
                </span>
                <input
                  value={confirmText}
                  onChange={(event) => setConfirmText(event.target.value)}
                  placeholder="REPLACE"
                  className="w-40 rounded-md border border-red-300 bg-white px-2.5 py-1.5 text-sm focus:border-red-500 focus:outline-none"
                />
              </label>
            )}

            <div className="flex items-center gap-2">
              <Button onClick={runApply} disabled={blocked || needsConfirm || busy !== null}>
                {busy === "apply" ? "Importing…" : "Apply import"}
              </Button>
              <Button variant="secondary" onClick={reset} disabled={busy !== null}>
                Cancel
              </Button>
            </div>
          </div>
        )}

        {result && (
          <div className="mt-4 rounded-md border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-800">
            <p className="font-medium">Import complete</p>
            <p className="mt-0.5">
              {result.created} created · {result.updated} updated · {result.skipped} skipped
              {result.kits_spawned > 0 && ` · ${result.kits_spawned} kits created from order lines`}
              {result.kits_removed > 0 && ` · ${result.kits_removed} kits removed from order lines`}
            </p>
          </div>
        )}
      </Card>
    </div>
  );
}
