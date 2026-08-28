/** resolveApiError (#25): known codes render through the catalogue, everything
 *  else falls back to the English the server sent — pinned byte-for-byte
 *  against the en-AU entries, with a sentinel detail so a pass can only come
 *  from the catalogue path, never from echoing the fallback.
 */
import { afterEach, describe, expect, it } from "vitest";

import { camelizeKey, resolveApiError, resolveDiagnostic } from "./apiError";
import { resetFormatPreferences, setFormatPreferences } from "./presentation";

// Deliberately nothing like any catalogue string: a test that sees this text in
// `message` is seeing the fallback path.
const SENTINEL = "backend english sentence — not catalogue copy";

afterEach(resetFormatPreferences);

describe("camelizeKey", () => {
  it("bridges snake_case wire params to camelCase placeholders", () => {
    expect(camelizeKey("on_hand")).toBe("onHand");
    expect(camelizeKey("limit_mb")).toBe("limitMb");
    expect(camelizeKey("supported_version")).toBe("supportedVersion");
    expect(camelizeKey("field")).toBe("field");
  });
});

describe("resolveApiError", () => {
  it("renders a known code through the catalogue, not the detail", () => {
    const resolved = resolveApiError("Conflict", {
      detail: SENTINEL,
      code: "order.already_received",
      params: {},
    });
    expect(resolved.message).toBe("This order is already marked received.");
    expect(resolved.detail).toBe(SENTINEL);
    expect(resolved.code).toBe("order.already_received");
  });

  it("interpolates camelized wire params into the rendering", () => {
    const resolved = resolveApiError("Conflict", {
      detail: SENTINEL,
      code: "stock.insufficient",
      params: { name: "GM02 Gundam Marker", on_hand: 1, requested: 3 },
    });
    expect(resolved.message).toBe(
      "Can't remove 3 × 'GM02 Gundam Marker' — only 1 on hand. Adjust its stock first.",
    );
  });

  it("selects the plural form by count", () => {
    const body = (count: number) => ({
      detail: SENTINEL,
      code: "retailer.has_orders",
      params: { name: "HLJ", count },
    });
    expect(resolveApiError("Conflict", body(1)).message).toBe(
      "'HLJ' has 1 order — order history is kept, so the retailer can't be deleted.",
    );
    expect(resolveApiError("Conflict", body(4)).message).toBe(
      "'HLJ' has 4 orders — order history is kept, so the retailer can't be deleted.",
    );
  });

  it("falls back to the detail for a code it doesn't know", () => {
    const resolved = resolveApiError("Conflict", {
      detail: SENTINEL,
      code: "future.condition",
      params: { anything: 1 },
    });
    expect(resolved.message).toBe(SENTINEL);
    // The code still travels — a caller switching on it is not the render path.
    expect(resolved.code).toBe("future.condition");
  });

  it("falls back to the detail for a pre-#25 body with no code", () => {
    const resolved = resolveApiError("Conflict", { detail: SENTINEL });
    expect(resolved.message).toBe(SENTINEL);
    expect(resolved.code).toBeNull();
    expect(resolved.params).toEqual({});
  });

  it("falls back to the status text for a non-JSON body", () => {
    const resolved = resolveApiError("Bad Gateway", null);
    expect(resolved.message).toBe("Bad Gateway");
    expect(resolved.detail).toBe("Bad Gateway");
    expect(resolved.code).toBeNull();
  });

  it("renders known request-validation findings through the catalogue while keeping detail", () => {
    const resolved = resolveApiError("Unprocessable Entity", {
      detail: [
        { loc: ["body", "name"], msg: "Field required", type: "missing" },
        { loc: ["body", "grade"], msg: "Field required", type: "missing" },
      ],
      code: "request.validation",
      params: {
        errors: [
          { field: "name", type: "missing" },
          { field: "grade", type: "missing" },
        ],
      },
    });
    expect(resolved.message).toBe("Name is required.; Grade is required.");
    expect(resolved.detail).toBe("name: Field required; grade: Field required");
    expect(resolved.code).toBe("request.validation");
  });

  it("keeps each original English finding when its future validation type is unknown", () => {
    const resolved = resolveApiError("Unprocessable Entity", {
      detail: [
        { loc: ["body", "name"], msg: "Field required", type: "missing" },
        { loc: ["body", "grade"], msg: "Unrecognised future rule", type: "future.rule" },
      ],
      code: "request.validation",
      params: {
        errors: [
          { field: "name", type: "missing" },
          { field: "grade", type: "future.rule" },
        ],
      },
    });
    expect(resolved.message).toBe("Name is required.; grade: Unrecognised future rule");
  });

  it("survives a params payload that isn't an object", () => {
    const resolved = resolveApiError("Conflict", {
      detail: SENTINEL,
      code: "order.already_shipped",
      params: [1, 2],
    });
    expect(resolved.params).toEqual({});
    expect(resolved.message).toBe("This order is already marked shipped.");
  });
});

