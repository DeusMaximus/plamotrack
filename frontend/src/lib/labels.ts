import type {
  ItemType,
  KitStatus,
  PackingQuality,
  RowAction,
  ShippingSpeed,
  WouldOrderAgain,
} from "../api/types";
import i18n from "../i18n";
import { formatNumber } from "./format";

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

/** The Title-case noun a select option leads with ("Display item") — a third
 * form, not a code-side capitalisation of `.singular`: casing rules are the
 * language's business. */
export function itemTypeTitle(type: ItemType): string {
  return i18n.t(`itemType.${type}.title`);
}

/** "{{date}} · same day" / "{{date}} · N d" — the shape KitsPage's completed
 * column and OrdersPage's received column share (the date is pre-formatted;
 * only the elapsed phrasing lives in the catalogue). */
export function dateWithElapsed(date: string, days: number): string {
  return days <= 0
    ? i18n.t("common.elapsed.sameDay", { date })
    : countedPhrase("common.elapsed.days", days, { date });
}

/** The 1–5 scale both star renderings caption themselves with. A constant
 *  rather than a setting: the rating columns are `CHECK (rating BETWEEN 1 AND
 *  5)` in the schema. */
const RATING_MAXIMUM = 5;

/** "4/5" as a tooltip — both numbers through the instance's formatting locale,
 * because a rating is a quantity the user reads and ar-EG spells those
 * ٤/٥ (#177 review, P3-1). The separator lives in the catalogue so a language
 * can reorder or respell it; the stored rating is untouched. Shared by the
 * Board card and the Retailers table so the two cannot drift. */
export function ratingTooltip(rating: number): string {
  return i18n.t("common.ratingOutOf", {
    ratingDisplay: formatNumber(rating),
    maximumDisplay: formatNumber(RATING_MAXIMUM),
  });
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
 * grammatical slots differently.
 *
 * Same `exists`+raw fallback as the other protocol identifiers below, and for
 * the same reason: `RowAction` constrains this repo's callers, not the JSON a
 * newer backend sends, so an unrecognised action must render its canonical
 * wire value rather than the dotted catalogue key (#177 review, P3-3). Flat
 * keys, so the `exists` caveat on `importTableLabel` doesn't bite. */
export function importActionLabel(action: RowAction): string {
  const key = `importAction.${action}`;
  return i18n.exists(key) ? i18n.t(key as "importAction.create") : action;
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

/** The preview's `matched_by` identifier ("id", "name",
 * "retailer_order_number", ...) as a display phrase, falling back to the raw
 * identifier — the wire value is canonical and never translated (#26). The
 * natural-key values double as column names, which the rest of the preview
 * renders raw, so the fallback is already true rather than merely safe. */
export function matchedByLabel(matchedBy: string): string {
  const key = `matchedBy.${matchedBy}`;
  return i18n.exists(key) ? i18n.t(key as "matchedBy.id") : matchedBy;
}

/** A portable column or API field as a user-facing label. The canonical name
 * remains the wire and CSV value; an unknown future field deliberately falls
 * back to that value rather than producing a misleading invented label. */
export function importFieldLabel(field: string): string {
  const key = `importField.${field}`;
  return i18n.exists(key) ? i18n.t(key as "importField.name") : field;
}

/** Count interpolation always carries both forms: raw `count` remains the
 * i18next plural selector, while `countDisplay` is the locale-formatted text
 * rendered into the catalogue. Keeping those values separate prevents a locale
 * digit string from ever changing grammar. */
export function counted(values: Record<string, unknown>, count: number): Record<string, unknown> {
  return { ...values, count, countDisplay: formatNumber(count) };
}

export function countedPhrase(key: string, count: number, values: Record<string, unknown> = {}): string {
  const t = i18n.t as (key: string, options?: Record<string, unknown>) => string;
  return t(key, counted(values, count));
}
