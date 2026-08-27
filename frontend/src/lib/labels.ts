import type { ItemType, KitStatus } from "../api/types";
import i18n from "../i18n";

/** Catalogue-backed labels for canonical wire values (design §6.1): the
 * API/database value stays untranslated everywhere it travels; only what the
 * user reads resolves through the catalogue, keyed by the wire value verbatim
 * so the lookup is the identity function.
 *
 * Functions rather than maps on purpose — a `Record` filled at module scope
 * would call `t()` at import time and freeze the strings, which is an
 * init-order hazard today and a stale-language bug the moment #27 lets the
 * instance language change. `catalogue.test.ts` drives every enum member
 * through these, so a wire value without a catalogue entry cannot land. */

export function statusLabel(status: KitStatus): string {
  return i18n.t(`kitStatus.${status}`);
}

/** The singular noun — "display" the wire value reads as "display item" the
 * phrase, which also retires the raw-value chip OrdersPage used to render. */
export function itemTypeLabel(type: ItemType): string {
  return i18n.t(`itemType.${type}.singular`);
}

export function itemTypePlural(type: ItemType): string {
  return i18n.t(`itemType.${type}.plural`);
}
