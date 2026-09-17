import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from "react";
import { Star, type LucideIcon } from "lucide-react";
import { forwardRef } from "react";
import { useTranslation } from "react-i18next";

import { formatNumber } from "../lib/format";
import { pageWindow, type Paged } from "../lib/listState";
import { useShell } from "../lib/shell";
import { BrandMark } from "./BrandMark";

const BUTTON_VARIANTS = {
  primary: "bg-accent text-accent-ink hover:opacity-90 disabled:opacity-50",
  secondary:
    "border border-border-strong bg-transparent text-text hover:bg-chip disabled:text-faint",
  danger: "border border-danger/40 bg-transparent text-danger hover:bg-danger/10 disabled:opacity-50",
} as const;

export function Button({
  variant = "primary",
  icon: Icon,
  className = "",
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: keyof typeof BUTTON_VARIANTS;
  /** A leading stroke icon (§13): the label stays the accessible name. */
  icon?: LucideIcon;
}) {
  return (
    <button
      className={`inline-flex items-center gap-1.5 rounded-sm px-3 py-1.5 text-sm font-medium transition-colors disabled:cursor-not-allowed touch:min-h-10 ${BUTTON_VARIANTS[variant]} ${className}`}
      {...props}
    >
      {Icon && <Icon size={15} aria-hidden />}
      {children}
    </button>
  );
}

/** An icon-only control — a row's edit pencil, a dialog's close — named for
 *  assistive tech and the tooltip by `label`. Faint at rest (the 3:1 UI floor),
 *  the text colour on hover. 28 px for a mouse; the 44 px touch target under
 *  `touch:` (§13.7), the icon the same size inside it. */
