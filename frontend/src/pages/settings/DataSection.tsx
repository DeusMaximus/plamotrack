import { useQueryClient } from "@tanstack/react-query";
import { FileText, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, ApiError, downloadFile } from "../../api/client";
import type { ImportMode, ImportPlan } from "../../api/types";
import { IMPORT_MODES } from "../../api/types";
import { ImportPreview } from "../../components/ImportPreview";
import { BAR_BUTTON_CLASS } from "../../components/Modal";
import { Button, Card, ErrorBanner, Select } from "../../components/ui";
import { focusByKey } from "../../lib/focusKey";
import type { ImportOutcome } from "../../lib/importRun";
import { acknowledgeImportOutcome, importRunState, sendImport, watchImportRun } from "../../lib/importRun";
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
  pending: "import-pending",
  starter: "data-starter-sheet",
} as const;

/** The keyboard has nowhere: on `<body>`, or on a control that has just been
 *  disabled under it (`:disabled`, so one a `<fieldset>` disables counts too). */
function keyboardLost(): boolean {
  const active = document.activeElement;
  return active === null || active === document.body || active.matches(":disabled");
}

/** Give an element the keyboard and bring it into view — only the nearest
 *  scroll, and clear of what is sticky over the page on a phone (the scroll
 *  margins on the element itself). `preventScroll` alone left a pending import
 *  focused 1,100 px below a long preview (#314 round 4, Codex finding 10). */
function reveal(element: HTMLElement | null) {
  if (!element) return;
  element.focus({ preventScroll: true });
  element.scrollIntoView({ block: "nearest" });
}

/** Room for what sits over the page on a phone when something is revealed: the
 *  sticky head (`PageHeader`'s 3.5rem) above; below, the tab bar (3.5rem) and
 *  the import's own bar (a 3rem button in 1.5rem of padding), and the inset. */
const REVEAL_MARGINS = "max-md:scroll-mt-16 max-md:scroll-mb-[calc(8rem+env(safe-area-inset-bottom))]";

/** Data management in two shapes (design §13.7). From 768 px: Export, the
 *  blank templates, and Import with a drop zone, a mode `<select>` and its
 *  actions under the preview. On a phone (#304), for someone carrying an
 *  archive from plamotrack-ios to their own server: Export, then Import — a
 *  button for the picker instead of a drop zone, Merge and Add only as two
 *  segments, Apply and Cancel in a bar held above the tab bar while the import
 *  is on screen — then the starter sheet alone, the one blank template a phone
 *  might fill in (in Numbers, say); the full pack stays on the wider shapes.
 *  The line is the shell's, by width, not a touch screen's: an iPad is a fair
 *  place to import from, `replace_all` included. The import's draft is held
 *  here, above both shapes, so a tablet turned to 744 px and back finds its
 *  file and its preview where it left them — unless it was replacing
 *  everything, which a phone does not offer: then the mode falls back to Merge
 *  and the preview goes, so no Apply can run a plan the phone cannot show. An
 *  import once sent is held above the routes instead (`lib/importRun.ts`,
 *  #315): leaving the section does not stop it, and must not lose it. */
