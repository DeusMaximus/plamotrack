import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";

import { api, ApiError } from "../api/client";
import type {
  Kit,
  KitCreate,
  KitStatus,
  KitUpdate,
  UpgradeApplicationDetail,
} from "../api/types";
import { KIT_STATUSES } from "../api/types";
import { ExportCsvButton } from "../components/ExportCsvButton";
import { Modal } from "../components/Modal";
import { StatusBadge } from "../components/StatusBadge";
import { Button, EmptyState, ErrorBanner, Field, Input, Select, Textarea } from "../components/ui";
import { formatDate, isoToLocalDateInput, localMidnightISO } from "../lib/format";
import { dateWithElapsed, statusLabel } from "../lib/labels";
import { usePresentationVersion } from "../lib/presentation";

const COMMON_GRADES = ["HG", "RG", "EG", "SD", "MG", "MGEX", "RE/100", "FM", "PG"];

interface KitFormValues {
  name: string;
  grade: string;
  scale: string;
  kit_number: string;
  series: string;
  status: KitStatus;
  rating: string;
  /** yyyy-mm-dd, "" = none. Sent only when dirty: a date input can't restate the
   *  stored *instant* losslessly, so an untouched field must not round-trip (#94). */
  build_started: string;
  build_completed: string;
  build_notes: string;
}

function toFormValues(kit?: Kit): KitFormValues {
  return {
    name: kit?.name ?? "",
    grade: kit?.grade ?? "",
    scale: kit?.scale ?? "",
    kit_number: kit?.kit_number ?? "",
    series: kit?.series ?? "",
    status: kit?.status ?? "backlog",
    rating: kit?.rating?.toString() ?? "",
    build_started: kit?.build_started_at ? isoToLocalDateInput(kit.build_started_at) : "",
    build_completed: kit?.build_completed_at ? isoToLocalDateInput(kit.build_completed_at) : "",
    build_notes: kit?.build_notes ?? "",
  };
}

/** The completion cell: the date, and when a start exists too, the elapsed days
 *  beside it (deliberately elapsed, not time-at-the-bench — a shelved build reads
 *  long, and that is the documented shape of the two-column decision on #94). */
function completedCell(kit: Kit): string {
  if (!kit.build_completed_at) return "—";
  const date = formatDate(kit.build_completed_at);
  if (!kit.build_started_at) return date;
  const days = Math.round(
    (new Date(kit.build_completed_at).getTime() - new Date(kit.build_started_at).getTime()) /
      86_400_000,
  );
  return dateWithElapsed(date, days);
}

