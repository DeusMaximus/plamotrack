/** resolveApiError (#25): known codes render through the catalogue, everything
 *  else falls back to the English the server sent — pinned byte-for-byte
 *  against the en-AU entries, with a sentinel detail so a pass can only come
 *  from the catalogue path, never from echoing the fallback.
 */
import { describe, expect, it } from "vitest";

import { camelizeKey, resolveApiError } from "./apiError";

// Deliberately nothing like any catalogue string: a test that sees this text in
// `message` is seeing the fallback path.
const SENTINEL = "backend english sentence — not catalogue copy";

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

  it("keeps the joined findings for request validation — specifics beat a generic line", () => {
    const resolved = resolveApiError("Unprocessable Entity", {
      detail: [
        { loc: ["body", "name"], msg: "Field required", type: "missing" },
        { loc: ["body", "grade"], msg: "Field required", type: "missing" },
      ],
      code: "request.validation",
      params: { errors: [{ field: "name", type: "missing" }] },
    });
    expect(resolved.message).toBe("name: Field required; grade: Field required");
    expect(resolved.code).toBe("request.validation");
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
