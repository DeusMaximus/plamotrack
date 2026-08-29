import i18n from "../i18n";
import { formatNumber } from "./format";
import { importFieldLabel, importTableLabel, itemTypeLabel, matchedByLabel } from "./labels";

/** Resolution of a failed response body into what the user reads (#25).
 *
 * The server's envelope is `{detail, code, params}` — `detail` the English
 * fallback (string for a domain refusal, FastAPI's findings list for request
 * validation), `code` a stable `<domain>.<condition>`, `params` snake_case
 * values. A known code renders through the catalogue (`api.<code>`, params
 * camelized to match the `{{placeholder}}` convention); everything else — an
 * unknown future code, a pre-#25 body, a proxy error page, a non-JSON body —
 * falls back exactly the way the client always did. The findings-list shape
 * findings list remains the English compatibility detail; structured findings
 * render through the active catalogue where their type is known.
 *
 * Pure and DOM-free on purpose: `apiError.test.ts` drives it under vitest's
 * node environment, and `client.ts` is the runtime caller.
 */

/** What a failed response body may hold. Everything optional — proxies and
 *  older servers send shapes this must survive. */
export interface ApiErrorBody {
  detail?: unknown;
  code?: unknown;
  params?: unknown;
}

export interface ResolvedApiError {
  /** What the user reads — catalogue rendering for a known code, else `detail`. */
  message: string;
  /** The English fallback the resolution started from. */
  detail: string;
  code: string | null;
  params: Record<string, unknown>;
}

/** snake_case → camelCase, the declared bridge between wire params and the
 *  catalogue's camelCase `{{placeholders}}` (`api-error-codes.json`'s note). */
export function camelizeKey(key: string): string {
  return key.replace(/_([a-z0-9])/g, (_, first: string) => first.toUpperCase());
}

/** One of FastAPI's 422 findings, as it arrives in `detail`. */
interface DetailFinding {
  loc?: unknown[];
  msg?: string;
  type?: unknown;
}

function detailFindings(body: ApiErrorBody): DetailFinding[] | null {
  return Array.isArray(body.detail) ? (body.detail as DetailFinding[]) : null;
}

/** The field path a finding names, spelled exactly the way the server spells it
 *  into `params.errors[].field`: `loc` minus its source element ("body",
 *  "query", "path"), dot-joined — so a nested `["body","items",0,"quantity"]`
 *  reads `items.0.quantity` on both sides (`app/main.py`'s handler).
 *
 *  `Array.isArray` rather than `?.`, because this module's whole contract is
 *  surviving bodies it did not expect: a `loc` that arrived as a string would
 *  slice happily and then throw on `join`. */
function findingPath(finding: DetailFinding): string | undefined {
  return Array.isArray(finding.loc) ? finding.loc.slice(1).join(".") : undefined;
}

/** One finding as the pre-#25 client wrote it: "field.path: message". */
function fallbackText(finding: DetailFinding): string {
  return [findingPath(finding), finding.msg].filter(Boolean).join(": ");
}

/** The pre-#25 fallback text, unchanged: string detail verbatim, a validation
 *  findings list joined field-by-field, anything else the HTTP status text. */
function fallbackFindings(body: ApiErrorBody): string[] | null {
  return detailFindings(body)?.map(fallbackText) ?? null;
}

function fallbackDetail(statusText: string, body: ApiErrorBody | null): string {
  if (body && typeof body.detail === "string") return body.detail;
  if (body) return fallbackFindings(body)?.join("; ") ?? statusText;
  return statusText;
}

export function resolveApiError(statusText: string, body: ApiErrorBody | null): ResolvedApiError {
  const detail = fallbackDetail(statusText, body);
  const code = body && typeof body.code === "string" ? body.code : null;
  const params =
    body && typeof body.params === "object" && body.params !== null && !Array.isArray(body.params)
      ? (body.params as Record<string, unknown>)
      : {};

  let message = detail;
  if (code === "request.validation" && body) {
    message = renderRequestValidation(params, detailFindings(body)) ?? detail;
  } else if (code !== null && !Array.isArray(body?.detail)) {
    message = renderCode(code, params) ?? detail;
  }
  return { message, detail, code, params };
}

/** Catalogue rendering for one wire code (`api.<code>`, params camelized), or
 *  null when the catalogue doesn't know it. Options are passed to `exists` too,
 *  so a plural entry (`…_one`/`…_other`) resolves by its `count`. The key is
 *  dynamic by design — unknown codes are the fallback path — so the typed-t
 *  compile check cannot apply here; the catalogue suite pins every registry
 *  code to an entry instead. */
