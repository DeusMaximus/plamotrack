import type { KitStatus } from "../api/types";

/** The pipeline's six colours (§13.1), one token per status — the status chip's
 *  tone, and the dot on the filter sheet's toggle for it (§13.7). */
export const STATUS_TONES: Record<KitStatus, string> = {
  pre_ordered: "text-status-pre-ordered",
  ordered: "text-status-ordered",
  in_transit: "text-status-in-transit",
  backlog: "text-status-backlog",
  building: "text-status-building",
  complete: "text-status-complete",
};
