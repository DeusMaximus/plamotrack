import { Monitor, Moon, Sun, type LucideIcon } from "lucide-react";
import { useTranslation } from "react-i18next";

import { THEME_PREFERENCES, useTheme, type ThemePreference } from "../lib/theme";

const THEME_FOCUS = "theme";

const THEME_ICONS: Record<ThemePreference, LucideIcon> = {
  light: Sun,
  dark: Moon,
  system: Monitor,
};

/** The words a labelled segment shows. "Follow the device" does not fit a third
 *  of a phone's width, so that segment reads "Device" — and keeps the full
 *  sentence as its accessible name, which contains the word on screen. */
const SEGMENT_TEXT = {
  light: "theme.light",
  dark: "theme.dark",
  system: "theme.systemShort",
} as const;

/** Light / dark / system, one segmented control (§13.1). A radio group: one of
 *  three is always chosen, and arrow keys are how a keyboard moves between them.
 *  `labelled` is the More page's (§13.7): full-height segments with their words;
 *  the sidebar's are icons, and grow to the touch height under `touch:`. The
 *  accessible names are the same in both. */
export function ThemeSwitch({ labelled = false }: { labelled?: boolean }) {
  const { t } = useTranslation();
  const [preference, setPreference] = useTheme();
  return (
    <div
      role="radiogroup"
      aria-label={t("theme.label")}
      className={`flex gap-0.5 rounded-sm border border-border bg-surface p-[3px] ${labelled ? "" : "mx-1"}`}
      onKeyDown={(event) => {
        const forward = event.key === "ArrowRight" || event.key === "ArrowDown";
        const back = event.key === "ArrowLeft" || event.key === "ArrowUp";
        const edge =
          event.key === "Home" ? 0 : event.key === "End" ? THEME_PREFERENCES.length - 1 : null;
        if (!forward && !back && edge === null) return;
        event.preventDefault();
        // From the focused radio, not the stored preference: another tab can
        // change the preference under a focus that stayed put — the storage
        // handler deliberately never moves focus — and the radio pattern moves
        // from where the keyboard is (#235 P3-2).
        const focused = (event.target as HTMLElement).closest<HTMLElement>("[data-theme-option]")
          ?.dataset.themeOption as ThemePreference | undefined;
        const from = focused ? THEME_PREFERENCES.indexOf(focused) : -1;
        const start = from === -1 ? THEME_PREFERENCES.indexOf(preference) : from;
        const count = THEME_PREFERENCES.length;
        const next =
          edge !== null
            ? THEME_PREFERENCES[edge]
            : THEME_PREFERENCES[(start + (forward ? 1 : -1) + count) % count];
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
            // The sidebar's segments, the rail's one button and (on a phone) the
            // More tab are one control in three shells (`lib/focusKey.ts`): the
            // chosen segment carries the key, being the one Tab stops on. The
            // More page's own switch is one node at every width and needs none.
            {...(labelled
              ? {}
              : checked
                ? { "data-focus-key": THEME_FOCUS, "data-focus-stand-in": "nav:/more" }
                : { "data-focus-stand-in": `${THEME_FOCUS} nav:/more` })}
            tabIndex={checked ? 0 : -1}
            onClick={() => setPreference(option)}
            className={`flex flex-1 items-center justify-center rounded-sm ${
              labelled ? "h-11 gap-2 text-[13.5px] font-medium" : "h-6.5 touch:h-11"
            } ${
              checked
                ? "bg-chip text-text"
                : labelled
                  ? "text-muted hover:text-text"
                  : "text-faint hover:text-muted"
            }`}
          >
            <Icon size={labelled ? 16 : 15} aria-hidden />
            {labelled && t(SEGMENT_TEXT[option])}
          </button>
        );
      })}
    </div>
  );
}

/** The rail's theme control (§13.7): 64 px has no room for three segments, so
 *  it is one button that steps light → dark → device, showing and naming the
 *  choice in force. */
export function ThemeCycleButton({ className }: { className: string }) {
  const { t } = useTranslation();
  const [preference, setPreference] = useTheme();
  const Icon = THEME_ICONS[preference];
  const label = t("theme.cycle", { choice: t(`theme.${preference}`) });
  const next =
    THEME_PREFERENCES[(THEME_PREFERENCES.indexOf(preference) + 1) % THEME_PREFERENCES.length];
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={() => setPreference(next)}
      className={className}
      data-focus-key={THEME_FOCUS}
      data-focus-stand-in="nav:/more"
    >
      <Icon size={20} aria-hidden />
    </button>
  );
}
