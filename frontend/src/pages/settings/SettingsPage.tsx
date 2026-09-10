import { useTranslation } from "react-i18next";
import { NavLink, Outlet } from "react-router-dom";

import { navRowClass } from "../../components/Layout";
import { PageTitle } from "../../components/ui";

/** Section slugs are route segments (App.tsx nests them under /settings) and
 *  stay canonical/untranslated; only the labels go through the catalogue. */
const SECTIONS = [
  { to: "general", label: "settings.sections.general" },
  { to: "language", label: "settings.sections.language" },
  { to: "data", label: "settings.sections.data" },
  { to: "tokens", label: "settings.sections.tokens" },
  { to: "about", label: "settings.sections.about" },
] as const;

export function SettingsPage() {
  const { t } = useTranslation();
  return (
    <div className="max-w-4xl">
      <div>
        <PageTitle>{t("settings.title")}</PageTitle>
        <p className="mt-0.5 text-sm text-muted">{t("settings.subtitle")}</p>
      </div>
      {/* Stacked on small screens (sections in a scrollable row), a second pane
          on sm+ — the rows in the sidebar's own shape (§13.3). */}
      <div className="mt-6 sm:flex sm:gap-8">
        <nav
          aria-label={t("settings.title")}
          className="flex gap-0.5 overflow-x-auto sm:w-44 sm:shrink-0 sm:flex-col sm:self-start"
        >
          {SECTIONS.map((section) => (
            <NavLink
              key={section.to}
              to={section.to}
              className={(state) => `whitespace-nowrap ${navRowClass(state)}`}
            >
              {t(section.label)}
            </NavLink>
          ))}
        </nav>
        <div className="mt-4 min-w-0 flex-1 sm:mt-0">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
