import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";

import { api, ApiError } from "../api/client";
import type { Kit, KitCreate, KitStatus, KitUpdate, UpgradeApplicationDetail } from "../api/types";
import { KIT_STATUSES } from "../api/types";
import { formatDate, formatNumber, isoToLocalDateInput, localMidnightISO } from "../lib/format";
import { invalidateKitViews } from "../lib/invalidate";
import { statusLabel } from "../lib/labels";
import { Modal } from "./Modal";
import {
  Button,
  ErrorBanner,
  Field,
  Input,
  MICRO_LABEL_CLASS,
  Select,
  Textarea,
} from "./ui";

/** The kit dialog (add or edit), shared by the Kits page and Home (#233):
 *  every edit control in the app opens this one form, so a status change
 *  travels with the dates, rating and notes a real transition carries (#120)
 *  wherever it is made from. */

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

/** Add or edit one kit. Delete lives here, not on the row (§13.4): the row's
 *  one control opens this dialog, and the destructive action sits next to the
 *  fields it destroys, behind the same confirmation as before. */
export function KitFormModal({
  kit,
  onClose,
  onDelete,
}: {
  kit?: Kit;
  onClose: () => void;
  onDelete?: (kit: Kit) => Promise<void>;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
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
      await invalidateKitViews(queryClient);
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
        <p className="-mt-2 text-xs text-muted">{t("kits.autoFillNote")}</p>
        <Field label={t("kits.buildNotes")}>
          <Textarea {...register("build_notes")} placeholder={t("kits.buildNotesPlaceholder")} />
        </Field>
        {kit && <AppliedUpgradesSection kitId={kit.id} />}
        <div className="flex items-center gap-2 pt-1">
          {kit && onDelete && (
            <Button
              type="button"
              variant="danger"
              className="me-auto"
              disabled={isSubmitting || deleting}
              onClick={async () => {
                if (!window.confirm(t("kits.confirmDelete", { name: kit.name }))) return;
                setError(null);
                setDeleting(true);
                try {
                  await onDelete(kit);
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
    <div className="space-y-2 rounded-sm border border-border p-3">
      <div className={MICRO_LABEL_CLASS}>
        {t("kits.appliedUpgrades")}
      </div>
      <ErrorBanner message={error} />
      <ul className="space-y-1">
        {applications.map((application) => (
          <li key={application.id} className="flex items-center justify-between gap-2 text-sm">
            <span>
              {application.upgrade.name}
              {application.quantity_used > 1 && ` ×${formatNumber(application.quantity_used)}`}
              <span className="text-xs text-muted">
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
        <div className="space-y-2 rounded-sm bg-surface-alt p-2 text-sm">
          <p>
            {t("kits.withdrawPrompt", {
              name: withdrawing.upgrade.name,
              // "(×N)" is numeric notation composed here, not copy — the prompt
              // key interpolates it whole so the sentence stays one value.
              qty: withdrawing.quantity_used > 1 ? ` (×${formatNumber(withdrawing.quantity_used)})` : "",
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
