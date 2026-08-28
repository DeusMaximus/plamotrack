import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";

import { api, ApiError, settingsQuery } from "../../api/client";
import type { DateStyle, HourCycle, InstanceSettings } from "../../api/types";
import { DATE_STYLES, HOUR_CYCLES } from "../../api/types";
import { Button, Card, ErrorBanner, Field, Input, Select } from "../../components/ui";
import { formatDateTimeWith, formatMoneyWith, formatNumberWith } from "../../lib/format";
import { enabledLanguages, resolveLanguage } from "../../lib/presentation";
import { SectionHeader } from "./SectionHeader";

/** The instance-wide language and regional controls (#27). Values are canonical
 *  identifiers (BCP 47 tags, IANA zones, Intl vocabulary) and travel
 *  untranslated; only their labels come from the catalogue. Validation is the
 *  server's — the same predicates the CSV importer shares — so the form stays a
 *  thin editor over PATCH /settings. */
export function LanguageSection() {
  const { t } = useTranslation();
  const { data: settings, error } = useQuery(settingsQuery);

  return (
    <div className="space-y-6">
      <SectionHeader
        title={t("settings.sections.language")}
        description={t("settings.language.description")}
      />
      {error ? (
        <ErrorBanner message={error instanceof ApiError ? error.message : t("common.requestFailed")} />
      ) : settings ? (
        <RegionCard settings={settings} />
      ) : (
        <p className="text-sm text-zinc-500">{t("common.loading")}</p>
      )}
    </div>
  );
}

interface RegionForm {
  interface_language: string;
  formatting_locale: string;
  time_zone: string;
  date_style: DateStyle;
  hour_cycle: HourCycle;
}

/** IANA zones for the datalist, where this browser can enumerate them — the
 *  server validates the value either way, so an older browser just types blind. */
function zoneOptions(): string[] {
  try {
    return Intl.supportedValuesOf("timeZone");
  } catch {
    return [];
  }
}

/** Mounted only once settings exist — `useForm` snapshots `defaultValues` on
 *  first render (the InventoryPage.tsx trap). */
function RegionCard({ settings }: { settings: InstanceSettings }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const resolved = resolveLanguage(settings.interface_language);
  const languages = enabledLanguages();

  const {
    register,
    handleSubmit,
    reset,
    setValue,
    watch,
    formState: { isSubmitting, isDirty },
  } = useForm<RegionForm>({
    defaultValues: {
      interface_language: settings.interface_language,
      formatting_locale: settings.formatting_locale,
      time_zone: settings.time_zone,
      date_style: settings.date_style,
      hour_cycle: settings.hour_cycle,
    },
  });

  const draft = watch();
  const draftLanguage = languages.find((entry) => entry.tag === draft.interface_language);
  // A language's usual locale is its own tag — offered, never imposed: picking a
  // language must not silently overwrite a separately chosen formatting locale.
  const suggestsLocale = draftLanguage !== undefined && draft.formatting_locale !== draftLanguage.tag;

  const onSubmit = handleSubmit(async (values) => {
    setError(null);
    setSaved(false);
    try {
      const updated = await api.updateSettings(values);
      // Write-through, then refetch the world: every visible date, time and
      // number was rendered under the old preferences, and the Layout effect
      // re-applies language/lang/dir from this same cache entry.
      queryClient.setQueryData(settingsQuery.queryKey, updated);
      await queryClient.invalidateQueries();
      reset({
        interface_language: updated.interface_language,
        formatting_locale: updated.formatting_locale,
        time_zone: updated.time_zone,
        date_style: updated.date_style,
        hour_cycle: updated.hour_cycle,
      });
      setSaved(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("common.requestFailed"));
    }
  });

  const previewPrefs = {
    locale: draft.formatting_locale,
    timeZone: draft.time_zone,
    dateStyle: draft.date_style,
    hourCycle: draft.hour_cycle,
  };

  return (
    <Card
      title={t("settings.language.currentTitle")}
      description={t("settings.language.currentDescription")}
    >
      {/* The saved language isn't in this build (removed or disabled after it
          was set): the UI is on the en-AU fallback, visibly and recoverably —
          the selector below offers what this build can actually serve. */}
      {resolved.fallback && (
        <div
          role="alert"
          className="mb-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800"
        >
          {t("settings.language.fallbackWarning", { tag: settings.interface_language })}
        </div>
      )}
      <form onSubmit={onSubmit} className="space-y-3">
        <ErrorBanner message={error} />
        <Field label={t("settings.language.interfaceLanguage")} required className="max-w-72">
          <Select {...register("interface_language")}>
            {resolved.fallback && (
              <option value={settings.interface_language}>
                {t("settings.language.unavailableOption", { tag: settings.interface_language })}
              </option>
            )}
            {languages.map((entry) => (
              <option key={entry.tag} value={entry.tag}>
                {entry.nativeName}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={t("settings.language.formattingLocale")} required className="max-w-72">
          <Input {...register("formatting_locale")} />
          {suggestsLocale && (
            <p className="mt-1 text-xs text-zinc-500">
              {t("settings.language.localeHint", {
                language: draftLanguage.nativeName,
                tag: draftLanguage.tag,
              })}{" "}
              <button
                type="button"
                className="text-indigo-600 hover:underline"
                onClick={() =>
                  setValue("formatting_locale", draftLanguage.tag, { shouldDirty: true })
                }
              >
                {t("settings.language.localeUse", { tag: draftLanguage.tag })}
              </button>
            </p>
          )}
        </Field>
        <Field label={t("settings.language.timeZone")} required className="max-w-72">
          <Input list="settings-time-zones" {...register("time_zone")} />
          <datalist id="settings-time-zones">
            {zoneOptions().map((zone) => (
              <option key={zone} value={zone} />
            ))}
          </datalist>
          <p className="mt-1 text-xs text-zinc-500">{t("settings.language.timeZoneHint")}</p>
        </Field>
        <div className="flex flex-wrap gap-3">
          <Field label={t("settings.language.dateStyle")} required className="max-w-44">
            <Select {...register("date_style")}>
              {DATE_STYLES.map((style) => (
                <option key={style} value={style}>
                  {t(`dateStyle.${style}`)}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={t("settings.language.hourCycle")} required className="max-w-44">
            <Select {...register("hour_cycle")}>
              {HOUR_CYCLES.map((cycle) => (
                <option key={cycle} value={cycle}>
                  {t(`hourCycle.${cycle}`)}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        {/* The draft, rendered live through the same helpers every page uses —
            what saving will make of a timestamp, a count, and an amount. */}
        <p data-testid="format-preview" className="text-xs text-zinc-500">
          {t("settings.language.preview")}{" "}
          <span className="text-zinc-700">
            {formatDateTimeWith(previewPrefs, "2026-03-14T04:00:00+00:00")}
            {t("common.dotSeparator")}
            {formatNumberWith(draft.formatting_locale, 1234567)}
            {t("common.dotSeparator")}
            {formatMoneyWith(draft.formatting_locale, 499900, settings.reference_currency)}
          </span>
        </p>
        <div className="flex items-center gap-3">
          <Button type="submit" disabled={!isDirty || isSubmitting}>
            {isSubmitting ? t("settings.language.saving") : t("common.save")}
          </Button>
          {saved && !isDirty && (
            <span role="status" className="text-sm text-green-700">
              {t("settings.language.saved")}
            </span>
          )}
        </div>
      </form>
    </Card>
  );
}
