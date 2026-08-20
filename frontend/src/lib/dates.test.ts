/** The receipt-date helpers (#93).
 *
 * `localMidnightISO` writes the browser's own offset out rather than folding the
 * instant into UTC, because the server judges "is this future?" as a calendar
 * date in the instant's *own* offset — a picked date converted to Z shifts the
 * asserted calendar date for half the world. The offset-formatting cases pin the
 * fiddly half (sign, padding, half-hour zones); the round trips pin the pair of
 * helpers against each other in whatever time zone the test machine runs.
 */
import { expect, test } from "vitest";

import { isoToLocalDateInput, localMidnightISO } from "./format";

test.each([
  { offset: 600, expected: "2026-05-04T00:00:00+10:00" }, // AEST
  { offset: -420, expected: "2026-05-04T00:00:00-07:00" }, // PDT
  { offset: 330, expected: "2026-05-04T00:00:00+05:30" }, // half-hour zone
  { offset: 0, expected: "2026-05-04T00:00:00+00:00" }, // UTC keeps a real offset, not Z
  { offset: -30, expected: "2026-05-04T00:00:00-00:30" }, // both parts need padding
])("localMidnightISO writes offset $offset as $expected", ({ offset, expected }) => {
  expect(localMidnightISO("2026-05-04", offset)).toBe(expected);
});

// In the machine's own time zone, whatever it is: midnight local on a date is
// still that date when read back onto the local calendar.
test.each(["2026-05-04", "2026-01-01", "2026-12-31", "2024-02-29"])(
  "local midnight of %s round-trips through the local calendar",
  (date) => {
    expect(isoToLocalDateInput(localMidnightISO(date))).toBe(date);
    const parsed = new Date(localMidnightISO(date));
    expect(parsed.getFullYear()).toBe(Number(date.slice(0, 4)));
    expect(parsed.getMonth() + 1).toBe(Number(date.slice(5, 7)));
    expect(parsed.getDate()).toBe(Number(date.slice(8, 10)));
  },
);
