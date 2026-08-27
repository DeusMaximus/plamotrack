import type { KitStatus } from "../api/types";
import { statusLabel } from "../lib/labels";

const STATUS_STYLES: Record<KitStatus, string> = {
  pre_ordered: "bg-purple-100 text-purple-700",
  ordered: "bg-blue-100 text-blue-700",
  in_transit: "bg-amber-100 text-amber-700",
  backlog: "bg-teal-100 text-teal-700", // inherited in_hand's teal in the merge
  building: "bg-orange-100 text-orange-700",
  complete: "bg-green-100 text-green-700",
};

export function StatusBadge({ status }: { status: KitStatus }) {
  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[status]}`}
    >
      {statusLabel(status)}
    </span>
  );
}