export function IconButton({
  label,
  className = "",
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      className={`inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-sm text-faint transition-colors hover:bg-chip hover:text-text focus:outline-none focus:ring-1 focus:ring-accent touch:h-11 touch:w-11 ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}

// 16 px text in the phone shell: iOS Safari zooms the page when a control under
// 16 px takes focus, and never zooms back (§13.7). 44 px tall under `touch:`.
const CONTROL_CLASSES =
  "w-full rounded-sm border border-border-strong bg-surface px-2.5 py-1.5 text-sm text-text " +
  "placeholder:text-muted focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent " +
  "disabled:opacity-60 max-md:text-base touch:min-h-11";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className = "", ...props }, ref) {
    return <input ref={ref} className={`${CONTROL_CLASSES} ${className}`} {...props} />;
  },
);

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  function Select({ className = "", ...props }, ref) {
    return <select ref={ref} className={`${CONTROL_CLASSES} ${className}`} {...props} />;
  },
);

export const Textarea = forwardRef<
  HTMLTextAreaElement,
  TextareaHTMLAttributes<HTMLTextAreaElement>
>(function Textarea({ className = "", ...props }, ref) {
  return <textarea ref={ref} rows={3} className={`${CONTROL_CLASSES} ${className}`} {...props} />;
});

export function Field({
  label,
  required,
  error,
  children,
  className = "",
}: {
  label: string;
  required?: boolean;
  error?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <label className={`block ${className}`}>
      <span className="mb-1 block text-xs font-medium text-muted">
        {label}
        {required && <span className="text-danger"> *</span>}
      </span>
      {children}
      {error && <span className="mt-1 block text-xs text-danger">{error}</span>}
    </label>
  );
}

export function ErrorBanner({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div
      role="alert"
      className="rounded-sm border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger"
    >
      {message}
    </div>
  );
}

/** A titled panel. The heading is an h3 because every consumer sits under a
 *  page h1 and a section h2 (the Settings sections); a new consumer at a
 *  different depth should say so here rather than skip a level silently. */
export function Card({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-md border border-border bg-surface p-4">
      <h3 className="text-sm font-semibold text-text">{title}</h3>
      <p className="mt-0.5 text-xs text-muted">{description}</p>
      <div className="mt-3">{children}</div>
    </section>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-md border border-dashed border-border-strong px-6 py-10 text-center text-sm text-muted">
      {children}
    </div>
  );
}

/** A rating out of five as stroke stars, the given ones filled in the accent
 *  (§13: one icon set, no glyphs). Named for assistive tech by `title`. */
export function RatingStars({ rating, title }: { rating: number; title: string }) {
  return (
    <span role="img" aria-label={title} title={title} className="inline-flex items-center gap-px text-accent">
      {Array.from({ length: 5 }, (_, index) => (
        <Star
          key={index}
          size={14}
          aria-hidden
          fill={index < rating ? "currentColor" : "none"}
          className={index < rating ? "" : "text-faint"}
        />
      ))}
    </span>
  );
}

/** The page's h1 (§13): the name, semibold and tight, nothing louder — with
 *  the list's count beside it when the page is a list (§13.4). */
export function PageTitle({ children, count }: { children: ReactNode; count?: number }) {
  return (
    <h1 className="flex items-baseline gap-2.5 text-[22px] font-semibold tracking-tight text-text">
      {children}
      {count !== undefined && (
        <span className="text-[13px] font-medium tabular-nums text-muted">{formatNumber(count)}</span>
      )}
    </h1>
  );
}

/** The head of a page. From 768 px up it is what the pages always had: the
 *  title (and a list's count), with the page's actions at the far end. In the
 *  phone shell (§13.7) it is a bar across the top that stays while the page
 *  scrolls — the title, the count and the one primary action; `secondary`
 *  actions (Export CSV) are not on a phone, where Settings → Data management
 *  has them. `brand` is Home's: the sidebar that carried the wordmark is gone
 *  there, so the bar does, and the h1 stays for assistive tech.
 *
 *  One tree for both shapes, dressed differently: the primary action keeps its
 *  place — second child of the second child — so it is the same DOM node on
 *  both sides of the 768 px line. `Modal` gives focus back to the node that
 *  opened it, and a dialog can be open while a tablet is turned; when the two
 *  shapes were two subtrees the opener was replaced mid-dialog and the keyboard
 *  was left on <body> (Codex #265, finding 1).
 *
 *  The bar is full-bleed by undoing `main`'s phone gutter (Layout's `px-4`) —
 *  the two move together. A negative margin cannot undo an ancestor's
 *  max-width, so a page that caps its own content keeps this outside the cap
 *  (MorePage; finding 2). */
export function PageHeader({
  title,
  count,
  subtitle,
  brand = false,
  actions,
  secondary,
}: {
  title: string;
  count?: number;
  subtitle?: string;
  brand?: boolean;
  actions?: ReactNode;
  secondary?: ReactNode;
}) {
  const phone = useShell() === "phone";
  return (
    <>
      <header
        className={
          phone
            ? "sticky top-0 z-10 -mx-4 flex h-14 items-center justify-between gap-3 border-b border-rule bg-bg px-4"
            : "flex items-center justify-between gap-3"
        }
      >
        {phone && brand ? (
          // The wordmark is a brand identifier, not copy — it stays untranslated.
          <div className="flex items-center gap-2.5 text-[17px] font-semibold tracking-tight text-text">
            <BrandMark />
            <span>plamotrack</span>
            <h1 className="sr-only">{title}</h1>
          </div>
        ) : (
          <div>
            <PageTitle count={count}>{title}</PageTitle>
            {!phone && subtitle && <p className="mt-0.5 text-sm text-muted">{subtitle}</p>}
          </div>
        )}
        {(secondary || actions) && (
          <div className="flex gap-2">
            {!phone && secondary}
            {actions}
          </div>
        )}
      </header>
      {phone && subtitle && <p className="mt-3 text-sm text-muted">{subtitle}</p>}
    </>
  );
}

/** A list table's footer (§13.4): the range shown and, past one page, the
 *  pager — the ends and a window around the current page. The page is URL
 *  state, so the caller owns it. */
export function Pager({ paged, onPage }: { paged: Paged<unknown>; onPage: (page: number) => void }) {
  const { t } = useTranslation();
  return (
    <div className="flex items-center justify-between gap-4 border-t border-rule px-3.5 py-3 text-xs text-muted tabular-nums">
      <span>
        {t("list.range", {
          from: formatNumber(paged.from),
          to: formatNumber(paged.to),
          total: formatNumber(paged.total),
        })}
      </span>
      {paged.pages > 1 && (
        <nav aria-label={t("list.pagination")} className="flex items-center gap-1">
          {pageWindow(paged.page, paged.pages).map((page, index) =>
            page === null ? (
              <span key={`gap-${index}`} aria-hidden className="px-1 text-faint">
                …
              </span>
            ) : (
              <button
                key={page}
                type="button"
                aria-label={t("list.page", { page: formatNumber(page) })}
                aria-current={page === paged.page ? "page" : undefined}
                onClick={() => onPage(page)}
                className={`min-w-6.5 rounded-sm px-1.5 py-1 text-xs tabular-nums touch:min-h-11 touch:min-w-11 ${
                  page === paged.page
                    ? "bg-accent-soft font-semibold text-accent"
                    : "text-muted hover:bg-chip hover:text-text"
                }`}
              >
                {formatNumber(page)}
              </button>
            ),
          )}
        </nav>
      )}
    </div>
  );
}

/** Uppercase micro-label (§13): section labels, table headers, counts' captions. */
export const MICRO_LABEL_CLASS = "text-[11px] font-semibold uppercase tracking-[0.08em] text-muted";

/** The header row of every list table: micro-labels on the alternate surface,
 *  a hairline beneath. */
export const TABLE_HEAD_ROW_CLASS = `border-b border-border bg-surface-alt text-start ${MICRO_LABEL_CLASS}`;

/** A status chip (§13): a dot and a word in the status colour on the neutral
 *  chip ground — `text-status-*` (or `text-danger`) from the caller. */
export function Chip({
  tone,
  children,
  className = "",
  title,
}: {
  tone: string;
  children: ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-sm bg-chip px-2 py-0.5 text-xs font-semibold ${tone} ${className}`}
    >
      <i aria-hidden className="h-1.5 w-1.5 shrink-0 rounded-full bg-current" />
      {children}
    </span>
  );
}
