import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";

import { api, ApiError } from "../api/client";
import type { Kit, KitCreate, KitStatus, KitUpdate } from "../api/types";
import { KIT_STATUSES } from "../api/types";
import { Modal } from "../components/Modal";
import { StatusBadge } from "../components/StatusBadge";
import { Button, EmptyState, ErrorBanner, Field, Input, Select, Textarea } from "../components/ui";
import { formatDate, STATUS_LABELS } from "../lib/format";

const COMMON_GRADES = ["HG", "RG", "EG", "SD", "MG", "MGEX", "RE/100", "FM", "PG"];

interface KitFormValues {
  name: string;
  grade: string;
  scale: string;
  kit_number: string;
  status: KitStatus;
  rating: string;
  build_notes: string;
}

function toFormValues(kit?: Kit): KitFormValues {
  return {
    name: kit?.name ?? "",
    grade: kit?.grade ?? "",
    scale: kit?.scale ?? "",
    kit_number: kit?.kit_number ?? "",
    status: kit?.status ?? "backlog",
    rating: kit?.rating?.toString() ?? "",
    build_notes: kit?.build_notes ?? "",
  };
}

function KitFormModal({ kit, onClose }: { kit?: Kit; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<KitFormValues>({ defaultValues: toFormValues(kit) });

  const onSubmit = handleSubmit(async (values) => {
    const payload: KitCreate & KitUpdate = {
      name: values.name,
      grade: values.grade,
      scale: values.scale || null,
      kit_number: values.kit_number || null,
      status: values.status,
      build_notes: values.build_notes || null,
    };
    if (kit) {
      payload.rating = values.rating === "" ? null : Number(values.rating);
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
      setError(err instanceof ApiError ? err.message : "Request failed");
    }
  });

  return (
    <Modal title={kit ? `Edit ${kit.name}` : "Add kit"} onClose={onClose}>
      <form onSubmit={onSubmit} className="space-y-3">
        <ErrorBanner message={error} />
        <Field label="Name" required error={errors.name?.message}>
          <Input
            {...register("name", { required: "Name is required" })}
            placeholder="RX-79(G) Gundam Ground Type"
          />
        </Field>
        <div className="grid grid-cols-3 gap-3">
          <Field label="Grade" required error={errors.grade?.message}>
            <Input
              {...register("grade", { required: "Grade is required" })}
              list="common-grades"
              placeholder="HG"
            />
            <datalist id="common-grades">
              {COMMON_GRADES.map((grade) => (
                <option key={grade} value={grade} />
              ))}
            </datalist>
          </Field>
          <Field label="Scale">
            <Input {...register("scale")} placeholder="auto from grade" />
          </Field>
          <Field label="Kit number">
            <Input {...register("kit_number")} placeholder="HGUC 210" />
          </Field>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Status">
            <Select {...register("status")}>
              {KIT_STATUSES.map((status) => (
                <option key={status} value={status}>
                  {STATUS_LABELS[status]}
                </option>
              ))}
            </Select>
          </Field>
          {kit && (
            <Field label="Rating (1–5)" error={errors.rating?.message}>
              <Input
                type="number"
                min={1}
                max={5}
                {...register("rating", {
                  validate: (value) =>
                    value === "" ||
                    (Number(value) >= 1 && Number(value) <= 5) ||
                    "Rating is 1–5",
                })}
              />
            </Field>
          )}
        </div>
        <Field label="Build notes">
          <Textarea {...register("build_notes")} placeholder="Nub cleanup, panel lining…" />
        </Field>
        <div className="flex justify-end gap-2 pt-1">
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={isSubmitting}>
            {kit ? "Save" : "Add kit"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

export function KitsPage() {
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<KitStatus | "">("");
  const [search, setSearch] = useState("");
  const [modal, setModal] = useState<{ mode: "add" } | { mode: "edit"; kit: Kit } | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const {
    data: kits,
    isLoading,
    isError,
    error,
  } = useQuery({ queryKey: ["kits"], queryFn: () => api.listKits() });

  const statusMutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: KitStatus }) =>
      api.updateKit(id, { status }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["kits"] }),
    onError: (err) => setActionError(err instanceof ApiError ? err.message : "Update failed"),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.deleteKit(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["kits"] }),
    onError: (err) => setActionError(err instanceof ApiError ? err.message : "Delete failed"),
  });

  const visible = useMemo(() => {
    let rows = kits ?? [];
    if (statusFilter) rows = rows.filter((kit) => kit.status === statusFilter);
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      rows = rows.filter(
        (kit) =>
          kit.name.toLowerCase().includes(q) || (kit.kit_number ?? "").toLowerCase().includes(q),
      );
    }
    return rows;
  }, [kits, statusFilter, search]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-2xl font-bold">Kits</h1>
        <Button onClick={() => setModal({ mode: "add" })}>+ Add kit</Button>
      </div>

      <div className="flex gap-2">
        <Input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search name or kit number…"
          className="max-w-xs"
        />
        <Select
          value={statusFilter}
          onChange={(event) => setStatusFilter(event.target.value as KitStatus | "")}
          className="max-w-40"
        >
          <option value="">All statuses</option>
          {KIT_STATUSES.map((status) => (
            <option key={status} value={status}>
              {STATUS_LABELS[status]}
            </option>
          ))}
        </Select>
      </div>

      <ErrorBanner message={actionError} />

      {isError ? (
        <ErrorBanner message={`Failed to load kits: ${(error as Error).message}`} />
      ) : isLoading ? (
        <EmptyState>Loading…</EmptyState>
      ) : visible.length === 0 ? (
        <EmptyState>
          {kits?.length === 0
            ? "No kits yet — add one, or record an order and let it spawn them."
            : "Nothing matches the current filters."}
        </EmptyState>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-zinc-200 bg-white">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500">
                <th className="px-3 py-2">Kit</th>
                <th className="px-3 py-2">Grade</th>
                <th className="px-3 py-2">Scale</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Rating</th>
                <th className="px-3 py-2">Since</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {visible.map((kit) => (
                <tr key={kit.id} className="border-b border-zinc-100 last:border-0 hover:bg-zinc-50">
                  <td className="px-3 py-2">
                    <div className="font-medium">{kit.name}</div>
                    {kit.kit_number && <div className="text-xs text-zinc-400">{kit.kit_number}</div>}
                  </td>
                  <td className="px-3 py-2">{kit.grade}</td>
                  <td className="px-3 py-2">{kit.scale ?? "—"}</td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-2">
                      <StatusBadge status={kit.status} />
                      <Select
                        aria-label={`Change status of ${kit.name}`}
                        value={kit.status}
                        onChange={(event) =>
                          statusMutation.mutate({
                            id: kit.id,
                            status: event.target.value as KitStatus,
                          })
                        }
                        className="!w-auto !py-1 text-xs"
                      >
                        {KIT_STATUSES.map((status) => (
                          <option key={status} value={status}>
                            {STATUS_LABELS[status]}
                          </option>
                        ))}
                      </Select>
                    </div>
                  </td>
                  <td className="px-3 py-2">
                    {kit.rating ? "★".repeat(kit.rating) + "☆".repeat(5 - kit.rating) : "—"}
                  </td>
                  <td className="px-3 py-2 text-zinc-500" title="In this status since">
                    {formatDate(kit.status_updated_at)}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <div className="flex justify-end gap-1">
                      <Button variant="secondary" onClick={() => setModal({ mode: "edit", kit })}>
                        Edit
                      </Button>
                      <Button
                        variant="danger"
                        onClick={() => {
                          if (window.confirm(`Delete "${kit.name}"? This cannot be undone.`)) {
                            deleteMutation.mutate(kit.id);
                          }
                        }}
                      >
                        Delete
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
