import { useQuery } from "@tanstack/react-query";
import {
  Box,
  Ellipsis,
  House,
  LogOut,
  Settings,
  ShoppingBag,
  Store,
  Wrench,
} from "lucide-react";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";

import { authSessionQuery, settingsQuery } from "../api/client";
import { providerName } from "../lib/labels";
import { useFocusAcrossShells } from "../lib/focusKey";
import { applyInstanceSettings } from "../lib/presentation";
import { useShell } from "../lib/shell";
import { useSignOut } from "../lib/signOut";
import { BrandMark } from "./BrandMark";
import { ThemeCycleButton, ThemeSwitch } from "./ThemeSwitch";

/** The collection's pages (§13.3): Home first — the start page (§13.2). No
 *  `end` on the root link: React Router's match rule treats `/` as a whole
 *  segment, so Home reads as current only at `/` (the Home e2e pins it). */
const NAV = [
  { to: "/", label: "nav.home", icon: House },
  { to: "/kits", label: "nav.kits", icon: Box },
  { to: "/orders", label: "nav.orders", icon: ShoppingBag },
  { to: "/inventory", label: "nav.inventory", icon: Wrench },
  { to: "/retailers", label: "nav.retailers", icon: Store },
] as const;

/** The phone's tab bar (§13.7) has five places and the fifth is More, so
 *  Retailers moves there with everything the sidebar's lower half holds. */
const PHONE_TABS = NAV.filter((item) => item.to !== "/retailers");

/** What lives under More on a phone: the tab reads as current on each of them,
 *  the way a tab bar's More does, and tapping it is the way back to the list. */
const MORE_PATHS = ["/more", "/retailers", "/settings"] as const;

/** The navigation is three different sets of nodes, so its controls carry focus
 *  keys like a list's rows do (`lib/focusKey.ts`): a shell change under a
 *  focused link hands the keyboard to the same destination's link in the new
 *  shell. What a phone keeps under More names that tab as its stand-in; the tab
 *  names the first of them for the way back. */
const MORE_FOCUS = "nav:/more";
const navFocus = (to: string) => ({
  "data-focus-key": `nav:${to}`,
  ...(PHONE_TABS.some((item) => item.to === to) ? {} : { "data-focus-stand-in": MORE_FOCUS }),
});
const SIGN_OUT_FOCUS = { "data-focus-key": "sign-out", "data-focus-stand-in": MORE_FOCUS };

export const SIDEBAR_DIVIDER_CLASS = "border-e";

/** One nav row (§13.3): the sidebar's, and the Settings sections' (SettingsPage).
 *  36 px for a mouse, the 44 px touch height under `touch:` (§13.7). */
export const NAV_ROW_CLASS =
  "flex h-9 items-center gap-2.5 rounded-sm px-3 text-sm font-medium touch:h-11";

export function navRowClass({ isActive }: { isActive: boolean }): string {
  return `${NAV_ROW_CLASS} ${
    isActive ? "bg-accent-soft text-accent" : "text-muted hover:bg-chip hover:text-text"
  }`;
}

/** One rail control (§13.7): a 44 px square around a 20 px icon, named for
 *  assistive tech and the tooltip by its caller. */
const RAIL_ITEM_CLASS = "flex h-11 w-11 shrink-0 items-center justify-center rounded-sm";
const RAIL_IDLE_CLASS = "text-muted hover:bg-chip hover:text-text";

function railItemClass({ isActive }: { isActive: boolean }): string {
  return `${RAIL_ITEM_CLASS} ${isActive ? "bg-accent-soft text-accent" : RAIL_IDLE_CLASS}`;
}

const TAB_CLASS =
  "-mt-px flex h-14 flex-col items-center justify-center gap-1 border-t-2 text-[10.5px] font-semibold tracking-[0.01em]";

function tabClass({ isActive }: { isActive: boolean }): string {
  return `${TAB_CLASS} ${isActive ? "border-accent text-accent" : "border-transparent text-muted"}`;
}

