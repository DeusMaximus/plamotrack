import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { NavLink, Outlet } from "react-router-dom";

import { settingsQuery } from "../api/client";
import { applyInstanceSettings } from "../lib/presentation";

const NAV = [
  { to: "/board", label: "nav.board", icon: "📋" },
  { to: "/kits", label: "nav.kits", icon: "🤖" },
  { to: "/orders", label: "nav.orders", icon: "📦" },
  { to: "/inventory", label: "nav.inventory", icon: "🛠️" },
  { to: "/retailers", label: "nav.retailers", icon: "🏪" },
  { to: "/settings", label: "nav.settings", icon: "⚙️" },
] as const;

export const SIDEBAR_DIVIDER_CLASS = "border-e";

export function Layout() {
  const { t } = useTranslation();
  // The one place the persisted settings row becomes this browser's
  // presentation (#27): language, document lang/dir, and the formatting
  // preferences the date/number helpers read. Every browser runs the same
  // effect off the same shared query, so there is no per-browser preference —
  // and a save (which writes through settingsQuery's cache) re-runs it.
  const { data: settings } = useQuery(settingsQuery);
  // The apply notifies `usePresentationVersion` subscribers itself (#174
  // review, P3-1): the render that delivers the settings data happens BEFORE
  // this effect applies them, so the pages have already formatted with the
  // previous preferences — and a re-render scheduled *here* cannot reach
  // them, because Outlet hands back the same element reference and the page
  // subtree bails out. The formatting pages subscribe directly instead.
  useEffect(() => {
    if (settings) applyInstanceSettings(settings);
  }, [settings]);
  return (
    <div className="flex min-h-screen">
      <aside className={`w-52 shrink-0 ${SIDEBAR_DIVIDER_CLASS} border-zinc-200 bg-white`}>
        <div className="px-4 py-5">
          {/* The wordmark is a brand identifier, not copy — it stays untranslated. */}
          <h1 className="text-xl font-bold tracking-tight text-indigo-600">plamotrack</h1>
          <p className="mt-0.5 text-[11px] leading-tight text-zinc-400">{t("layout.tagline")}</p>
        </div>
        <nav className="space-y-0.5 px-2">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium ${
                  isActive
                    ? "bg-indigo-50 text-indigo-700"
                    : "text-zinc-600 hover:bg-zinc-50 hover:text-zinc-900"
                }`
              }
            >
              <span aria-hidden>{item.icon}</span>
              {t(item.label)}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="min-w-0 flex-1 p-6">
        <Outlet />
      </main>
    </div>
  );
}
