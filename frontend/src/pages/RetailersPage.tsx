import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Search } from "lucide-react";
import { useMemo, useState } from "react";
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
  IconButton,
  Input,
  PageTitle,
  Pager,
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
import { paginate, usePageParam, useTextParam } from "../lib/listState";
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

/** Rows per page on the list pages (§13.4). */
const PAGE_SIZE = 10;

function RetailerFormModal({
  retailer,
  onClose,
  onDelete,
}: {
  retailer?: Retailer;
  onClose: () => void;
  /** Delete lives in the dialog, not on the row (§13.4). */
  onDelete?: (retailer: Retailer) => Promise<void>;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
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
        <div className="flex items-center gap-2 pt-1">
          {retailer && onDelete && (
            <Button
              type="button"
              variant="danger"
              className="me-auto"
              disabled={isSubmitting || deleting}
              onClick={async () => {
                if (!window.confirm(t("common.confirmDelete", { name: retailer.name }))) return;
                setError(null);
                setDeleting(true);
                try {
                  await onDelete(retailer);
                  onClose();
                } catch (err) {
                  setError(err instanceof ApiError ? err.message : t("common.deleteFailed"));
                } finally {
                  setDeleting(false);
                }
              }}
            >
              {t("common.delete")}
            </Button>
          )}
          <Button type="button" variant="secondary" className="ms-auto" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" disabled={isSubmitting || deleting}>
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
  // The search and the page are the URL (§13.4, #232).
  const [search, setSearch] = useTextParam("q", true);
  const [page, setPage] = usePageParam();
  const {
    data: retailers,
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ["retailers"],
    queryFn: api.listRetailers,
  });

  const removeRetailer = async (retailer: Retailer) => {
    await api.deleteRetailer(retailer.id);
    await queryClient.invalidateQueries({ queryKey: ["retailers"] });
  };

  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return retailers ?? [];
    return (retailers ?? []).filter((retailer) =>
      [retailer.name, retailer.url, retailer.notes]
        .filter((value): value is string => Boolean(value))
        .some((value) => value.toLowerCase().includes(needle)),
    );
  }, [retailers, search]);
  const paged = paginate(visible, page, PAGE_SIZE);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <PageTitle count={retailers === undefined ? undefined : visible.length}>
          {t("retailers.title")}
        </PageTitle>
        <div className="flex gap-2">
          <ExportCsvButton table="retailers" />
          <Button icon={Plus} onClick={() => setModal({})}>
            {t("retailers.addButton")}
          </Button>
        </div>
      </div>

      <div className="relative w-full max-w-xs">
        <Search
          size={15}
          aria-hidden
          className="pointer-events-none absolute start-2.5 top-1/2 -translate-y-1/2 text-faint"
        />
        <Input
          type="search"
          aria-label={t("common.search")}
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder={t("retailers.searchPlaceholder")}
          className="ps-8"
        />
      </div>

      {isError ? (
        <ErrorBanner message={t("retailers.loadFailed", { message: (error as Error).message })} />
      ) : paged.total > 0 ? (
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
              {paged.rows.map((retailer) => (
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
                  <td className="px-2 py-2 text-end">
                    <IconButton
                      label={t("common.editNamed", { name: retailer.name })}
                      onClick={() => setModal({ retailer })}
                    >
                      <Pencil size={15} aria-hidden />
                    </IconButton>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pager paged={paged} onPage={setPage} />
        </div>
      ) : (
        <EmptyState>
          {isLoading
            ? t("common.loading")
            : retailers?.length
              ? t("retailers.emptyFiltered")
              : t("retailers.empty")}
        </EmptyState>
      )}

      {modal && (
        <RetailerFormModal
          retailer={modal.retailer}
          onClose={() => setModal(null)}
          onDelete={removeRetailer}
        />
      )}
    </div>
  );
}
