import i18n from "../i18n";
import { formatNumber } from "./format";
import { importActionLabel, importFieldLabel, importTableLabel, itemTypeLabel, matchedByLabel } from "./labels";

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

/** The pre-#25 fallback text, unchanged: string detail verbatim, a validation
 *  findings list joined field-by-field, anything else the HTTP status text. */
function fallbackFindings(body: ApiErrorBody): string[] | null {
  if (!Array.isArray(body.detail)) return null;
  return body.detail.map((finding: { loc?: unknown[]; msg?: string }) =>
    [finding.loc?.slice(1).join("."), finding.msg].filter(Boolean).join(": "),
  );
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
    message = renderRequestValidation(params, fallbackFindings(body)) ?? detail;
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

/** Known identifiers are display labels only at the browser boundary. The
 * values in `params`, the API body and CSV data remain canonical. */
function presentationValue(param: string, value: unknown): unknown {
  if (typeof value === "string") {
    if (["field", "column", "amount_field"].includes(param)) return importFieldLabel(value);
    if (param === "table") return importTableLabel(value);
    if (param === "action") return importActionLabel(value as never);
    if (["matched_by", "matchedBy"].includes(param)) return matchedByLabel(value);
    if (["item_type", "itemType"].includes(param)) {
      const key = `itemType.${value}.singular`;
      return i18n.exists(key) ? itemTypeLabel(value as never) : value;
    }
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
 * its matching English detail instead of being hidden behind a generic error. */
function renderRequestValidation(
  params: Record<string, unknown>,
  fallback: string[] | null,
): string | null {
  const errors = params.errors;
  if (!Array.isArray(errors) || !fallback || errors.length !== fallback.length) return null;
  const rendered = errors.map((error, index) => {
    if (!error || typeof error !== "object") return fallback[index];
    const finding = error as RequestValidationFinding;
    if (typeof finding.field !== "string" || typeof finding.type !== "string") return fallback[index];
    const key = `validation.request.${finding.type}`;
    const t = i18n.t as (key: string, options?: Record<string, unknown>) => string;
    return i18n.exists(key) ? t(key, { field: importFieldLabel(finding.field) }) : fallback[index];
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
