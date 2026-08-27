import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { ApiError, settingsQuery } from "../../api/client";
import { Card, ErrorBanner } from "../../components/ui";
import { manifest } from "../../i18n";
import { SectionHeader } from "./SectionHeader";

/** Read-only in this milestone: the section shows what the instance holds, and
 *  the controls for changing it from here arrive with #27. The values are
 *  canonical identifiers (BCP 47 tags, IANA zones, Intl vocabulary) and render
 *  untranslated — rule 11. */
export function LanguageSection() {
  const { t } = useTranslation();
  const { data: settings, error } = useQuery(settingsQuery);

  const language = settings
    ? manifest.languages.find((entry) => entry.tag === settings.interface_language)
    : undefined;

  return (
    <div className="space-y-6">
      <SectionHeader
        title={t("settings.sections.language")}
        description={t("settings.language.description")}
      />
      {error ? (
        <ErrorBanner message={error instanceof ApiError ? error.message : t("common.requestFailed")} />
      ) : settings ? (
        <Card
          title={t("settings.language.currentTitle")}
          description={t("settings.language.currentDescription")}
        >
          <dl className="divide-y divide-zinc-100">
            <Row
              label={t("settings.language.interfaceLanguage")}
              value={settings.interface_language}
              detail={language?.nativeName}
            />
            <Row label={t("settings.language.formattingLocale")} value={settings.formatting_locale} />
            <Row label={t("settings.language.timeZone")} value={settings.time_zone} />
            <Row label={t("settings.language.dateStyle")} value={settings.date_style} />
            <Row label={t("settings.language.hourCycle")} value={settings.hour_cycle} />
          </dl>
        </Card>
      ) : (
        <p className="text-sm text-zinc-500">{t("common.loading")}</p>
      )}
    </div>
  );
}

function Row({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-2 first:pt-0 last:pb-0">
      <dt className="text-sm text-zinc-600">{label}</dt>
      <dd className="flex items-baseline gap-2 text-sm">
        {detail && <span className="text-zinc-800">{detail}</span>}
        <code className="rounded bg-zinc-100 px-1.5 py-0.5 font-mono text-xs text-zinc-700">
          {value}
        </code>
      </dd>
    </div>
  );
}
