import { useQueryClient } from "@tanstack/react-query";
import { FileText, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, ApiError, downloadFile } from "../../api/client";
import type { ImportMode, ImportPlan, ImportResult } from "../../api/types";
import { IMPORT_MODES } from "../../api/types";
import { ImportPreview } from "../../components/ImportPreview";
import { BAR_BUTTON_CLASS } from "../../components/Modal";
import { Button, Card, ErrorBanner, Select } from "../../components/ui";
import { formatFileSize } from "../../lib/format";
import { counted, importTableLabel } from "../../lib/labels";
import { useShell } from "../../lib/shell";
import { SectionHeader } from "./SectionHeader";

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

/** The import modes a phone offers (design §13.7, #304, the owner's call):
 *  `replace_all` — the one destructive action in the app — never sits a
 *  thumb's width from a mis-tap, and the move it would serve does not need it:
 *  merging an archive into an empty instance restores it whole (the golden
 *  archive's round trip, `test_golden_archive.py`). */
const PHONE_IMPORT_MODES: readonly ImportMode[] = ["merge", "add_only"];

/** Focus keys (`lib/focusKey.ts`): every control here that the two shapes
 *  below draw differently, or in different places, or only one of them draws. */
const FOCUS = {
  file: "import-file",
  mode: "import-mode",
  preview: "import-preview",
  apply: "import-apply",
  cancel: "import-cancel",
  starter: "data-starter-sheet",
} as const;

/** Data management in two shapes (design §13.7). From 768 px: Export, the
 *  blank templates, and Import with a drop zone, a mode `<select>` and its
 *  actions under the preview. On a phone (#304), for someone carrying an
 *  archive from plamotrack-ios to their own server: Export, then Import — a
 *  button for the picker instead of a drop zone, Merge and Add only as two
 *  segments, Apply and Cancel in a bar held above the tab bar while the import
 *  is on screen — then the starter sheet alone, the one blank template a phone
 *  might fill in (in Numbers, say); the full pack stays on the wider shapes.
 *  The line is the shell's, by width, not a touch screen's: an iPad is a fair
 *  place to import from, `replace_all` included. The import's state is held
 *  here, above both shapes, so a tablet turned to 744 px and back finds its
 *  file and its preview where it left them — unless it was replacing
 *  everything, which a phone does not offer: then the mode falls back to Merge
 *  and the preview goes, so no Apply can run a plan the phone cannot show. */
