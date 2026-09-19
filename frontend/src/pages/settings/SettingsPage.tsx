import { ChevronLeft, ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link, Navigate, NavLink, Outlet, useMatch } from "react-router-dom";

import { navRowClass } from "../../components/Layout";
import { PageHeader } from "../../components/ui";
import { useShell } from "../../lib/shell";

/** Section slugs are route segments (App.tsx nests them under /settings) and
 *  stay canonical/untranslated; only the labels go through the catalogue. */
const SECTIONS = [
  { to: "general", label: "settings.sections.general" },
  { to: "language", label: "settings.sections.language" },
  { to: "data", label: "settings.sections.data" },
  { to: "tokens", label: "settings.sections.tokens" },
  { to: "about", label: "settings.sections.about" },
] as const;

/** The focus key of the phone's way back to the section list (`lib/focusKey.ts`).
 *  The section links name it as their stand-in — a phone does not draw them
 *  beside a section — and it names the open section's link as its own. */
const BACK_FOCUS = "settings-sections";
const sectionFocus = (slug: string) => `settings:${slug}`;

/** More's row (MorePage), which is where a phone reaches this list from. */
const LIST_ROW_CLASS =
  "flex min-h-14 w-full items-center gap-3.5 px-3.5 py-2 text-[15px] font-medium text-text hover:bg-chip";

/** Settings in two shapes (design §13.7, #260). From 768 px up, two panes: the
 *  section links in the sidebar's row shape (§13.3) and the open section beside
 *  them, `/settings` itself landing on General. On a phone the section list is
 *  a screen of its own — `/settings`, reached from More — and a section opens
 *  from it with the bar's chevron as the way back.
 *
 *  One `<nav>` for both: the same links dressed as panes' rows or as a list,
 *  and hidden beside an open section on a phone — so turning a tablet keeps
 *  the page, the form in it and the focused link (the links and the chevron
 *  name each other as stand-ins for the shape that draws only one of them). */
export function SettingsPage() {
  const { t } = useTranslation();
  const phone = useShell() === "phone";
  const atList = useMatch({ path: "/settings", end: true }) !== null;
  const open = useMatch("/settings/:section")?.params.section;
  return (
    <div className="max-w-4xl">
      <PageHeader
        title={t("settings.title")}
        subtitle={phone && !atList ? undefined : t("settings.subtitle")}
        back={
          atList ? undefined : (
            <Link
              to="/settings"
              aria-label={t("settings.allSections")}
              data-focus-key={BACK_FOCUS}
              data-focus-stand-in={open ? sectionFocus(open) : undefined}
              className="-ms-3 grid size-11 shrink-0 place-items-center rounded-sm text-muted hover:bg-chip hover:text-text"
            >
              <ChevronLeft size={22} aria-hidden className="rtl:-scale-x-100" />
            </Link>
          )
        }
      />
      <div className="mt-6 md:flex md:gap-8 max-md:mt-4">
        <nav
          aria-label={t("settings.title")}
          className={
            phone
              ? atList
                ? "flex flex-col divide-y divide-rule rounded-md border border-border bg-surface"
                : "hidden"
              : "flex w-44 shrink-0 flex-col gap-0.5 self-start"
          }
        >
          {SECTIONS.map((section) => (
            <NavLink
              key={section.to}
              to={section.to}
              data-focus-key={sectionFocus(section.to)}
              data-focus-stand-in={BACK_FOCUS}
              className={(state) => (phone ? LIST_ROW_CLASS : `whitespace-nowrap ${navRowClass(state)}`)}
            >
              <span className="flex-1">{t(section.label)}</span>
              {phone && (
                <ChevronRight size={18} aria-hidden className="shrink-0 text-faint rtl:-scale-x-100" />
              )}
            </NavLink>
          ))}
        </nav>
        <div className="min-w-0 flex-1">
          <Outlet />
        </div>
      </div>
    </div>
  );
}

/** `/settings` itself: the section list on a phone, which `SettingsPage` has
 *  already drawn; General from 768 px up, where the list is beside a section
 *  and an empty pane would be the only thing the route could add. */
export function SettingsIndex() {
  return useShell() === "phone" ? null : <Navigate to="general" replace />;
}
