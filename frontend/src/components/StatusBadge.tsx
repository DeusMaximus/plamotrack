import type { KitStatus } from "../api/types";
import { statusLabel } from "../lib/labels";
import { Chip } from "./ui";

/** The pipeline's six colours (§13.1), one token per status. */
const STATUS_TONES: Record<KitStatus, string> = {
  pre_ordered: "text-status-pre-ordered",
  ordered: "text-status-ordered",
  in_transit: "text-status-in-transit",
  backlog: "text-status-backlog",
  building: "text-status-building",
  complete: "text-status-complete",
};

export function StatusBadge({ status }: { status: KitStatus }) {
  return <Chip tone={STATUS_TONES[status]}>{statusLabel(status)}</Chip>;
}
