import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { api, ApiError } from "../api/client";
import type { PackingQuality, Retailer, ShippingSpeed, WouldOrderAgain } from "../api/types";
import { PACKING_QUALITIES, SHIPPING_SPEEDS, WOULD_ORDER_AGAIN } from "../api/types";
import { Modal } from "../components/Modal";
import { Button, EmptyState, ErrorBanner, Field, Input, Select, Textarea } from "../components/ui";

const PACKING_LABELS: Record<PackingQuality, string> = {
  excellent: "Excellent",
  good: "Good",
  average: "Average",
  below_average: "Below Average",
  poor: "Poor",
};

const SPEED_LABELS: Record<ShippingSpeed, string> = {
  very_fast: "Very Fast",
  fast: "Fast",
  average: "Average",
  slow: "Slow",
  very_slow: "Very Slow",
};

const AGAIN_LABELS: Record<WouldOrderAgain, string> = {
  yes: "Yes",
  maybe: "Maybe",
  no: "No",
};

const AGAIN_STYLES: Record<WouldOrderAgain, string> = {
  yes: "bg-green-100 text-green-700",
  maybe: "bg-amber-100 text-amber-700",
  no: "bg-red-100 text-red-700",
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
      setError(err instanceof ApiError ? err.message : "Request failed");
    }
  });

  return (
    <Modal title={retailer ? `Edit ${retailer.name}` : "Add retailer"} onClose={onClose}>
      <form onSubmit={onSubmit} className="space-y-3">
        <ErrorBanner message={error} />
        <Field label="Name" required error={errors.name?.message}>
          <Input {...register("name", { required: "Name is required" })} />
        </Field>
        <Field label="URL">
          <Input {...register("url")} placeholder="https://…" />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Overall rating (1–5)" error={errors.rating?.message}>
            <Input
              type="number"
              min={1}
              max={5}
              placeholder="—"
              {...register("rating", {
                validate: (value) =>
                  value === "" || (Number(value) >= 1 && Number(value) <= 5) || "Rating is 1–5",
              })}
            />
          </Field>
          <Field label="Would order again">
            <Select {...register("would_order_again")}>
              <option value="">—</option>
              {WOULD_ORDER_AGAIN.map((value) => (
                <option key={value} value={value}>
                  {AGAIN_LABELS[value]}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Packing quality">
            <Select {...register("packing_quality")}>
              <option value="">—</option>
              {PACKING_QUALITIES.map((value) => (
                <option key={value} value={value}>
                  {PACKING_LABELS[value]}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Shipping speed">
            <Select {...register("shipping_speed")}>
              <option value="">—</option>
              {SHIPPING_SPEEDS.map((value) => (
                <option key={value} value={value}>
                  {SPEED_LABELS[value]}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <Field label="Notes">
          <Textarea
            {...register("notes")}
            placeholder="Anything else — shipping quirks, coupon codes…"
          />
        </Field>
        <div className="flex justify-end gap-2 pt-1">
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={isSubmitting}>
            {retailer ? "Save" : "Add"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

export function RetailersPage() {
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
    if (!window.confirm(`Delete "${retailer.name}"?`)) return;
    setActionError(null);
    try {
      await api.deleteRetailer(retailer.id);
      await queryClient.invalidateQueries({ queryKey: ["retailers"] });
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Delete failed");
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-2xl font-bold">Retailers</h1>
        <Button onClick={() => setModal({})}>+ Add retailer</Button>
      </div>

      <ErrorBanner message={actionError} />

      {isError ? (
        <ErrorBanner message={`Failed to load retailers: ${(error as Error).message}`} />
      ) : retailers?.length ? (
        <div className="overflow-x-auto rounded-lg border border-zinc-200 bg-white">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500">
                <th className="px-3 py-2">Name</th>
                <th className="px-3 py-2">Rating</th>
                <th className="px-3 py-2">Packing</th>
                <th className="px-3 py-2">Shipping</th>
                <th className="px-3 py-2">Again?</th>
                <th className="px-3 py-2">Notes</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {retailers.map((retailer) => (
                <tr key={retailer.id} className="border-b border-zinc-100 last:border-0">
                  <td className="px-3 py-2">
                    <div className="font-medium">{retailer.name}</div>
                    {retailer.url && (
                      <a
                        href={retailer.url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-xs text-indigo-600 hover:underline"
                      >
                        {retailer.url.replace(/^https?:\/\//, "")}
                      </a>
                    )}
                  </td>
                  <td className="px-3 py-2" title={retailer.rating ? `${retailer.rating}/5` : ""}>
                    {retailer.rating
                      ? "★".repeat(retailer.rating) + "☆".repeat(5 - retailer.rating)
                      : "—"}
                  </td>
                  <td className="px-3 py-2">
                    {retailer.packing_quality ? PACKING_LABELS[retailer.packing_quality] : "—"}
                  </td>
                  <td className="px-3 py-2">
                    {retailer.shipping_speed ? SPEED_LABELS[retailer.shipping_speed] : "—"}
                  </td>
                  <td className="px-3 py-2">
                    {retailer.would_order_again ? (
                      <span
                        className={`rounded-full px-2 py-0.5 text-xs font-medium ${AGAIN_STYLES[retailer.would_order_again]}`}
                      >
                        {AGAIN_LABELS[retailer.would_order_again]}
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="max-w-48 truncate px-3 py-2 text-zinc-500" title={retailer.notes ?? ""}>
                    {retailer.notes ?? "—"}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <div className="flex justify-end gap-1">
                      <Button variant="secondary" onClick={() => setModal({ retailer })}>
                        Edit
                      </Button>
                      <Button variant="danger" onClick={() => remove(retailer)}>
                        Delete
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState>{isLoading ? "Loading…" : "No retailers yet — add where you buy."}</EmptyState>
      )}

      {modal && <RetailerFormModal retailer={modal.retailer} onClose={() => setModal(null)} />}
    </div>
  );
}
