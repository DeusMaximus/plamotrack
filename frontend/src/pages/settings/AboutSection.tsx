import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { ApiError, metaQuery } from "../../api/client";
import { Card, ErrorBanner } from "../../components/ui";
import { SectionHeader } from "./SectionHeader";

export function AboutSection() {
  const { t } = useTranslation();
  const { data: meta, error } = useQuery(metaQuery);

  return (
    <div className="space-y-6">
      <SectionHeader
        title={t("settings.sections.about")}
        description={t("settings.about.description")}
      />
      {error ? (
        <ErrorBanner message={error instanceof ApiError ? error.message : t("common.requestFailed")} />
      ) : meta ? (
        /* The wordmark is a brand identifier, not copy — it stays untranslated. */
        <Card title="plamotrack" description={t("layout.tagline")}>
          <dl>
            <div className="flex items-baseline justify-between gap-4">
              <dt className="text-sm text-zinc-600">{t("settings.about.version")}</dt>
              <dd className="text-sm">
                <code className="rounded bg-zinc-100 px-1.5 py-0.5 font-mono text-xs text-zinc-700">
                  {meta.version}
                </code>
              </dd>
            </div>
          </dl>
        </Card>
      ) : (
        <p className="text-sm text-zinc-500">{t("common.loading")}</p>
      )}
    </div>
  );
}
