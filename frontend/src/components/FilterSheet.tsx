import type { ReactNode } from "react";
import { SlidersHorizontal } from "lucide-react";
import { useId } from "react";
import { useTranslation } from "react-i18next";

import { formatNumber } from "../lib/format";
import { countedPhrase } from "../lib/labels";
import { Modal } from "./Modal";
import { MICRO_LABEL_CLASS } from "./ui";

/** Where the keyboard goes when the filter sheet closes (`Modal`'s
 *  `restoreFocus`): the control that opened it — or, if the screen was turned
 *  past 768 px while it was open and that control is gone, the first of the
 *  inline filters that stand where it stood. Both carry this `data-focus-key`. */
export const FILTERS_FOCUS = "list-filters";

/** The phone's one control for everything but the search (§13.7): it opens the
 *  filter sheet and says how many filters are narrowing the list — a sort is an
 *  order, not a filter, and is not counted. 44 px, beside the search box. */
export function FilterSheetButton({ active, onClick }: { active: number; onClick: () => void }) {
  const { t } = useTranslation();
  const label =
    active > 0 ? countedPhrase("list.filterAndSortActive", active) : t("list.filterAndSort");
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      data-focus-key={FILTERS_FOCUS}
      className="relative inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-sm border border-border-strong bg-surface text-text hover:bg-chip focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
    >
      <SlidersHorizontal size={18} aria-hidden />
      {active > 0 && (
        <span
          aria-hidden
          className="absolute -end-1.5 -top-1.5 inline-flex h-4.5 min-w-4.5 items-center justify-center rounded-full bg-accent px-1 text-[11px] font-semibold tabular-nums text-accent-ink"
        >
          {formatNumber(active)}
        </span>
      )}
    </button>
  );
}

/** The filter sheet (§13.7): every filter but the search, and the sort, in one
 *  bottom sheet. It edits a draft — nothing reaches the URL until the primary
 *  button, which says what it will show; *Clear* empties the draft, and closing
 *  any other way leaves the list as it was. The caller owns the draft and
 *  writes it in one navigation (`useWriteParams`), so the sheet's result is the
 *  same `?status=…&sort=…` a *view all* link and a bookmark carry (§13.4). */
export function FilterSheet({
  applyLabel,
  onApply,
  onClear,
  onClose,
  children,
}: {
  /** "Show 5 kits" — the count the draft would leave, from the page's own filter. */
  applyLabel: string;
  onApply: () => void;
  onClear: () => void;
  onClose: () => void;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  // The two buttons are the sheet's own action bar (#259): *Clear* the secondary,
  // the primary the submit of this form, which it stands outside of.
  const formId = useId();
  return (
    <Modal
      sheet
      title={t("list.filterAndSort")}
      onClose={onClose}
      actions={{
        secondary: { label: t("list.clearFilters"), onClick: onClear },
        primary: { label: applyLabel, form: formId },
      }}
    >
      <form
        id={formId}
        className="space-y-5"
        onSubmit={(event) => {
          event.preventDefault();
          onApply();
        }}
      >
        {children}
      </form>
    </Modal>
  );
}

/** One group of the sheet under its micro-label, which names the group. */
export function SheetSection({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div role="group" aria-label={label} className="space-y-2.5">
      <h3 className={MICRO_LABEL_CLASS}>{label}</h3>
      {children}
    </div>
  );
}

/** The status toggles: one of them pressed, two to a row, each with its dot in
 *  the pipeline's colour and how many the collection holds (`GET /summary`). */
export function ToggleGrid({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-2 gap-2">{children}</div>;
}

export function ToggleOption({
  pressed,
  onClick,
  tone,
  count,
  children,
}: {
  pressed: boolean;
  onClick: () => void;
  /** `text-status-*`, for the dot; none on "All statuses". */
  tone?: string;
  count?: number;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onClick}
      className={`flex h-11 items-center gap-2 rounded-sm border px-3 text-sm font-medium text-text focus:outline-none focus:ring-1 focus:ring-accent ${
        pressed ? "border-accent bg-accent-soft" : "border-border-strong hover:bg-chip"
      }`}
    >
      {tone && <i aria-hidden className={`h-1.5 w-1.5 shrink-0 rounded-full bg-current ${tone}`} />}
      <span className="min-w-0 flex-1 truncate text-start">{children}</span>{" "}
      {count !== undefined && (
        <span className="text-[12.5px] font-normal tabular-nums text-muted">{formatNumber(count)}</span>
      )}
    </button>
  );
}

/** The sort, as a segmented control: every choice on screen, one pressed. */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
}: {
  options: readonly { value: T; label: string }[];
  value: T;
  onChange: (next: T) => void;
}) {
  return (
    // Equal columns from the flow, not an inline `style`: the packaged stack's
    // CSP is `style-src 'self'`, and nothing in `src/` sets one.
    <div className="grid auto-cols-fr grid-flow-col gap-0.5 rounded-sm border border-border bg-surface-alt p-[3px]">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={option.value === value}
          onClick={() => onChange(option.value)}
          className={`flex h-11 items-center justify-center rounded-sm px-1 text-[13.5px] font-medium focus:outline-none focus:ring-1 focus:ring-accent ${
            option.value === value ? "bg-chip text-text" : "text-muted hover:text-text"
          }`}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
