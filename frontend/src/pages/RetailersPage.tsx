import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";

import { api, ApiError } from "../api/client";
import type { PackingQuality, Retailer, ShippingSpeed, WouldOrderAgain } from "../api/types";
import { PACKING_QUALITIES, SHIPPING_SPEEDS, WOULD_ORDER_AGAIN } from "../api/types";
import { ExportCsvButton } from "../components/ExportCsvButton";
import { Modal } from "../components/Modal";
import {
  Button,
  Chip,
  EmptyState,
  ErrorBanner,
  Field,
  Input,
  PageTitle,
  RatingStars,
  Select,
  TABLE_HEAD_ROW_CLASS,
  Textarea,
} from "../components/ui";
import {
  packingQualityLabel,
  ratingTooltip,
  shippingSpeedLabel,
  wouldOrderAgainLabel,
} from "../lib/labels";
import { usePresentationVersion } from "../lib/presentation";

/** Would order again, in the pipeline's own vocabulary (§13.1): complete's
 * green, in-transit's amber, and danger for no. */
const AGAIN_TONES: Record<WouldOrderAgain, string> = {
  yes: "text-status-complete",
  maybe: "text-status-in-transit",
  no: "text-danger",
};

interface RetailerFormValues {
  name: string;
  url: string;
  rating: string;
  packing_quality: PackingQuality | "";
  shipping_speed: ShippingSpeed | "";
  would_order_again: WouldOrderAgain | "";
  notes: string;
}

