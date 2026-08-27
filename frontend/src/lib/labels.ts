import type {
  ItemType,
  KitStatus,
  PackingQuality,
  RowAction,
  ShippingSpeed,
  WouldOrderAgain,
} from "../api/types";
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

/** "{{date}} · same day" / "{{date}} · N d" — the shape KitsPage's completed
 * column and OrdersPage's received column share (the date is pre-formatted;
 * only the elapsed phrasing lives in the catalogue). */
export function dateWithElapsed(date: string, days: number): string {
  return days <= 0
    ? i18n.t("common.elapsed.sameDay", { date })
    : i18n.t("common.elapsed.days", { date, count: days });
}

export function packingQualityLabel(quality: PackingQuality): string {
  return i18n.t(`packingQuality.${quality}`);
}

export function shippingSpeedLabel(speed: ShippingSpeed): string {
  return i18n.t(`shippingSpeed.${speed}`);
}

export function wouldOrderAgainLabel(answer: WouldOrderAgain): string {
  return i18n.t(`wouldOrderAgain.${answer}`);
}

/** The bare action word for a row badge; counted phrases ("3 new") come from
 * the `importCount.*` plural keys instead — a language may inflect the two
 * grammatical slots differently. */
export function importActionLabel(action: RowAction): string {
  return i18n.t(`importAction.${action}`);
}

/** Portable-table display name, falling back to the raw spec key so a table
 * the catalogue doesn't know yet still renders something true rather than a
 * dotted key. Keys are `portability/spec.py` table keys. Note the unified
 * vocabulary is wider than the preview's old private map: `display_items` and
 * `instance_settings` headings used to render as raw spec keys and now render
 * their labels (#163 review, P3-2 — sanctioned visible change). The
 * `exists`+`t` pattern here is safe only on flat keys — `exists` is false for
 * a plural base like `importCount.skip` even though `t` resolves it. */
export function importTableLabel(table: string): string {
  const key = `importTable.${table}`;
  return i18n.exists(key) ? i18n.t(key as "importTable.kits") : table;
}