export function Layout() {
  const shell = useShell();
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
  // A list's rows are different nodes on either side of the 768 px line; the
  // keyboard keeps its place across it by the record it was on (#258).
  useFocusAcrossShells(shell);
  // Three shells by viewport width alone (§13.7). `main` keeps its place in the
  // tree whichever navigation stands beside it, so a rotation or a resize
  // across a line re-dresses the page without remounting it — an open dialog
  // and a half-filled form survive. `min-h-dvh`, not `vh`: on iOS 100vh is the
  // *large* viewport, which put the sidebar's foot under Safari's toolbar.
  return (
    <div className="px-safe flex min-h-dvh">
      {shell === "sidebar" ? <Sidebar /> : shell === "rail" ? <Rail /> : null}
      {/* `break-words` in the phone shell: under a large browser font the gutter
          and every card's padding are in rem, the screen is not, and what is
          left — 158 px inside a card at 40 px on a 320 px phone — is narrower
          than "formatting" or "Australia/Sydney". A word breaks where its box
          ends instead of widening the page (and the tab bar, which is fixed to
          the layout viewport, with it; #269). It changes no box's min-content
          size, so nothing that fits today moves. */}
      <main
        className={`min-w-0 flex-1 ${shell === "phone" ? "pb-tab-bar px-4 break-words" : "px-8 py-7"}`}
      >
        <Outlet />
      </main>
      {shell === "phone" && <TabBar />}
    </div>
  );
}

/** 1280 px and up (§13.3): unchanged by the phone and tablet work. */
function Sidebar() {
  const { t } = useTranslation();
  const { data: session } = useQuery(authSessionQuery);
  const signOut = useSignOut();
  return (
    // Sticky, viewport-high: the sidebar stays while the page scrolls (§13.3).
    <aside
      className={`sticky top-0 flex h-dvh w-60 shrink-0 flex-col ${SIDEBAR_DIVIDER_CLASS} border-border bg-bg px-3 pb-4 pt-5`}
    >
      {/* The wordmark is a brand identifier, not copy — it stays untranslated.
          Not a heading: each page has its own h1. */}
      <div className="flex items-center gap-2.5 px-3 pb-5 text-[17px] font-semibold tracking-tight text-text">
        <BrandMark />
        <span>plamotrack</span>
      </div>
      <nav className="flex flex-col gap-0.5">
        {NAV.map((item) => (
          <NavLink key={item.to} to={item.to} className={navRowClass} {...navFocus(item.to)}>
            <item.icon size={18} aria-hidden />
            {t(item.label)}
          </NavLink>
        ))}
      </nav>
      <div className="flex-1" />
      <nav className="flex flex-col gap-0.5">
        <NavLink to="/settings" className={navRowClass} {...navFocus("/settings")}>
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
          {...SIGN_OUT_FOCUS}
        >
          <LogOut size={18} aria-hidden />
          {t("auth.signOut")}
        </button>
      </div>
    </aside>
  );
}

/** 768–1279 px (§13.7): the sidebar as a 64 px column of icons, on every device
 *  — an iPad and a narrow desktop window alike. Each control keeps the
 *  sidebar's accessible name and says it again as a tooltip. It scrolls, which
 *  the sidebar never needed to: a phone held sideways is this wide and barely
 *  taller than the rail's nine controls. */
