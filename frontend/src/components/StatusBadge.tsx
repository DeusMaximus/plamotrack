import type { KitStatus } from "../api/types";
import { statusLabel } from "../lib/labels";
import { STATUS_TONES } from "../lib/tones";
import { Chip } from "./ui";

export function StatusBadge({ status }: { status: KitStatus }) {
  return <Chip tone={STATUS_TONES[status]}>{statusLabel(status)}</Chip>;
}