export function DataSection() {
  const { t } = useTranslation();
  const phone = useShell() === "phone";
  const queryClient = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);

  const [file, setFile] = useState<File | null>(null);
  const [mode, setMode] = useState<ImportMode>("merge");
  const [plan, setPlan] = useState<ImportPlan | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [confirmText, setConfirmText] = useState("");
  const [busy, setBusy] = useState<"preview" | "apply" | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The import's own failures, said inside its card rather than at the head of
  // the section: on a phone the head is a screen above Preview and the bar, and
  // a refused file looked like a tap that did nothing (#304, in the simulator).
  const [importError, setImportError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  // Adjusted while rendering, not in an effect, so the phone never draws a
  // frame with no segment pressed and a `replace_all` plan under it.
  if (phone && mode === "replace_all") {
    setMode("merge");
    setPlan(null);
    setResult(null);
    setConfirmText("");
  }

  function reset() {
    setFile(null);
    setPlan(null);
    setResult(null);
    setConfirmText("");
    setError(null);
    setImportError(null);
    if (fileInput.current) fileInput.current.value = "";
  }

  function pickFile(next: File | null) {
    setFile(next);
    // Any change invalidates the preview — never let an Apply run against a plan
    // the user is no longer looking at.
    setPlan(null);
    setResult(null);
    setImportError(null);
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
    setImportError(null);
    setResult(null);
    try {
      setPlan(await api.previewImport(file, mode));
    } catch (err) {
      setPlan(null);
      setImportError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  async function runApply() {
    if (!file || !plan) return;
    setBusy("apply");
    setImportError(null);
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
      setImportError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  function chooseMode(next: ImportMode) {
    setMode(next);
    setPlan(null);
    setResult(null);
    setImportError(null);
  }

  const blocked = (plan?.blocking_errors.length ?? 0) > 0;
  const needsConfirm = mode === "replace_all" && confirmText.trim().toUpperCase() !== "REPLACE";

  // Each drawn in one place per shape; the key hands the keyboard across.
  const applyButton = (className = "") => (
    <Button
      onClick={runApply}
      disabled={blocked || needsConfirm || busy !== null}
      data-focus-key={FOCUS.apply}
      className={className}
    >
      {busy === "apply" ? t("data.importing") : t("data.applyImport")}
    </Button>
  );
  const cancelButton = (className = "") => (
    <Button
      variant="secondary"
      onClick={reset}
      disabled={busy !== null}
      data-focus-key={FOCUS.cancel}
      className={className}
    >
      {t("common.cancel")}
    </Button>
  );
  const starterSheetButton = (
    <Button
      variant="secondary"
      data-focus-key={FOCUS.starter}
      onClick={() => download("/export/starter-sheet.csv", "plamotrack-starter-sheet.csv")}
    >
      {t("data.starterSheetButton")}
    </Button>
  );

  return (
    <div className="space-y-6">
      <SectionHeader title={t("settings.sections.data")} description={t("data.subtitle")} />

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

      {!phone && (
        <Card title={t("data.templatesTitle")} description={t("data.templatesDescription")}>
          <div className="flex flex-wrap gap-2">
            {starterSheetButton}
            {/* The phone has the starter sheet alone: this hands the keyboard there. */}
            <Button
              variant="secondary"
              data-focus-stand-in={FOCUS.starter}
              onClick={() => download("/export/templates", "plamotrack-templates.zip")}
            >
              {t("data.templatePackButton")}
            </Button>
          </div>
          <p className="mt-2 text-xs text-muted">{t("data.starterBlurb")}</p>
        </Card>
      )}

      {/* The phone's action bar is held above the tab bar while this box is on
          screen, so it is the Import card and the bar together. */}
      <div>
        <Card title={t("data.importTitle")} description={t("data.importDescription")}>
          <input
            ref={fileInput}
            type="file"
            accept=".csv,.zip,text/csv,application/zip"
            onChange={(event) => pickFile(event.target.files?.[0] ?? null)}
            className="hidden"
            id="import-file"
          />
          {phone ? (
            file ? (
              <div className="flex items-center gap-3 rounded-md border border-border bg-surface-alt py-1.5 ps-3 pe-1.5">
                <FileText size={20} aria-hidden className="shrink-0 text-faint" />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-text">{file.name}</p>
                  <p className="text-xs text-muted">{formatFileSize(file.size)}</p>
                </div>
                <Button
                  variant="secondary"
                  data-focus-key={FOCUS.file}
                  onClick={() => fileInput.current?.click()}
                  disabled={busy !== null}
                  className="shrink-0"
                >
                  {t("data.changeFile")}
                </Button>
              </div>
            ) : (
              <div>
                <Button
                  variant="secondary"
                  icon={Upload}
                  data-focus-key={FOCUS.file}
                  onClick={() => fileInput.current?.click()}
                  className="w-full justify-center"
                >
                  {t("data.chooseFile")}
                </Button>
                <p className="mt-1.5 text-xs text-muted">{t("data.chooseFileHint")}</p>
              </div>
            )
          ) : (
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
              className={`rounded-md border border-dashed px-4 py-6 text-center ${
                dragging ? "border-accent bg-accent-soft" : "border-border-strong bg-surface-alt"
              }`}
            >
              {file ? (
                <div className="space-y-1">
                  <p className="text-sm font-medium text-text">{file.name}</p>
                  <p className="text-xs text-muted">{formatFileSize(file.size)}</p>
                  <button
                    type="button"
                    onClick={reset}
                    data-focus-key={FOCUS.file}
                    className="text-xs text-accent hover:underline"
                  >
                    {t("data.chooseDifferent")}
                  </button>
                </div>
              ) : (
                <div className="space-y-1">
                  <p className="text-sm text-muted">{t("data.dropHere")}</p>
                  {/* A button, not a `<label>` for the hidden input: a label
                      takes no focus, and the input is `display: none`. */}
                  <button
                    type="button"
                    onClick={() => fileInput.current?.click()}
                    data-focus-key={FOCUS.file}
                    className="text-xs text-accent hover:underline"
                  >
                    {t("data.browse")}
                  </button>
                </div>
              )}
            </div>
          )}

          <div className="mt-3 flex flex-wrap items-end gap-3 max-md:flex-col max-md:items-stretch">
            {phone ? (
              // `min-w-0`: a fieldset's own minimum is its content's, which
              // widened the page under a large browser font.
              <fieldset className="min-w-0">
                <legend className="mb-1 text-xs font-medium text-muted">{t("data.modeLabel")}</legend>
                <div className="grid grid-cols-2 gap-2">
                  {PHONE_IMPORT_MODES.map((option) => (
                    <label
                      key={option}
                      className="flex min-h-11 cursor-pointer items-center justify-center rounded-sm border border-border-strong px-2 py-1.5 text-center text-sm font-medium text-text wrap-anywhere has-checked:border-accent has-checked:bg-accent-soft has-checked:text-accent has-focus-visible:outline-2 has-focus-visible:outline-accent"
                    >
                      <input
                        type="radio"
                        name="import-mode"
                        value={option}
                        checked={mode === option}
                        onChange={() => chooseMode(option)}
                        data-focus-key={mode === option ? FOCUS.mode : undefined}
                        className="sr-only"
                      />
                      {t(`importMode.${option}.label`)}
                    </label>
                  ))}
                </div>
              </fieldset>
            ) : (
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-muted">
                  {t("data.modeLabel")}
                </span>
                <Select
                  value={mode}
                  onChange={(event) => chooseMode(event.target.value as ImportMode)}
                  data-focus-key={FOCUS.mode}
                  className="w-56"
                >
                  {IMPORT_MODES.map((option) => (
                    <option key={option} value={option}>
                      {t(`importMode.${option}.label`)}
                    </option>
                  ))}
                </Select>
              </label>
            )}
            <Button
              onClick={runPreview}
              disabled={!file || busy !== null}
              data-focus-key={FOCUS.preview}
              className="max-md:justify-center"
            >
              {busy === "preview" ? t("data.reading") : t("data.previewChanges")}
            </Button>
          </div>
          <p className="mt-1.5 text-xs text-muted">{t(`importMode.${mode}.blurb`)}</p>

          {plan && (
            <div className="mt-4 space-y-3">
              <ImportPreview plan={plan} />

              {mode === "replace_all" && !blocked && (
                <label
                  data-focus-stand-in={FOCUS.mode}
                  className="block rounded-sm border border-danger/40 bg-danger/10 px-3 py-2"
                >
                  <span className="mb-1 block text-xs font-medium text-danger">
                    {t("data.replaceConfirm")}
                  </span>
                  <input
                    value={confirmText}
                    onChange={(event) => setConfirmText(event.target.value)}
                    placeholder="REPLACE"
                    className="w-40 rounded-sm border border-danger/40 bg-surface px-2.5 py-1.5 text-sm text-text focus:border-danger focus:outline-none"
                  />
                </label>
              )}

              {/* Gone on a phone, which draws them in the bar below; a turn
                  with a `replace_all` plan takes the plan too, so then the
                  mode stands in for them. */}
              {!phone && (
                <div data-focus-stand-in={FOCUS.mode} className="flex items-center gap-2">
                  {applyButton()}
                  {cancelButton()}
                </div>
              )}
            </div>
          )}

          {/* Last in the card: under Preview when a preview is refused, and
              just above Apply — the phone's bar — when an apply is. */}
          {importError && (
            <div className="mt-3">
              <ErrorBanner message={importError} />
            </div>
          )}

          {result && (
            <div className="mt-4 rounded-sm border border-status-complete/40 bg-status-complete/10 px-3 py-2 text-sm text-status-complete">
              <p className="font-medium">{t("data.complete")}</p>
              <p className="mt-0.5">
                {t("data.result.created", counted({}, result.created))}
                {t("common.dotSeparator")}
                {t("data.result.updated", counted({}, result.updated))}
                {t("common.dotSeparator")}
                {t("data.result.skipped", counted({}, result.skipped))}
                {result.kits_spawned > 0 &&
                  t("common.dotSeparator") +
                    t("data.result.kitsSpawned", counted({}, result.kits_spawned))}
                {result.kits_removed > 0 &&
                  t("common.dotSeparator") +
                    t("data.result.kitsRemoved", counted({}, result.kits_removed))}
                {result.kits_advanced > 0 &&
                  t("common.dotSeparator") +
                    t("data.result.kitsAdvanced", counted({}, result.kits_advanced))}
              </p>
            </div>
          )}
        </Card>

        {/* A dialog's bar (`Modal`), on the page: held at the foot of the
            screen — above the tab bar, whose height is `TAB_CLASS`'s 3.5rem
            and the home indicator's inset — while the import is on screen, so
            Apply is never a long preview's scroll away; at rest under the
            card. The width of `main`, its gutters included, so nothing scrolls
            past beside it. */}
        {phone && plan && (
          <div className="sticky bottom-[calc(3.5rem+env(safe-area-inset-bottom))] z-20 -mx-4 mt-3 grid grid-cols-[minmax(0,1fr)_minmax(0,2fr)] gap-2.5 border-t border-rule bg-surface px-4 py-3">
            {cancelButton(BAR_BUTTON_CLASS)}
            {applyButton(BAR_BUTTON_CLASS)}
          </div>
        )}
      </div>

      {phone && (
        <Card title={t("data.templatesTitle")} description={t("data.templatesDescription")}>
          {starterSheetButton}
          <p className="mt-2 text-xs text-muted">{t("data.starterBlurbPhone")}</p>
        </Card>
      )}
    </div>
  );
}