function renderCode(code: string, params: Record<string, unknown>): string | null {
  const key = `api.${code}`;
  const options: Record<string, unknown> = {};
  for (const [param, value] of Object.entries(params)) {
    const key = camelizeKey(param);
    // i18next reads raw `count` to select its plural form. Only its rendered
    // companion is locale-formatted; turning count into text here would make
    // every plural catalogue entry appear absent.
    options[key] = param === "count" ? value : presentationValue(param, value);
    if (param === "count" && typeof value === "number") options.countDisplay = formatNumber(value);
  }
  const t = i18n.t as (key: string, options?: Record<string, unknown>) => string;
  return i18n.exists(key, options) ? t(key, options) : null;
}

/** The wire params that render as display labels, each with its labeller —
 * snake_case, because `renderCode` hands this the raw wire name.
 *
 * A table rather than a branch chain so it can be *held against the catalogue*:
 * a param whose camelized name no `api.*` entry interpolates is a branch
 * nothing can reach, and `apiError.test.ts` fails on one. That is what the
 * removed `action` and `matched_by` branches were (#177 review, P3-4 — both
 * mutants survived the entire suite): `action` is never a diagnostic param at
 * all and stays out, while `matched_by` was emitted on a code whose shared
 * catalogue entry could not name it. #178 split that code — the order
 * matcher's `import.order_match_ambiguous` declares `matched_by` and its entry
 * interpolates {{matchedBy}}, so the labeller is reachable and earns its row
 * back. */
export const LABELLED_PARAMS: Record<string, (value: string) => unknown> = {
  field: importFieldLabel,
  column: importFieldLabel,
  amount_field: importFieldLabel,
  table: importTableLabel,
  matched_by: matchedByLabel,
  item_type: (value) => {
    const key = `itemType.${value}.singular`;
    return i18n.exists(key) ? itemTypeLabel(value as never) : value;
  },
};

/** Known identifiers are display labels only at the browser boundary. The
 * values in `params`, the API body and CSV data remain canonical. */
function presentationValue(param: string, value: unknown): unknown {
  if (typeof value === "string") {
    const label = LABELLED_PARAMS[param];
    if (label) return label(value);
  }
  // Keep version/schema/id values and user-entered strings canonical. Other
  // numeric diagnostics are presentation quantities, so grouping follows the
  // instance locale just as it does in visible count phrases.
  if (typeof value === "number" && !["id", "schema", "version"].includes(param)) {
    return formatNumber(value);
  }
  return value;
}

interface RequestValidationFinding {
  field?: unknown;
  type?: unknown;
}

/** The server preserves FastAPI's English findings in `detail` for API
 * compatibility. Where its structured `{field, type}` companion names a known
 * type, render that finding through the active catalogue; a future type keeps
 * its matching English detail instead of being hidden behind a generic error.
 *
 * The two arrays are parallel by the handler's construction, and this refuses
 * to assume it: equal length is not correspondence (#177 review, P3-2). Each
 * structured item is trusted only where its `field` and `type` both equal what
 * the English finding beside it actually says — the same path spelling on both
 * sides — so a reordered, truncated or malformed companion degrades per item to
 * that item's English text rather than captioning it with another field's
 * message. Deliberately no sorting or re-pairing: which finding a structured
 * item belongs to is the server's to state, not this function's to guess. */
function renderRequestValidation(
  params: Record<string, unknown>,
  findings: DetailFinding[] | null,
): string | null {
  const errors = params.errors;
  if (!Array.isArray(errors) || !findings || errors.length !== findings.length) return null;
  const t = i18n.t as (key: string, options?: Record<string, unknown>) => string;
  const rendered = findings.map((finding, index) => {
    const fallback = fallbackText(finding);
    const error = errors[index];
    if (!error || typeof error !== "object") return fallback;
    const structured = error as RequestValidationFinding;
    if (typeof structured.field !== "string" || typeof structured.type !== "string") return fallback;
    if (structured.field !== (findingPath(finding) ?? "") || structured.type !== finding.type) {
      return fallback;
    }
    const key = `validation.request.${structured.type}`;
    return i18n.exists(key) ? t(key, { field: importFieldLabel(structured.field) }) : fallback;
  });
  return rendered.join("; ");
}

/** The #26 half of the same contract: an import-preview diagnostic renders
 *  through the catalogue exactly like a failed response's code, and an unknown
 *  future code falls back to the English `detail` the server sent. */
export function resolveDiagnostic(diagnostic: {
  code: string;
  params: Record<string, unknown>;
  detail: string;
}): string {
  return renderCode(diagnostic.code, diagnostic.params) ?? diagnostic.detail;
}
