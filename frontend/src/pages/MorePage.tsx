import { useQuery } from "@tanstack/react-query";
import { ChevronRight, LogOut, Settings, Store, type LucideIcon } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { authSessionQuery } from "../api/client";
import { Identity } from "../components/Layout";
import { ThemeSwitch } from "../components/ThemeSwitch";
import { MICRO_LABEL_CLASS, PageHeader } from "../components/ui";
import { useSignOut } from "../lib/signOut";

/** The phone shell's fifth tab (design §13.7): everything the sidebar's lower
 *  half holds, since a tab bar has five places and the collection takes four —
 *  Retailers, Settings, the theme switch, who the owner is bound as (OIDC mode
 *  only, §13.3) and Sign out. Only the tab bar links here; opened at a wider
 *  width — a bookmark, a rotated tablet — it is the same page beside a
 *  navigation that already offers all of it, which is harmless. */
const DESTINATIONS: readonly { to: string; label: "nav.retailers" | "nav.settings"; icon: LucideIcon }[] = [
  { to: "/retailers", label: "nav.retailers", icon: Store },
  { to: "/settings", label: "nav.settings", icon: Settings },
];

const ROW_CLASS = "flex h-14 w-full items-center gap-3.5 px-3.5 text-[15px] font-medium text-text";
const PANEL_CLASS = "divide-y divide-rule rounded-md border border-border bg-surface";

export function MorePage() {
  const { t } = useTranslation();
  const { data: session } = useQuery(authSessionQuery);
  const signOut = useSignOut();
  return (
    <div className="max-w-md space-y-5.5">
      <PageHeader title={t("nav.more")} />
      <nav aria-label={t("nav.more")} className={`flex flex-col ${PANEL_CLASS}`}>
        {DESTINATIONS.map((item) => (
          <Link key={item.to} to={item.to} className={`${ROW_CLASS} hover:bg-chip`}>
            <item.icon size={20} aria-hidden className="shrink-0 text-muted" />
            <span className="flex-1">{t(item.label)}</span>
            <ChevronRight size={18} aria-hidden className="shrink-0 text-faint rtl:-scale-x-100" />
          </Link>
        ))}
      </nav>
      <section aria-labelledby="more-theme" className="space-y-2.5">
        <h2 id="more-theme" className={MICRO_LABEL_CLASS}>
          {t("theme.label")}
        </h2>
        <ThemeSwitch labelled />
      </section>
      <section className={PANEL_CLASS}>
        {session?.auth_mode === "oidc" && session.display_name && (
          <Identity name={session.display_name} issuer={session.oidc_issuer} variant="card" />
        )}
        <button type="button" onClick={signOut} className={`${ROW_CLASS} hover:bg-chip`}>
          <LogOut size={20} aria-hidden className="shrink-0 text-muted" />
          {t("auth.signOut")}
        </button>
      </section>
    </div>
  );
}