export function DataSection() {
  const { t } = useTranslation();
  const phone = useShell() === "phone";
  const queryClient = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);

  const [file, setFile] = useState<File | null>(null);
  const [mode, setMode] = useState<ImportMode>("merge");
  const [plan, setPlan] = useState<ImportPlan | null>(null);
  // How the sent import ended — the operation's, not the draft's, and the
  // module's until this section has painted it (`importRun`, #315). The
  // section starts from it, so one sent before the section was left is drawn
  // from the first frame. It is one state, and the result and the apply's
  // failure below are read from it, so what is drawn and what is acknowledged
  // as painted cannot part: kept as three, the phone's fall-back cleared the
  // drawn result and left the acknowledged copy, which then forgot an outcome
  // never on screen (PR #332 round 2, Codex finding 2). Someone's own move on
  // the draft dismisses it — another file, another mode, Cancel, a preview;
  // the fall-back throws the draft away under it and leaves it be.
  const [outcome, setOutcome] = useState<ImportOutcome | null>(() => importRunState().outcome);
  const result = outcome && "result" in outcome ? outcome.result : null;
  const [confirmText, setConfirmText] = useState("");
  const [busy, setBusy] = useState<"preview" | null>(null);
  // The import that has been sent, by the mode it was sent with — the
  // operation's, not the draft's. The draft (file, mode, plan) can still be
  // thrown away under it, by the phone's fall-back, and an import that has
  // reached the server is not stopped by that: the page keeps saying it is
  // under way, and what it is, until it answers (#314 round 2, Codex finding 5).
  // Nor by leaving: a section mounted under it says the same (#315).
  const [submitted, setSubmitted] = useState<ImportMode | null>(() => importRunState().pending);
  // A download's failure, and the card whose button failed, where it is said
  // (#316): at the section's head, a phone put the starter sheet's a screen
  // above its button, the last card on the page.
  const [downloadError, setDownloadError] = useState<{ card: "export" | "templates"; message: string } | null>(null);
  // A preview's refusal: the draft's, so it goes with the draft. With the
  // apply's failure it is the import's own failures, said inside its card
  // rather than at the head of the section: on a phone the head is a screen
  // above Preview and the bar, and a refused file looked like a tap that did
  // nothing (#304, in the simulator).
  const [refusal, setRefusal] = useState<string | null>(null);
  const importError = refusal ?? (outcome && "error" in outcome ? outcome.error : null);
  // Previewing, or an import under way: either holds every control that would
  // change the draft, and an import under way holds Preview and Apply too.
  const working = busy !== null || submitted !== null;
  const [dragging, setDragging] = useState(false);
  // Which preview is the current one. Everything that throws a plan away —
  // another file, another mode, Cancel, the phone's fall-back from
  // `replace_all` — moves it on, and a preview that answers under an older
  // number is dropped: one still in flight would otherwise put back the plan it
  // was asked for, under a mode or a file the page no longer shows, and Apply
  // would send that plan's hash with the new mode (#314 review: Greptile P1,
  // Codex P2).
  const previewSeq = useRef(0);

  // Adjusted while rendering, not in an effect, so the phone never draws a
  // frame with no segment pressed and a `replace_all` plan under it. The
  // counter is moved on here too, a ref written during render: it is only ever
  // compared for inequality, so a render React repeats moves it twice to no
  // effect.
  if (phone && mode === "replace_all") {
    previewSeq.current += 1;
    setMode("merge");
    setPlan(null);
    setConfirmText("");
    setRefusal(null);
  }

  function reset() {
    previewSeq.current += 1;
    setFile(null);
    setPlan(null);
    setOutcome(null);
    setConfirmText("");
    setRefusal(null);
    if (fileInput.current) fileInput.current.value = "";
  }

  function pickFile(next: File | null) {
    previewSeq.current += 1;
    if (outcomeRef.current?.contains(document.activeElement)) outcomeReplaced.current = true;
    setFile(next);
    // Any change invalidates the preview — never let an Apply run against a plan
    // the user is no longer looking at.
    setPlan(null);
    setOutcome(null);
    setRefusal(null);
  }

  async function download(path: string, name: string, card: "export" | "templates") {
    setDownloadError(null);
    try {
      await downloadFile(path, name);
    } catch (err) {
      setDownloadError({ card, message: err instanceof ApiError ? err.message : String(err) });
    }
  }
  const downloadFailure = (card: "export" | "templates") =>
    downloadError?.card === card && (
      <div className="mt-3">
        <ErrorBanner reveal message={downloadError.message} />
      </div>
    );

  async function runPreview() {
    if (!file) return;
    const asked = ++previewSeq.current;
    setBusy("preview");
    setRefusal(null);
    setOutcome(null);
    try {
      const planned = await api.previewImport(file, mode);
      if (asked === previewSeq.current) setPlan(planned);
    } catch (err) {
      if (asked !== previewSeq.current) return;
      setPlan(null);
      setRefusal(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  /** The picker, opened with the input emptied first: a file input whose value
   *  is already that path fires no `change` when the same file is picked again —
   *  a fresh export of the same name, a CSV edited and saved — and the old
   *  preview stayed (#314 review, Codex P2). The file the page holds is React's,
   *  so a cancelled pick loses nothing. */
  function openPicker() {
    if (fileInput.current) {
      fileInput.current.value = "";
      fileInput.current.click();
    }
  }

  function runApply() {
    if (!file || !plan) return;
    const sent = sendImport(
      mode,
      () =>
        api.applyImport(
          file,
          mode,
          plan.plan_hash,
          mode === "replace_all" ? confirmText.trim().toUpperCase() : undefined,
        ),
      () => queryClient.invalidateQueries(),
    );
    if (!sent) return;
    setSubmitted(mode);
    setRefusal(null);
    // The import sent replaces the last one's outcome — a failure left beside
    // "Importing…" read as this one's (PR #332 round 3, Codex finding 4). Only
    // once it is sent: a send refused as a duplicate dismisses nothing.
    setOutcome(null);
  }

  // The sent phase ends on the answer, in one commit with what it brought: the
  // result, and a draft emptied for the next file — told in the tick the
  // answer comes, so these are batched as one. Refreshing the rest of the
  // app's data comes after and is not part of it — awaited inside it, the page
  // said "Importing…" beside "Import complete" with the pickers enabled (#314
  // round 3, Codex finding 9). A section mounted after the answer is handed it
  // here at once; its draft is empty already.
  useEffect(
    () =>
      watchImportRun((ended) => {
        setSubmitted(null);
        setOutcome(ended);
        if (ended === null || "error" in ended) return;
        setPlan(null);
        setFile(null);
        setConfirmText("");
        if (fileInput.current) fileInput.current.value = "";
      }),
    [],
  );

  // The outcome drawn is the outcome acknowledged, two frames after it was
  // committed: then the module forgets it, and not before. A section told of
  // it while it is torn down never commits it (PR #332 round 1), and one that
  // dismisses or loses it first cancels the frames; either way it waits for
  // the next visit.
  useEffect(() => {
    if (!outcome) return;
    let frame = requestAnimationFrame(() => {
      frame = requestAnimationFrame(() => acknowledgeImportOutcome(outcome));
    });
    return () => cancelAnimationFrame(frame);
  }, [outcome]);

  // A sent import has somewhere to keep the keyboard (#314 round 3, Codex
  // finding 8). Sending it disables Apply, and Chromium then drops the focus a
  // keyboard put there; the controls that would stand in for it — the mode —
  // are disabled for the same reason. So while it runs the keyboard is given
  // to its status, which carries a key of its own and is what every pending
  // control names as its last stand-in; when it answers, to the outcome. Only
  // where nothing else has the keyboard: someone who moved on keeps their place.
  const pendingRef = useRef<HTMLParagraphElement>(null);
  const outcomeRef = useRef<HTMLDivElement>(null);
  // Moments, not states: a section mounted under an import already sent, or
  // over one already answered, takes nobody's keyboard (#315).
  const wasSubmitted = useRef(submitted !== null);
  useEffect(() => {
    const was = wasSubmitted.current;
    wasSubmitted.current = submitted !== null;
    if (submitted !== null && !was) {
      if (keyboardLost()) reveal(pendingRef.current);
    } else if (submitted === null && was) {
      if (keyboardLost()) reveal(outcomeRef.current);
    }
  }, [submitted]);

  // A preview has the same two moments (#314 round 4, already so on `main`):
  // Preview disables itself while it reads, and Chromium drops the keyboard a
  // just-disabled button held. When it answers, the keyboard goes to a refusal,
  // or back to Preview.
  const previewWas = useRef(busy);
  useEffect(() => {
    const was = previewWas.current;
    previewWas.current = busy;
    if (was !== "preview" || busy !== null || !keyboardLost()) return;
    if (refusal) reveal(outcomeRef.current);
    else focusByKey(FOCUS.preview);
  }, [busy, refusal]);

  // An outcome holding the keyboard and replaced by the next file — dropped onto
  // the drop zone, which moves no focus of its own — hands it to that file's
  // Preview (#314 round 4, Codex finding 11).
  const outcomeReplaced = useRef(false);
  useEffect(() => {
    if (!outcomeReplaced.current) return;
    outcomeReplaced.current = false;
    if (keyboardLost()) focusByKey(FOCUS.preview);
  }, [file]);

  function chooseMode(next: ImportMode) {
    previewSeq.current += 1;
    setMode(next);
    setPlan(null);
    setOutcome(null);
    setRefusal(null);
  }

  const blocked = (plan?.blocking_errors.length ?? 0) > 0;
  const needsConfirm = mode === "replace_all" && confirmText.trim().toUpperCase() !== "REPLACE";

  // Each drawn in one place per shape; the key hands the keyboard across.
  const applyButton = (className = "") => (
    <Button
      onClick={runApply}
      disabled={blocked || needsConfirm || working}
      data-focus-key={FOCUS.apply}
      className={className}
    >
      {submitted !== null ? t("data.importing") : t("data.applyImport")}
    </Button>
  );
  const cancelButton = (className = "") => (
    <Button
      variant="secondary"
      onClick={reset}
      disabled={working}
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
      onClick={() => download("/export/starter-sheet.csv", "plamotrack-starter-sheet.csv", "templates")}
    >
      {t("data.starterSheetButton")}
    </Button>
  );

  return (
    <div className="space-y-6">
      <SectionHeader title={t("settings.sections.data")} description={t("data.subtitle")} />

      <Card title={t("data.exportTitle")} description={t("data.exportDescription")}>
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => download("/export/archive", "plamotrack-export.zip", "export")}>
            {t("data.archiveButton")}
          </Button>
          {TABLE_EXPORTS.map((table) => (
            <Button
              key={table}
              variant="secondary"
              onClick={() => download(`/export/${table}.csv`, `${table}.csv`, "export")}
            >
              {importTableLabel(table)} .csv
            </Button>
          ))}
        </div>
        {downloadFailure("export")}
      </Card>

      {!phone && (
        <Card title={t("data.templatesTitle")} description={t("data.templatesDescription")}>
          <div className="flex flex-wrap gap-2">
            {starterSheetButton}
            {/* The phone has the starter sheet alone: this hands the keyboard there. */}
            <Button
              variant="secondary"
              data-focus-stand-in={FOCUS.starter}
              onClick={() => download("/export/templates", "plamotrack-templates.zip", "templates")}
            >
              {t("data.templatePackButton")}
            </Button>
          </div>
          <p className="mt-2 text-xs text-muted">{t("data.starterBlurb")}</p>
          {downloadFailure("templates")}
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
            // A pick with no file in it — a cancel, where an engine reports one —
            // keeps the file already chosen.
            onChange={(event) => {
              const next = event.target.files?.[0];
              if (next) pickFile(next);
            }}
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
                  onClick={openPicker}
                  disabled={working}
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
                  onClick={openPicker}
                  disabled={working}
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
                if (!working) pickFile(event.dataTransfer.files[0] ?? null);
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
                    disabled={working}
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
                    onClick={openPicker}
                    disabled={working}
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
              <fieldset className="min-w-0" disabled={submitted !== null}>
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
                  disabled={submitted !== null}
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
              disabled={!file || working}
              data-focus-key={FOCUS.preview}
              className="max-md:justify-center"
            >
              {busy === "preview" ? t("data.reading") : t("data.previewChanges")}
            </Button>
          </div>
          <p className="mt-1.5 text-xs text-muted">{t(`importMode.${mode}.blurb`)}</p>

          {/* The actions stay while an import is under way even when its plan
              has gone with the draft — they say "Importing…" — so this box is
              drawn for either. */}
          {(plan || submitted) && (
            <div className="mt-4 space-y-3">
              {plan && <ImportPreview plan={plan} />}

              {plan && mode === "replace_all" && !blocked && (
                <label
                  data-focus-stand-in={`${FOCUS.mode} ${FOCUS.pending}`}
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
                <div data-focus-stand-in={`${FOCUS.mode} ${FOCUS.pending}`} className="flex items-center gap-2">
                  {applyButton()}
                  {cancelButton()}
                </div>
              )}
            </div>
          )}

          {submitted && (
            <p
              ref={pendingRef}
              role="status"
              tabIndex={-1}
              data-focus-key={FOCUS.pending}
              className={`mt-3 text-sm text-muted ${REVEAL_MARGINS}`}
            >
              {t("data.applying", { mode: t(`importMode.${submitted}.label`) })}
            </p>
          )}

          {/* Last in the card: under Preview when a preview is refused, and
              just above Apply — the phone's bar — when an apply is. */}
          {importError && (
            <div ref={outcomeRef} tabIndex={-1} className={`mt-3 ${REVEAL_MARGINS}`}>
              <ErrorBanner message={importError} />
            </div>
          )}

          {result && (
            <div
              ref={outcomeRef}
              tabIndex={-1}
              className={`mt-4 ${REVEAL_MARGINS} rounded-sm border border-status-complete/40 bg-status-complete/10 px-3 py-2 text-sm text-status-complete`}>
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
        {phone && (plan || submitted) && (
          <div
            data-focus-stand-in={FOCUS.pending}
            className="sticky bottom-[calc(3.5rem+env(safe-area-inset-bottom))] z-20 -mx-4 mt-3 grid grid-cols-[minmax(0,1fr)_minmax(0,2fr)] gap-2.5 border-t border-rule bg-surface px-4 py-3">
            {cancelButton(BAR_BUTTON_CLASS)}
            {applyButton(BAR_BUTTON_CLASS)}
          </div>
        )}
      </div>

      {phone && (
        <Card title={t("data.templatesTitle")} description={t("data.templatesDescription")}>
          {starterSheetButton}
          <p className="mt-2 text-xs text-muted">{t("data.starterBlurbPhone")}</p>
          {downloadFailure("templates")}
        </Card>
      )}
    </div>
  );
}
