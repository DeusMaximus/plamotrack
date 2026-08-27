import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, ApiError, downloadFile } from "../api/client";
import type { ImportMode, ImportPlan, ImportResult } from "../api/types";
import { IMPORT_MODES } from "../api/types";
import { ImportPreview } from "../components/ImportPreview";
import { Button, ErrorBanner, Select } from "../components/ui";
import { importTableLabel } from "../lib/labels";

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

/** Keys are `portability/spec.py` table keys, not REST paths — `/export/{key}.csv`.
 *  Hand-maintained against that registry, which is the trap it fell into: the
 *  backend gained `display_items` and exported it correctly, and only this list
 *  decided nobody could reach it from the Data page (#129 review, P3-5). Adding a
 *  portable table means adding a line here — and its label to `importTable.*` in
 *  the catalogue, which ImportPreview reads too. */
const TABLE_EXPORTS = [
  "kits",
  "orders",
  "order_items",
  "tools",
  "consumables",
  "upgrades",
  "display_items",
  "retailers",
  "instance_settings",
];

export function DataPage() {
  const { t } = useTranslation();
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
        <h1 className="text-2xl font-bold">{t("data.title")}</h1>
        <p className="mt-0.5 text-sm text-zinc-500">{t("data.subtitle")}</p>
      </div>

      <ErrorBanner message={error} />

      <Card title={t("data.exportTitle")} description={t("data.exportDescription")}>
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => download("/export/archive", "plamotrack-export.zip")}>
            {t("data.archiveButton")}
          </Button>
          {TABLE_EXPORTS.map((table) => (
            <Button
              key={table}
              variant="secondary"
              onClick={() => download(`/export/${table}.csv`, `${table}.csv`)}
            >
              {importTableLabel(table)} .csv
            </Button>
          ))}
        </div>
      </Card>

      <Card title={t("data.templatesTitle")} description={t("data.templatesDescription")}>
        <div className="flex flex-wrap gap-2">
          <Button
            variant="secondary"
            onClick={() =>
              download("/export/starter-sheet.csv", "plamotrack-starter-sheet.csv")
            }
          >
            {t("data.starterSheetButton")}
          </Button>
          <Button
            variant="secondary"
            onClick={() => download("/export/templates", "plamotrack-templates.zip")}
          >
            {t("data.templatePackButton")}
          </Button>
        </div>
        <p className="mt-2 text-xs text-zinc-500">{t("data.starterBlurb")}</p>
      </Card>

      <Card title={t("data.importTitle")} description={t("data.importDescription")}>
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
                {t("data.chooseDifferent")}
              </button>
            </div>
          ) : (
            <div className="space-y-1">
              <p className="text-sm text-zinc-600">{t("data.dropHere")}</p>
              <label
                htmlFor="import-file"
                className="cursor-pointer text-xs text-indigo-600 hover:underline"
              >
                {t("data.browse")}
              </label>
            </div>
          )}
        </div>

        <div className="mt-3 flex flex-wrap items-end gap-3">
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-zinc-600">
              {t("data.modeLabel")}
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
              {IMPORT_MODES.map((option) => (
                <option key={option} value={option}>
                  {t(`importMode.${option}.label`)}
                </option>
              ))}
            </Select>
          </label>
          <Button onClick={runPreview} disabled={!file || busy !== null}>
            {busy === "preview" ? t("data.reading") : t("data.previewChanges")}
          </Button>
        </div>
        <p className="mt-1.5 text-xs text-zinc-500">{t(`importMode.${mode}.blurb`)}</p>

        {plan && (
          <div className="mt-4 space-y-3">
            <ImportPreview plan={plan} />

            {mode === "replace_all" && !blocked && (
              <label className="block rounded-md border border-red-200 bg-red-50 px-3 py-2">
                <span className="mb-1 block text-xs font-medium text-red-700">
                  {t("data.replaceConfirm")}
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
                {busy === "apply" ? t("data.importing") : t("data.applyImport")}
              </Button>
              <Button variant="secondary" onClick={reset} disabled={busy !== null}>
                {t("common.cancel")}
              </Button>
            </div>
          </div>
        )}

        {result && (
          <div className="mt-4 rounded-md border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-800">
            <p className="font-medium">{t("data.complete")}</p>
            <p className="mt-0.5">
              {t("data.result.created", { count: result.created })}
              {t("common.dotSeparator")}
              {t("data.result.updated", { count: result.updated })}
              {t("common.dotSeparator")}
              {t("data.result.skipped", { count: result.skipped })}
              {result.kits_spawned > 0 &&
                t("common.dotSeparator") +
                  t("data.result.kitsSpawned", { count: result.kits_spawned })}
              {result.kits_removed > 0 &&
                t("common.dotSeparator") +
                  t("data.result.kitsRemoved", { count: result.kits_removed })}
              {result.kits_advanced > 0 &&
                t("common.dotSeparator") +
                  t("data.result.kitsAdvanced", { count: result.kits_advanced })}
            </p>
          </div>
        )}
      </Card>
    </div>
  );
}
