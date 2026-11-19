/** Deep equality over form values: primitives, arrays and plain objects, which is
 *  all a react-hook-form value is. Strict on primitives, so the string "1" is not
 *  the number 1 — the comparison react-hook-form makes for its own dirty state.
 *
 *  What a dialog reads to decide whether a field is a change from what is stored
 *  (#358): the order dialog keeps its own record of that, because after a save
 *  that stored half of what it meant to, the form's opening values are no longer
 *  what is stored, and react-hook-form's `dirtyFields` only ever compares with
 *  those. */
export function sameValue(a: unknown, b: unknown): boolean {
  if (Object.is(a, b)) return true;
  if (a === null || b === null || typeof a !== "object" || typeof b !== "object") return false;
  if (Array.isArray(a) !== Array.isArray(b)) return false;
  const left = a as Record<string, unknown>;
  const right = b as Record<string, unknown>;
  const keys = Object.keys(left);
  if (keys.length !== Object.keys(right).length) return false;
  return keys.every((key) => Object.hasOwn(right, key) && sameValue(left[key], right[key]));
}
