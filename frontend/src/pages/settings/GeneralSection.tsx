import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";

import { api, ApiError, metaQuery, settingsQuery } from "../../api/client";
import type { InstanceSettings } from "../../api/types";
import { Button, Card, ErrorBanner, Field, Input } from "../../components/ui";
import { currencyOptions } from "../../lib/currency";
import { SectionHeader } from "./SectionHeader";

export function GeneralSection() {
  const { t } = useTranslation();
  const { data: settings, error } = useQuery(settingsQuery);

  return (
    <div className="space-y-6">
      <SectionHeader
        title={t("settings.sections.general")}
        description={t("settings.general.description")}
      />
      {error ? (
        <ErrorBanner message={error instanceof ApiError ? error.message : t("common.requestFailed")} />
      ) : settings ? (
        <CurrencyCard settings={settings} />
      ) : (
        <p className="text-sm text-zinc-500">{t("common.loading")}</p>
      )}
    </div>
  );
}

/** Rendered only once settings exist: `useForm` snapshots `defaultValues` on
 *  first render (the InventoryPage.tsx trap), so the form must not mount before
 *  the row it hydrates from has arrived. */
function CurrencyCard({ settings }: { settings: InstanceSettings }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting, isDirty },
  } = useForm<{ reference_currency: string }>({
    defaultValues: { reference_currency: settings.reference_currency },
  });

  const onSubmit = handleSubmit(async (values) => {
    setError(null);
    setSaved(false);
    try {
      const updated = await api.updateSettings({
        reference_currency: values.reference_currency,
      });
      // The PATCH response is the fresh row — no need to refetch it. But /meta
      // serves the same reference_currency with staleTime Infinity, and the
      // order/inventory forms default from that copy, so it must not survive
      // the save.
      queryClient.setQueryData(settingsQuery.queryKey, updated);
      await queryClient.invalidateQueries({ queryKey: metaQuery.queryKey });
      reset({ reference_currency: updated.reference_currency });
      setSaved(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("common.requestFailed"));
    }
  });

  return (
    <Card
      title={t("settings.general.currencyTitle")}
      description={t("settings.general.currencyDescription")}
    >
      <form onSubmit={onSubmit} className="space-y-3">
        <ErrorBanner message={error} />
        <Field
          label={t("settings.general.currencyLabel")}
          required
          error={errors.reference_currency?.message}
          className="max-w-40"
        >
          <Input
            list="settings-currencies"
            maxLength={3}
            {...register("reference_currency", {
              required: t("validation.currencyCode"),
              pattern: { value: /^[A-Z]{3}$/, message: t("validation.currencyCode") },
            })}
          />
          <datalist id="settings-currencies">
            {currencyOptions(settings.reference_currency).map((code) => (
              <option key={code} value={code} />
            ))}
          </datalist>
        </Field>
        <p className="text-xs text-zinc-500">{t("settings.general.currencyNote")}</p>
        <div className="flex items-center gap-3">
          <Button type="submit" disabled={!isDirty || isSubmitting}>
            {isSubmitting ? t("settings.general.saving") : t("common.save")}
          </Button>
          {/* isDirty gates the confirmation so editing again retires it. */}
          {saved && !isDirty && (
            <span role="status" className="text-sm text-green-700">
              {t("settings.general.saved")}
            </span>
          )}
        </div>
      </form>
    </Card>
  );
}