function Rail() {
  const { t } = useTranslation();
  const { data: session } = useQuery(authSessionQuery);
  const signOut = useSignOut();
  return (
    <aside
      className={`sticky top-0 flex h-dvh w-16 shrink-0 flex-col items-center gap-1 overflow-y-auto ${SIDEBAR_DIVIDER_CLASS} border-border bg-bg pb-4 pt-4.5`}
    >
      <div className="mb-2.5 flex h-11 w-11 shrink-0 items-center justify-center">
        <BrandMark size={22} />
      </div>
      <nav aria-label={t("nav.main")} className="flex flex-col gap-1">
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            aria-label={t(item.label)}
            title={t(item.label)}
            className={railItemClass}
            {...navFocus(item.to)}
          >
            <item.icon size={20} aria-hidden />
          </NavLink>
        ))}
      </nav>
      <div className="min-h-4 flex-1" />
      <NavLink
        to="/settings"
        aria-label={t("nav.settings")}
        title={t("nav.settings")}
        className={railItemClass}
        {...navFocus("/settings")}
      >
        <Settings size={20} aria-hidden />
      </NavLink>
      <div aria-hidden className="my-2 h-px w-8 shrink-0 bg-rule" />
      <ThemeCycleButton className={`${RAIL_ITEM_CLASS} ${RAIL_IDLE_CLASS}`} />
      {session?.auth_mode === "oidc" && session.display_name && (
        <Identity name={session.display_name} issuer={session.oidc_issuer} variant="initial" />
      )}
      <button
        type="button"
        onClick={signOut}
        aria-label={t("auth.signOut")}
        title={t("auth.signOut")}
        className={`${RAIL_ITEM_CLASS} ${RAIL_IDLE_CLASS}`}
        {...SIGN_OUT_FOCUS}
      >
        <LogOut size={20} aria-hidden />
      </button>
    </aside>
  );
}

/** Below 768 px (§13.7): five places along the bottom edge, clear of the home
 *  indicator (`pb-safe`; `viewport-fit=cover` in index.html is what makes the
 *  inset non-zero). Fixed rather than sticky so the page scrolls beneath it;
 *  `main` reserves the room with `pb-tab-bar`. */
function TabBar() {
  const { t } = useTranslation();
  const { pathname } = useLocation();
  const underMore = MORE_PATHS.some((path) => pathname === path || pathname.startsWith(`${path}/`));
  return (
    <nav
      aria-label={t("nav.main")}
      className="px-safe pb-safe fixed inset-x-0 bottom-0 z-30 border-t border-border bg-bg"
    >
      <div className="grid grid-cols-5 px-1">
        {PHONE_TABS.map((item) => (
          <NavLink key={item.to} to={item.to} className={tabClass} {...navFocus(item.to)}>
            <item.icon size={22} aria-hidden />
            {t(item.label)}
          </NavLink>
        ))}
        {/* Not a NavLink: it is current on the pages it holds as well as its
            own, and only `/more` is the page it names. */}
        <Link
          to="/more"
          aria-current={pathname === "/more" ? "page" : underMore ? "true" : undefined}
          className={tabClass({ isActive: underMore })}
          data-focus-key={MORE_FOCUS}
          data-focus-stand-in="nav:/retailers"
        >
          <Ellipsis size={22} aria-hidden />
          {t("nav.more")}
        </Link>
      </div>
    </nav>
  );
}

/** Who the owner is bound as — OIDC mode only (§13.3): the one identity a
 *  single-owner app has to show, and the provider it came from. A row in the
 *  sidebar, a card's head on the More page, the initial alone on the rail. */
export function Identity({
  name,
  issuer,
  variant = "row",
}: {
  name: string;
  issuer: string | null;
  variant?: "row" | "card" | "initial";
}) {
  const { t } = useTranslation();
  const via = t("layout.identityVia", { provider: providerName(issuer) });
  const initial = Array.from(name)[0]?.toUpperCase() ?? "";
  if (variant === "initial") {
    return (
      <span
        role="img"
        aria-label={`${name} · ${via}`}
        title={`${name} · ${via}`}
        className="my-2 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent-soft text-xs font-semibold text-accent"
      >
        {initial}
      </span>
    );
  }
  const card = variant === "card";
  return (
    <div
      className={`flex items-center ${card ? "gap-3 p-3.5" : "gap-2.5 px-3 py-1.5 text-xs"}`}
      title={`${name} · ${via}`}
    >
      <span
        aria-hidden
        className={`flex shrink-0 items-center justify-center rounded-full bg-accent-soft font-semibold text-accent ${
          card ? "h-9 w-9 text-[15px]" : "h-6 w-6 text-[11px]"
        }`}
      >
        {initial}
      </span>
      <span className="min-w-0">
        <span className={`block truncate font-medium text-text ${card ? "text-[15px]" : ""}`}>
          {name}
        </span>
        <span className={`block truncate text-muted ${card ? "text-[12.5px]" : ""}`}>{via}</span>
      </span>
    </div>
  );
}