function RetailerFormModal({
  retailer,
  onClose,
}: {
  retailer?: Retailer;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<RetailerFormValues>({
    defaultValues: {
      name: retailer?.name ?? "",
      url: retailer?.url ?? "",
      rating: retailer?.rating?.toString() ?? "",
      packing_quality: retailer?.packing_quality ?? "",
      shipping_speed: retailer?.shipping_speed ?? "",
      would_order_again: retailer?.would_order_again ?? "",
      notes: retailer?.notes ?? "",
    },
  });

  const onSubmit = handleSubmit(async (values) => {
    const payload = {
      name: values.name,
      url: values.url || null,
      rating: values.rating === "" ? null : Number(values.rating),
      packing_quality: values.packing_quality || null,
      shipping_speed: values.shipping_speed || null,
      would_order_again: values.would_order_again || null,
      notes: values.notes || null,
    };
    try {
      await (retailer ? api.updateRetailer(retailer.id, payload) : api.createRetailer(payload));
      await queryClient.invalidateQueries({ queryKey: ["retailers"] });
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("common.requestFailed"));
    }
  });

  return (
    <Modal
      title={retailer ? t("retailers.editTitle", { name: retailer.name }) : t("retailers.addTitle")}
      onClose={onClose}
    >
      <form onSubmit={onSubmit} className="space-y-3">
        <ErrorBanner message={error} />
        <Field label={t("common.name")} required error={errors.name?.message}>
          <Input {...register("name", { required: t("validation.nameRequired") })} />
        </Field>
        <Field label={t("retailers.url")}>
          <Input {...register("url")} placeholder={t("common.urlPlaceholder")} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label={t("retailers.overallRating")} error={errors.rating?.message}>
            <Input
              type="number"
              min={1}
              max={5}
              placeholder="—"
              {...register("rating", {
                validate: (value) =>
                  value === "" ||
                  (Number(value) >= 1 && Number(value) <= 5) ||
                  t("validation.rating1to5"),
              })}
            />
          </Field>
          <Field label={t("retailers.wouldOrderAgain")}>
            <Select {...register("would_order_again")}>
              <option value="">—</option>
              {WOULD_ORDER_AGAIN.map((value) => (
                <option key={value} value={value}>
                  {wouldOrderAgainLabel(value)}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={t("retailers.packingQuality")}>
            <Select {...register("packing_quality")}>
              <option value="">—</option>
              {PACKING_QUALITIES.map((value) => (
                <option key={value} value={value}>
                  {packingQualityLabel(value)}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={t("retailers.shippingSpeed")}>
            <Select {...register("shipping_speed")}>
              <option value="">—</option>
              {SHIPPING_SPEEDS.map((value) => (
                <option key={value} value={value}>
                  {shippingSpeedLabel(value)}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <Field label={t("retailers.notes")}>
          <Textarea {...register("notes")} placeholder={t("retailers.notesPlaceholder")} />
        </Field>
        <div className="flex justify-end gap-2 pt-1">
          <Button type="button" variant="secondary" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" disabled={isSubmitting}>
            {retailer ? t("common.save") : t("common.add")}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

export function RetailersPage() {
  const { t } = useTranslation();
  // Rating tooltips are locale-formatted; see the note on `BoardPage`.
  usePresentationVersion();
  const queryClient = useQueryClient();
  const [modal, setModal] = useState<{ retailer?: Retailer } | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const {
    data: retailers,
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ["retailers"],
    queryFn: api.listRetailers,
  });

  const remove = async (retailer: Retailer) => {
    if (!window.confirm(t("common.confirmDelete", { name: retailer.name }))) return;
    setActionError(null);
    try {
      await api.deleteRetailer(retailer.id);
      await queryClient.invalidateQueries({ queryKey: ["retailers"] });
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : t("common.deleteFailed"));
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <PageTitle>{t("retailers.title")}</PageTitle>
        <div className="flex gap-2">
          <ExportCsvButton table="retailers" />
          <Button onClick={() => setModal({})}>{t("retailers.addButton")}</Button>
        </div>
      </div>

      <ErrorBanner message={actionError} />

      {isError ? (
        <ErrorBanner message={t("retailers.loadFailed", { message: (error as Error).message })} />
      ) : retailers?.length ? (
        <div className="overflow-x-auto rounded-md border border-border bg-surface">
          <table className="w-full text-sm">
            <thead>
              <tr className={TABLE_HEAD_ROW_CLASS}>
                <th className="px-3 py-2.5">{t("common.name")}</th>
                <th className="px-3 py-2.5">{t("retailers.headerRating")}</th>
                <th className="px-3 py-2.5">{t("retailers.headerPacking")}</th>
                <th className="px-3 py-2.5">{t("retailers.headerShipping")}</th>
                <th className="px-3 py-2.5">{t("retailers.headerAgain")}</th>
                <th className="px-3 py-2.5">{t("retailers.notes")}</th>
                <th className="px-3 py-2.5" />
              </tr>
            </thead>
            <tbody>
              {retailers.map((retailer) => (
                <tr key={retailer.id} className="border-b border-rule last:border-0">
                  <td className="px-3 py-2">
                    <div className="font-medium">{retailer.name}</div>
                    {retailer.url && (
                      <a
                        href={retailer.url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-xs text-accent hover:underline"
                      >
                        {retailer.url.replace(/^https?:\/\//, "")}
                      </a>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {retailer.rating ? (
                      <RatingStars rating={retailer.rating} title={ratingTooltip(retailer.rating)} />
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {retailer.packing_quality ? packingQualityLabel(retailer.packing_quality) : "—"}
                  </td>
                  <td className="px-3 py-2">
                    {retailer.shipping_speed ? shippingSpeedLabel(retailer.shipping_speed) : "—"}
                  </td>
                  <td className="px-3 py-2">
                    {retailer.would_order_again ? (
                      <Chip tone={AGAIN_TONES[retailer.would_order_again]}>
                        {wouldOrderAgainLabel(retailer.would_order_again)}
                      </Chip>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="max-w-48 truncate px-3 py-2 text-muted" title={retailer.notes ?? ""}>
                    {retailer.notes ?? "—"}
                  </td>
                  <td className="px-3 py-2 text-end">
                    <div className="flex justify-end gap-1">
                      <Button variant="secondary" onClick={() => setModal({ retailer })}>
                        {t("common.edit")}
                      </Button>
                      <Button variant="danger" onClick={() => remove(retailer)}>
                        {t("common.delete")}
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState>{isLoading ? t("common.loading") : t("retailers.empty")}</EmptyState>
      )}

      {modal && <RetailerFormModal retailer={modal.retailer} onClose={() => setModal(null)} />}
    </div>
  );
}
