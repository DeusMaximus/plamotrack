import { useTranslation } from "react-i18next";
import { NavLink, Outlet } from "react-router-dom";

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
        <h1 className="text-2xl font-bold">{t("settings.title")}</h1>
        <p className="mt-0.5 text-sm text-zinc-500">{t("settings.subtitle")}</p>
      </div>
      {/* Stacked on small screens (sections in a scrollable row), sidebar on sm+. */}
      <div className="mt-6 sm:flex sm:gap-8">
        <nav
          aria-label={t("settings.title")}
          className="flex gap-1 overflow-x-auto sm:w-44 sm:shrink-0 sm:flex-col sm:self-start"
        >
          {SECTIONS.map((section) => (
            <NavLink
              key={section.to}
              to={section.to}
              className={({ isActive }) =>
                `whitespace-nowrap rounded-md px-3 py-2 text-sm font-medium ${
                  isActive
                    ? "bg-indigo-50 text-indigo-700"
                    : "text-zinc-600 hover:bg-zinc-50 hover:text-zinc-900"
                }`
              }
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