describe("resolveDiagnostic (#26)", () => {
  it("renders a known code through the catalogue, not the detail", () => {
    const message = resolveDiagnostic({
      code: "import.cell_required",
      params: { field: "grade" },
      detail: SENTINEL,
    });
    expect(message).toBe("Grade is required.");
  });

  it("camelizes wire params into the rendering", () => {
    const message = resolveDiagnostic({
      code: "import.currency_without_amount",
      params: { field: "currency_code", amount_field: "unit_price_minor" },
      detail: SENTINEL,
    });
    expect(message).toBe(
      "Currency: ignored — this file has no Unit price (minor units) column, and a currency " +
        "can't be changed without restating the amount it applies to.",
    );
  });

  it("presents known import fields and tables while retaining canonical unknown values", () => {
    expect(
      resolveDiagnostic({
        code: "import.cell_required",
        params: { field: "build_completed_at" },
        detail: SENTINEL,
      }),
    ).toBe("Build completed is required.");
    expect(
      resolveDiagnostic({
        code: "import.match_ambiguous",
        params: { count: 2, table: "display_items" },
        detail: SENTINEL,
      }),
    ).toBe("2 existing Display items rows match this one — set the id column to say which one you mean.");
    expect(
      resolveDiagnostic({
        code: "import.catalog_ref_unresolved",
        params: { item_type: "display", table: "display_items" },
        detail: SENTINEL,
      }),
    ).toBe(
      "Catalog item: a display item line has to point at a row in Display items.csv — give it a Catalog item, " +
        "or name the item in Catalog item name and one will be created at 0 on hand.",
    );
    expect(
      resolveDiagnostic({
        code: "import.cell_required",
        params: { field: "future_field" },
        detail: SENTINEL,
      }),
    ).toBe("future_field is required.");
  });

  it("selects the plural form by count", () => {
    const diagnostic = (count: number) => ({
      code: "import.rows_unreadable",
      params: { count },
      detail: SENTINEL,
    });
    expect(resolveDiagnostic(diagnostic(1))).toBe(
      "1 row couldn't be read — nothing will be imported until it's fixed or removed.",
    );
    expect(resolveDiagnostic(diagnostic(4))).toBe(
      "4 rows couldn't be read — nothing will be imported until they're fixed or removed.",
    );
  });

  it("keeps plural selection numeric while rendering diagnostic counts in the formatting locale", () => {
    setFormatPreferences({
      formatting_locale: "de-DE",
      time_zone: "UTC",
      date_style: "locale",
      hour_cycle: "locale",
    });
    expect(
      resolveDiagnostic({
        code: "import.rows_unreadable",
        params: { count: 1234 },
        detail: SENTINEL,
      }),
    ).toBe("1.234 rows couldn't be read — nothing will be imported until they're fixed or removed.");
  });

  it("falls back to the detail for a code it doesn't know", () => {
    const message = resolveDiagnostic({
      code: "future.condition",
      params: { anything: 1 },
      detail: SENTINEL,
    });
    expect(message).toBe(SENTINEL);
  });
});