function KitFormModal({ kit, onClose }: { kit?: Kit; onClose: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting, dirtyFields },
  } = useForm<KitFormValues>({ defaultValues: toFormValues(kit) });

  // The de-dup device for a free-text column: what already exists, most frequent
  // first. staleTime 0 for the same reason as the catalog picker (#49/#108) — a
  // gate that answers from cache offers "new" for something that now exists.
  const { data: seriesValues } = useQuery({
    queryKey: ["kit-series"],
    queryFn: api.listKitSeries,
    staleTime: 0,
  });

  const onSubmit = handleSubmit(async (values) => {
    const payload: KitCreate & KitUpdate = {
      name: values.name,
      grade: values.grade,
      scale: values.scale || null,
      kit_number: values.kit_number || null,
      series: values.series || null,
      status: values.status,
      build_notes: values.build_notes || null,
    };
    if (kit) {
      payload.rating = values.rating === "" ? null : Number(values.rating);
    }
    // Only when touched (see KitFormValues). A typed date goes out as midnight
    // local in the browser's own offset; an emptied field clears the stored one.
    if (dirtyFields.build_started) {
      payload.build_started_at = values.build_started
        ? localMidnightISO(values.build_started)
        : null;
    }
    if (dirtyFields.build_completed) {
      payload.build_completed_at = values.build_completed
        ? localMidnightISO(values.build_completed)
        : null;
    }
    try {
      if (kit) {
        await api.updateKit(kit.id, payload);
      } else {
        await api.createKit(payload);
      }
      await queryClient.invalidateQueries({ queryKey: ["kits"] });
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("common.requestFailed"));
    }
  });

  return (
    <Modal
      title={kit ? t("kits.editTitle", { name: kit.name }) : t("kits.addTitle")}
      onClose={onClose}
    >
      <form onSubmit={onSubmit} className="space-y-3">
        <ErrorBanner message={error} />
        <Field label={t("common.name")} required error={errors.name?.message}>
          <Input
            {...register("name", { required: t("validation.nameRequired") })}
            placeholder={t("kits.namePlaceholder")}
          />
        </Field>
        <div className="grid grid-cols-3 gap-3">
          <Field label={t("kits.grade")} required error={errors.grade?.message}>
            <Input
              {...register("grade", { required: t("validation.gradeRequired") })}
              list="common-grades"
              placeholder={t("kits.gradePlaceholder")}
            />
            <datalist id="common-grades">
              {COMMON_GRADES.map((grade) => (
                <option key={grade} value={grade} />
              ))}
            </datalist>
          </Field>
          <Field label={t("kits.scale")}>
            <Input {...register("scale")} placeholder={t("kits.scalePlaceholder")} />
          </Field>
          <Field label={t("kits.kitNumber")}>
            <Input {...register("kit_number")} placeholder={t("kits.kitNumberPlaceholder")} />
          </Field>
        </div>
        <Field label={t("kits.series")}>
          <Input
            {...register("series")}
            list="kit-series"
            placeholder={t("kits.seriesPlaceholder")}
          />
          <datalist id="kit-series">
            {seriesValues?.map((value) => (
              <option key={value} value={value} />
            ))}
          </datalist>
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label={t("kits.status")}>
            <Select {...register("status")}>
              {KIT_STATUSES.map((status) => (
                <option key={status} value={status}>
                  {statusLabel(status)}
                </option>
              ))}
            </Select>
          </Field>
          {kit && (
            <Field label={t("kits.ratingLabel")} error={errors.rating?.message}>
              <Input
                type="number"
                min={1}
                max={5}
                {...register("rating", {
                  validate: (value) =>
                    value === "" ||
                    (Number(value) >= 1 && Number(value) <= 5) ||
                    t("validation.rating1to5"),
                })}
              />
            </Field>
          )}
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Field label={t("kits.buildStarted")}>
            <Input type="date" {...register("build_started")} />
          </Field>
          <Field label={t("kits.buildCompleted")}>
            <Input type="date" {...register("build_completed")} />
          </Field>
        </div>
        <p className="-mt-2 text-xs text-zinc-500">{t("kits.autoFillNote")}</p>
        <Field label={t("kits.buildNotes")}>
          <Textarea {...register("build_notes")} placeholder={t("kits.buildNotesPlaceholder")} />
        </Field>
        {kit && <AppliedUpgradesSection kitId={kit.id} />}
        <div className="flex justify-end gap-2 pt-1">
          <Button type="button" variant="secondary" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" disabled={isSubmitting}>
            {kit ? t("common.save") : t("kits.addSubmit")}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

/** The upgrade applications on this kit, each with its withdrawal control (#61).
 *
 * Withdrawing asks whether the stock returns as two equal-weight buttons rather
 * than a pre-ticked box: whether the part physically survived is a fact
 * plamotrack cannot know, and a default would be silently wrong half the time
 * (§3.6). Every button is type="button" — this renders inside the edit form.
 */
function AppliedUpgradesSection({ kitId }: { kitId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [withdrawing, setWithdrawing] = useState<UpgradeApplicationDetail | null>(null);
  const [submitting, setSubmitting] = useState(false);
  // staleTime 0 for the same reason as the series typeahead: an MCP agent can
  // apply or withdraw between two opens of this dialog.
  const { data: applications } = useQuery({
    queryKey: ["kit-applications", kitId],
    queryFn: () => api.listKitApplications(kitId),
    staleTime: 0,
  });

  if (!applications || applications.length === 0) return null;

  const withdraw = async (restoreStock: boolean) => {
    if (!withdrawing) return;
    setSubmitting(true);
    try {
      await api.withdrawUpgradeApplication(withdrawing.upgrade_id, withdrawing.id, restoreStock);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["kit-applications", kitId] }),
        queryClient.invalidateQueries({ queryKey: ["upgrades"] }),
      ]);
      setWithdrawing(null);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("kits.withdrawalFailed"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-2 rounded-md border border-zinc-200 p-3">
      <div className="text-xs font-semibold uppercase tracking-wide text-zinc-500">
        {t("kits.appliedUpgrades")}
      </div>
      <ErrorBanner message={error} />
      <ul className="space-y-1">
        {applications.map((application) => (
          <li key={application.id} className="flex items-center justify-between gap-2 text-sm">
            <span>
              {application.upgrade.name}
              {application.quantity_used > 1 && ` ×${application.quantity_used}`}
              <span className="text-xs text-zinc-400">
                {t("common.dotSeparator")}
                {formatDate(application.applied_at)}
              </span>
            </span>
            <Button
              type="button"
              variant="secondary"
              onClick={() => {
                setWithdrawing(application);
                setError(null);
              }}
            >
              {t("kits.withdrawButton")}
            </Button>
          </li>
        ))}
      </ul>
      {withdrawing && (
        <div className="space-y-2 rounded-md bg-zinc-50 p-2 text-sm">
          <p>
            {t("kits.withdrawPrompt", {
              name: withdrawing.upgrade.name,
              // "(×N)" is numeric notation composed here, not copy — the prompt
              // key interpolates it whole so the sentence stays one value.
              qty: withdrawing.quantity_used > 1 ? ` (×${withdrawing.quantity_used})` : "",
            })}
          </p>
          <div className="flex flex-wrap justify-end gap-2">
            <Button
              type="button"
              variant="secondary"
              onClick={() => setWithdrawing(null)}
              disabled={submitting}
            >
              {t("common.cancel")}
            </Button>
            <Button
              type="button"
              variant="danger"
              onClick={() => withdraw(false)}
              disabled={submitting}
            >
              {t("kits.withdrawSpent")}
            </Button>
            <Button
              type="button"
              variant="danger"
              onClick={() => withdraw(true)}
              disabled={submitting}
            >
              {t("kits.withdrawReturn")}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

export function KitsPage() {
  // Re-render when the instance's presentation settings arrive or change —
  // the plain format helpers below read them per call (#174 review, P3-1).
  usePresentationVersion();
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<KitStatus | "">("");
  const [seriesFilter, setSeriesFilter] = useState("");
  const [search, setSearch] = useState("");
  const [modal, setModal] = useState<{ mode: "add" } | { mode: "edit"; kit: Kit } | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const {
    data: kits,
    isLoading,
    isError,
    error,
  } = useQuery({ queryKey: ["kits"], queryFn: () => api.listKits() });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.deleteKit(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["kits"] }),
    onError: (err) =>
      setActionError(err instanceof ApiError ? err.message : t("common.deleteFailed")),
  });

  // Distinct series among the loaded kits, for the filter dropdown. Alphabetical:
  // a filter is scanned by eye, unlike the form's typeahead, which ranks by use.
  const seriesOptions = useMemo(() => {
    const values = new Set<string>();
    for (const kit of kits ?? []) if (kit.series) values.add(kit.series);
    return [...values].sort((a, b) => a.localeCompare(b));
  }, [kits]);

  const visible = useMemo(() => {
    let rows = kits ?? [];
    if (statusFilter) rows = rows.filter((kit) => kit.status === statusFilter);
    if (seriesFilter) rows = rows.filter((kit) => kit.series === seriesFilter);
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      rows = rows.filter(
        (kit) =>
          kit.name.toLowerCase().includes(q) || (kit.kit_number ?? "").toLowerCase().includes(q),
      );
    }
    return rows;
  }, [kits, statusFilter, seriesFilter, search]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-2xl font-bold">{t("kits.title")}</h1>
        <div className="flex gap-2">
          <ExportCsvButton table="kits" />
          <Button onClick={() => setModal({ mode: "add" })}>{t("kits.addButton")}</Button>
        </div>
      </div>

      <div className="flex gap-2">
        <Input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder={t("kits.searchPlaceholder")}
          className="max-w-xs"
        />
        <Select
          value={statusFilter}
          onChange={(event) => setStatusFilter(event.target.value as KitStatus | "")}
          className="max-w-40"
        >
          <option value="">{t("kits.allStatuses")}</option>
          {KIT_STATUSES.map((status) => (
            <option key={status} value={status}>
              {statusLabel(status)}
            </option>
          ))}
        </Select>
        {seriesOptions.length > 0 && (
          <Select
            aria-label={t("kits.filterBySeries")}
            value={seriesFilter}
            onChange={(event) => setSeriesFilter(event.target.value)}
            className="max-w-52"
          >
            <option value="">{t("kits.allSeries")}</option>
            {seriesOptions.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </Select>
        )}
      </div>

      <ErrorBanner message={actionError} />

      {isError ? (
        <ErrorBanner message={t("kits.loadFailed", { message: (error as Error).message })} />
      ) : isLoading ? (
        <EmptyState>{t("common.loading")}</EmptyState>
      ) : visible.length === 0 ? (
        <EmptyState>
          {kits?.length === 0 ? t("kits.emptyNone") : t("kits.emptyFiltered")}
        </EmptyState>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-zinc-200 bg-white">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-zinc-200 text-start text-xs uppercase tracking-wide text-zinc-500">
                <th className="px-3 py-2">{t("kits.headerKit")}</th>
                <th className="px-3 py-2">{t("kits.grade")}</th>
                <th className="px-3 py-2">{t("kits.scale")}</th>
                <th className="px-3 py-2">{t("kits.status")}</th>
                <th className="px-3 py-2">{t("kits.headerRating")}</th>
                <th className="px-3 py-2">{t("kits.headerStarted")}</th>
                <th className="px-3 py-2">{t("kits.headerCompleted")}</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {visible.map((kit) => (
                <tr key={kit.id} className="border-b border-zinc-100 last:border-0 hover:bg-zinc-50">
                  <td className="px-3 py-2">
                    <div className="font-medium">{kit.name}</div>
                    {(kit.kit_number || kit.series) && (
                      <div className="text-xs text-zinc-400">
                        {[kit.kit_number, kit.series]
                          .filter(Boolean)
                          .join(t("common.dotSeparator"))}
                      </div>
                    )}
                  </td>
                  <td className="px-3 py-2">{kit.grade}</td>
                  <td className="px-3 py-2">{kit.scale ?? "—"}</td>
                  {/* Display only (#120): status changes go through Edit, where the
                      dates, rating and notes a real transition travels with live. The
                      inline select this replaces invited a half-done change. */}
                  <td className="px-3 py-2">
                    <StatusBadge status={kit.status} />
                  </td>
                  <td className="px-3 py-2">
                    {kit.rating ? "★".repeat(kit.rating) + "☆".repeat(5 - kit.rating) : "—"}
                  </td>
                  <td className="px-3 py-2 text-zinc-500" title={t("kits.buildStarted")}>
                    {kit.build_started_at ? formatDate(kit.build_started_at) : "—"}
                  </td>
                  <td className="px-3 py-2 text-zinc-500" title={t("kits.completedTitle")}>
                    {completedCell(kit)}
                  </td>
                  <td className="px-3 py-2 text-end">
                    <div className="flex justify-end gap-1">
                      <Button variant="secondary" onClick={() => setModal({ mode: "edit", kit })}>
                        {t("common.edit")}
                      </Button>
                      <Button
                        variant="danger"
                        onClick={() => {
                          if (window.confirm(t("kits.confirmDelete", { name: kit.name }))) {
                            deleteMutation.mutate(kit.id);
                          }
                        }}
                      >
                        {t("common.delete")}
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {modal && (
        <KitFormModal
          kit={modal.mode === "edit" ? modal.kit : undefined}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
