/** A list page's state lives in the URL (design §13.4, #232): the filter, the
 *  sort, the search and the page are query parameters, so a "view all" link
 *  from Home is a page state and so is a bookmark. The readers below are pure
 *  and total — anything the URL might hold (missing, empty, garbage, a page
 *  past the end) reads as the default rather than as an error — and the hooks
 *  wrap them in `useSearchParams`, dropping a parameter again when it returns
 *  to its default so a clean URL stays clean. Changing a filter, the sort or
 *  the search resets the page: the page was a position in a list that no
 *  longer exists. */

import { useCallback } from "react";
import { useSearchParams } from "react-router-dom";

export const PAGE_PARAM = "page";

/** One of an allowed set, else the fallback — the value axis a link can carry. */
export function readEnum<T extends string>(
  raw: string | null,
  allowed: readonly T[],
  fallback: T,
): T {
  return raw !== null && (allowed as readonly string[]).includes(raw) ? (raw as T) : fallback;
}

/** A positive page number, else 1. */
export function readPage(raw: string | null): number {
  if (raw === null || !/^\d{1,6}$/.test(raw)) return 1;
  const page = Number(raw);
  return page >= 1 ? page : 1;
}

export type Paged<T> = {
  rows: T[];
  total: number;
  /** The page shown — the requested one clamped into the list. */
  page: number;
  pages: number;
  /** 1-based positions of the first and last row shown, 0–0 for an empty list. */
  from: number;
  to: number;
};

/** The slice of `rows` for `page`, clamping a page past the end onto the last
 *  one so a bookmark outlives a shrinking list. */
export function paginate<T>(rows: readonly T[], page: number, pageSize: number): Paged<T> {
  const total = rows.length;
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const shown = Math.min(Math.max(1, page), pages);
  const start = (shown - 1) * pageSize;
  const slice = rows.slice(start, start + pageSize);
  return {
    rows: slice,
    total,
    page: shown,
    pages,
    from: total === 0 ? 0 : start + 1,
    to: total === 0 ? 0 : start + slice.length,
  };
}

/** The pager's labels: every page when few, else the ends and a window around
 *  the current page with `null` for each gap — "1 2 3 4 5 … 11". */
export function pageWindow(page: number, pages: number): (number | null)[] {
  if (pages <= 7) return Array.from({ length: pages }, (_, index) => index + 1);
  const around = new Set([1, 2, pages - 1, pages, page - 1, page, page + 1]);
  if (page <= 4) for (let n = 1; n <= 5; n += 1) around.add(n);
  if (page >= pages - 3) for (let n = pages - 4; n <= pages; n += 1) around.add(n);
  const sorted = [...around].filter((n) => n >= 1 && n <= pages).sort((a, b) => a - b);
  const out: (number | null)[] = [];
  for (const n of sorted) {
    const previous = out[out.length - 1];
    if (typeof previous === "number" && n - previous > 1) out.push(null);
    out.push(n);
  }
  return out;
}

type Setter<T> = (next: T) => void;

/** Write several parameters in one navigation — `null` removes one. Two
 *  single-key writes in one handler would not compose: React Router's
 *  functional updater reads the params of the render, not of the previous
 *  call, so the second would overwrite the first. `replace` keeps a search
 *  box's keystrokes out of the history. */
export function useWriteParams(): (
  changes: Record<string, string | null>,
  options?: { replace?: boolean },
) => void {
  const [, setParams] = useSearchParams();
  return useCallback(
    (changes, options) => {
      setParams(
        (current) => {
          const params = new URLSearchParams(current);
          for (const [key, value] of Object.entries(changes)) {
            if (value === null) params.delete(key);
            else params.set(key, value);
          }
          return params;
        },
        { replace: options?.replace ?? false },
      );
    },
    [setParams],
  );
}

/** Write one parameter, dropping it at its default and resetting the page. */
function useParamWriter(key: string, fallback: string, replace: boolean): Setter<string> {
  const write = useWriteParams();
  return useCallback(
    (next: string) => {
      const changes: Record<string, string | null> = { [key]: next === fallback ? null : next };
      if (key !== PAGE_PARAM) changes[PAGE_PARAM] = null;
      write(changes, { replace });
    },
    [key, fallback, replace, write],
  );
}

/** A parameter with a closed vocabulary — a status, a sort. */
export function useEnumParam<T extends string>(
  key: string,
  allowed: readonly T[],
  fallback: T,
): [T, Setter<T>] {
  const [params] = useSearchParams();
  const write = useParamWriter(key, fallback, false);
  return [readEnum(params.get(key), allowed, fallback), write as Setter<T>];
}

/** A free-text parameter — a search, a series, a retailer id, a category. */
export function useTextParam(key: string, replace = false): [string, Setter<string>] {
  const [params] = useSearchParams();
  const write = useParamWriter(key, "", replace);
  return [params.get(key) ?? "", write];
}

/** The page, 1-based; setting 1 removes the parameter. */
export function usePageParam(): [number, Setter<number>] {
  const [params] = useSearchParams();
  const write = useParamWriter(PAGE_PARAM, "1", false);
  return [readPage(params.get(PAGE_PARAM)), useCallback((next: number) => write(String(next)), [write])];
}
