import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Box,
  LayoutDashboard,
  LogOut,
  Monitor,
  Moon,
  Settings,
  ShoppingBag,
  Store,
  Sun,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { NavLink, Outlet } from "react-router-dom";

import { api, authSessionQuery, setCsrfToken, settingsQuery } from "../api/client";
import { providerName } from "../lib/labels";
import { applyInstanceSettings } from "../lib/presentation";
import { THEME_PREFERENCES, useTheme, type ThemePreference } from "../lib/theme";
import { BrandMark } from "./BrandMark";

/** The collection's pages (§13.3). The board is the start page until Home
 *  replaces it (§13.2, M6.5 PR 3), when this first entry becomes Home. */
const NAV = [
  { to: "/board", label: "nav.board", icon: LayoutDashboard },
  { to: "/kits", label: "nav.kits", icon: Box },
  { to: "/orders", label: "nav.orders", icon: ShoppingBag },
  { to: "/inventory", label: "nav.inventory", icon: Wrench },
  { to: "/retailers", label: "nav.retailers", icon: Store },
] as const;

export const SIDEBAR_DIVIDER_CLASS = "border-e";

const NAV_ROW_CLASS = "flex h-9 items-center gap-2.5 rounded-sm px-3 text-sm font-medium";

function navRowClass({ isActive }: { isActive: boolean }): string {
  return `${NAV_ROW_CLASS} ${
    isActive ? "bg-accent-soft text-accent" : "text-muted hover:bg-chip hover:text-text"
  }`;
}

const THEME_ICONS: Record<ThemePreference, LucideIcon> = {
  light: Sun,
  dark: Moon,
  system: Monitor,
};

export function Layout() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { data: session } = useQuery(authSessionQuery);
  const signOut = async () => {
    try {
      await api.logout();
    } finally {
      // Whatever the server said, this browser is done: forget the CSRF token,
      // re-read the session — it now reports anonymous, so the AuthGate swaps to
      // the login screen and every page unmounts — then drop everything else so
      // nothing from this session lingers for the next owner. The order matters:
      // the session query has to still exist to be refetched (a cleared cache
      // has nothing to invalidate, and the gate would keep rendering the app
      // from its last result — caught by e2e/auth.spec.ts).
      setCsrfToken(null);
      await queryClient.invalidateQueries({ queryKey: authSessionQuery.queryKey });
      queryClient.removeQueries({
        predicate: (query) => query.queryKey[0] !== authSessionQuery.queryKey[0],
      });
    }
  };
  // The one place the persisted settings row becomes this browser's
  // presentation (#27): language, document lang/dir, and the formatting
  // preferences the date/number helpers read. Every browser runs the same
  // effect off the same shared query, so there is no per-browser preference —
  // the theme (§13.1) is the deliberate exception, and it never touches this row.
  // A save (which writes through settingsQuery's cache) re-runs it.
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
      {/* Sticky, viewport-high: the sidebar stays while the page scrolls (§13.3). */}
      <aside
        className={`sticky top-0 flex h-screen w-60 shrink-0 flex-col ${SIDEBAR_DIVIDER_CLASS} border-border bg-bg px-3 pb-4 pt-5`}
      >
        {/* The wordmark is a brand identifier, not copy — it stays untranslated.
            Not a heading: each page has its own h1. */}
        <div className="flex items-center gap-2.5 px-3 pb-5 text-[17px] font-semibold tracking-tight text-text">
          <BrandMark />
          <span>plamotrack</span>
        </div>
        <nav className="flex flex-col gap-0.5">
          {NAV.map((item) => (
            <NavLink key={item.to} to={item.to} className={navRowClass}>
              <item.icon size={18} aria-hidden />
              {t(item.label)}
            </NavLink>
          ))}
        </nav>
        <div className="flex-1" />
        <nav className="flex flex-col gap-0.5">
          <NavLink to="/settings" className={navRowClass}>
            <Settings size={18} aria-hidden />
            {t("nav.settings")}
          </NavLink>
        </nav>
        <div className="mt-3 flex flex-col gap-1.5 border-t border-rule pt-3">
          <ThemeSwitch />
          {session?.auth_mode === "oidc" && session.display_name && (
            <Identity name={session.display_name} issuer={session.oidc_issuer} />
          )}
          <button
            type="button"
            onClick={signOut}
            className={`${NAV_ROW_CLASS} w-full text-muted hover:bg-chip hover:text-text`}
          >
            <LogOut size={18} aria-hidden />
            {t("auth.signOut")}
          </button>
        </div>
      </aside>
      <main className="min-w-0 flex-1 px-8 py-7">
        <Outlet />
      </main>
    </div>
  );
}

/** Light / dark / system, one segmented control (§13.1). A radio group: one of
 *  three is always chosen, and arrow keys are how a keyboard moves between them. */
function ThemeSwitch() {
  const { t } = useTranslation();
  const [preference, setPreference] = useTheme();
  return (
    <div
      role="radiogroup"
      aria-label={t("theme.label")}
      className="mx-1 flex gap-0.5 rounded-sm border border-border bg-surface p-[3px]"
      onKeyDown={(event) => {
        const step = event.key === "ArrowRight" || event.key === "ArrowDown" ? 1 : 0;
        const back = event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 0;
        if (!step && !back) return;
        event.preventDefault();
        const index = THEME_PREFERENCES.indexOf(preference);
        const next =
          THEME_PREFERENCES[(index + step + back + THEME_PREFERENCES.length) % THEME_PREFERENCES.length];
        setPreference(next);
        (event.currentTarget.querySelector(`[data-theme-option="${next}"]`) as HTMLElement | null)?.focus();
      }}
    >
      {THEME_PREFERENCES.map((option) => {
        const Icon = THEME_ICONS[option];
        const checked = option === preference;
        return (
          <button
            key={option}
            type="button"
            role="radio"
            aria-checked={checked}
            aria-label={t(`theme.${option}`)}
            title={t(`theme.${option}`)}
            data-theme-option={option}
            tabIndex={checked ? 0 : -1}
            onClick={() => setPreference(option)}
            className={`flex h-6.5 flex-1 items-center justify-center rounded-[2px] ${
              checked ? "bg-chip text-text" : "text-faint hover:text-muted"
            }`}
          >
            <Icon size={15} aria-hidden />
          </button>
        );
      })}
    </div>
  );
}

/** Who the owner is bound as — OIDC mode only (§13.3): the one identity a
 *  single-owner app has to show, and the provider it came from. */
function Identity({ name, issuer }: { name: string; issuer: string | null }) {
  const { t } = useTranslation();
  const via = t("layout.identityVia", { provider: providerName(issuer) });
  const initial = Array.from(name)[0]?.toUpperCase() ?? "";
  return (
    <div className="flex items-center gap-2.5 px-3 py-1.5 text-xs" title={`${name} · ${via}`}>
      <span
        aria-hidden
        className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent-soft text-[11px] font-semibold text-accent"
      >
        {initial}
      </span>
      <span className="min-w-0">
        <span className="block truncate font-medium text-text">{name}</span>
        <span className="block truncate text-faint">{via}</span>
      </span>
    </div>
  );
}
