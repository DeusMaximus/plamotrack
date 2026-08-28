import type {
  CatalogSearchResult,
  Consumable,
  ConsumableCreate,
  ConsumableUpdate,
  DisplayItem,
  DisplayItemCreate,
  DisplayItemUpdate,
  ImportMode,
  ImportPlan,
  ImportResult,
  InstanceSettings,
  InstanceSettingsUpdate,
  Kit,
  KitCreate,
  KitStatus,
  KitUpdate,
  Meta,
  Order,
  OrderCreate,
  OrderReceive,
  OrderShip,
  OrderUpdate,
  Retailer,
  RetailerCreate,
  RetailerUpdate,
  StockAdjustment,
  Tool,
  ToolCreate,
  ToolUpdate,
  Upgrade,
  UpgradeApplication,
  UpgradeApplicationDetail,
  UpgradeCreate,
  UpgradeUpdate,
} from "./types";
import i18n from "../i18n";
import type { ApiErrorBody, ResolvedApiError } from "../lib/apiError";
import { resolveApiError } from "../lib/apiError";

const API_BASE: string = import.meta.env.VITE_API_BASE ?? "/api";

export class ApiError extends Error {
  status: number;
  /** Stable semantic code (`order.already_received`), or null when the body
   *  carried none — a proxy page, a non-JSON body, an older server. */
  code: string | null;
  /** The code's structured values, snake_case keys as sent on the wire. */
  params: Record<string, unknown>;
  /** The server's English fallback. `message` is the catalogue rendering when
   *  the code is known, so banners localise for free; this stays the raw text. */
  detail: string;

  constructor(status: number, resolved: string | ResolvedApiError) {
    const full: ResolvedApiError =
      typeof resolved === "string"
        ? { message: resolved, detail: resolved, code: null, params: {} }
        : resolved;
    super(full.message);
    this.name = "ApiError";
    this.status = status;
    this.code = full.code;
    this.params = full.params;
    this.detail = full.detail;
  }
}

/** One resolution for every failed response (#25) — request() and upload()
 *  must not grow separate opinions about the envelope. */
async function throwApiError(res: Response): Promise<never> {
  let body: ApiErrorBody | null = null;
  try {
    body = (await res.json()) as ApiErrorBody;
  } catch {
    // non-JSON error body — resolveApiError falls back to statusText
  }
  throw new ApiError(res.status, resolveApiError(res.statusText, body));
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    await throwApiError(res);
  }
  if (res.status === 204) {
    return undefined as T;
  }
  return (await res.json()) as T;
}

function post(body: unknown): RequestInit {
  return { method: "POST", body: JSON.stringify(body) };
}

function patch(body: unknown): RequestInit {
  return { method: "PATCH", body: JSON.stringify(body) };
}

/** Multipart POST — the browser sets its own boundary, so no Content-Type here. */
async function upload<T>(path: string, form: FormData): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { method: "POST", body: form });
  if (!res.ok) {
    await throwApiError(res);
  }
  return (await res.json()) as T;
}

/** Pull a file down through fetch so an API error renders as a message rather
 *  than dumping a JSON error page into a download. */
export async function downloadFile(path: string, fallbackName: string): Promise<void> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    throw new ApiError(res.status, i18n.t("api.exportFailed", { status: res.status }));
  }
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const name = /filename="?([^"]+)"?/.exec(disposition)?.[1] ?? fallbackName;
  const blobUrl = URL.createObjectURL(await res.blob());
  const link = document.createElement("a");
  link.href = blobUrl;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(blobUrl);
}

export const api = {
  listKits: (filters?: { status?: KitStatus | "" }) => {
    const params = new URLSearchParams();
    if (filters?.status) params.set("status", filters.status);
    const qs = params.size > 0 ? `?${params.toString()}` : "";
    return request<Kit[]>(`/kits${qs}`);
  },
  createKit: (data: KitCreate) => request<Kit>("/kits", post(data)),
  /** Distinct series values in use, most frequent first — the typeahead feed. */
  listKitSeries: () => request<string[]>("/kits/series"),
  updateKit: (id: string, data: KitUpdate) =>
    request<Kit>(`/kits/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  deleteKit: (id: string) => request<void>(`/kits/${id}`, { method: "DELETE" }),

  /** Distinct category values in use on one catalog table, most frequent first —
   *  the typeahead feed (#127; the listKitSeries shape). Per-table: a tool
   *  category and a consumable category are separate vocabularies. */
  listCategories: (table: "tools" | "consumables" | "display-items") =>
    request<string[]>(`/${table}/categories`),
  listTools: () => request<Tool[]>("/tools"),
  createTool: (data: ToolCreate) => request<Tool>("/tools", post(data)),
  updateTool: (id: string, data: ToolUpdate) => request<Tool>(`/tools/${id}`, patch(data)),
  deleteTool: (id: string) => request<void>(`/tools/${id}`, { method: "DELETE" }),
  listConsumables: () => request<Consumable[]>("/consumables"),
  createConsumable: (data: ConsumableCreate) => request<Consumable>("/consumables", post(data)),
  updateConsumable: (id: string, data: ConsumableUpdate) =>
    request<Consumable>(`/consumables/${id}`, patch(data)),
  deleteConsumable: (id: string) => request<void>(`/consumables/${id}`, { method: "DELETE" }),
  listUpgrades: () => request<Upgrade[]>("/upgrades"),
  createUpgrade: (data: UpgradeCreate) => request<Upgrade>("/upgrades", post(data)),
  updateUpgrade: (id: string, data: UpgradeUpdate) =>
    request<Upgrade>(`/upgrades/${id}`, patch(data)),
  deleteUpgrade: (id: string) => request<void>(`/upgrades/${id}`, { method: "DELETE" }),
  listDisplayItems: () => request<DisplayItem[]>("/display-items"),
  createDisplayItem: (data: DisplayItemCreate) =>
    request<DisplayItem>("/display-items", post(data)),
  updateDisplayItem: (id: string, data: DisplayItemUpdate) =>
    request<DisplayItem>(`/display-items/${id}`, patch(data)),
  deleteDisplayItem: (id: string) => request<void>(`/display-items/${id}`, { method: "DELETE" }),
  applyUpgrade: (upgradeId: string, data: { kit_id: string; quantity: number }) =>
    request<UpgradeApplication>(`/upgrades/${upgradeId}/apply`, post(data)),
  /** The applications recorded on one kit, oldest first (#61). */
  listKitApplications: (kitId: string) =>
    request<UpgradeApplicationDetail[]>(`/kits/${kitId}/applications`),
  /** Withdraw an application. `restoreStock` is required — no default anywhere,
   *  because whether the part physically survived is not inferable (§3.6). */
  withdrawUpgradeApplication: (upgradeId: string, applicationId: string, restoreStock: boolean) =>
    request<void>(
      `/upgrades/${upgradeId}/applications/${applicationId}?restore_stock=${restoreStock}`,
      { method: "DELETE" },
    ),

  searchCatalog: (q: string) =>
    request<CatalogSearchResult[]>(`/catalog/search?q=${encodeURIComponent(q)}`),
  /** Signed stock change, resolved across every catalog table server-side.
   *
   * Not a PATCH of `quantity_on_hand`: an absolute write has to read the number
   * first, and three writer types can move it in between (#35). */
  adjustStock: (id: string, delta: number, reason?: string) =>
    request<StockAdjustment>(`/catalog/${id}/adjust`, post({ delta, reason })),

  listRetailers: () => request<Retailer[]>("/retailers"),
  createRetailer: (data: RetailerCreate) => request<Retailer>("/retailers", post(data)),
  updateRetailer: (id: string, data: RetailerUpdate) =>
    request<Retailer>(`/retailers/${id}`, patch(data)),
  deleteRetailer: (id: string) => request<void>(`/retailers/${id}`, { method: "DELETE" }),

  getMeta: () => request<Meta>("/meta"),

  getSettings: () => request<InstanceSettings>("/settings"),
  updateSettings: (data: InstanceSettingsUpdate) =>
    request<InstanceSettings>("/settings", patch(data)),

  listOrders: () => request<Order[]>("/orders"),
  /** One order, fresh — what the editor hydrates from (#67): the list is a
   *  cache exactly as stale as the page is old. */
  getOrder: (id: string) => request<Order>(`/orders/${id}`),
  createOrder: (data: OrderCreate) => request<Order>("/orders", post(data)),
  updateOrder: (id: string, data: OrderUpdate) => request<Order>(`/orders/${id}`, patch(data)),
  receiveOrder: (id: string, data?: OrderReceive) =>
    request<Order>(`/orders/${id}/receive`, data ? post(data) : { method: "POST" }),
  shipOrder: (id: string, data?: OrderShip) =>
    request<Order>(`/orders/${id}/ship`, data ? post(data) : { method: "POST" }),
  deleteOrder: (id: string) => request<void>(`/orders/${id}`, { method: "DELETE" }),

  previewImport: (file: File, mode: ImportMode) => {
    const form = new FormData();
    form.append("file", file);
    form.append("mode", mode);
    return upload<ImportPlan>("/import/preview", form);
  },
  applyImport: (file: File, mode: ImportMode, planHash: string, confirm?: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("mode", mode);
    // Re-checked server-side: a mismatch means the collection moved under the preview.
    form.append("plan_hash", planHash);
    if (confirm) form.append("confirm", confirm);
    return upload<ImportResult>("/import/apply", form);
  },
};

/** Instance config: static for the life of the process, so fetch it once. Shared
 * key, so whichever page loads first warms the cache for every form that needs the
 * reference currency. Declared here rather than in a page — two copies would be two
 * cache keys the day one of them was edited. */
export const metaQuery = {
  queryKey: ["meta"],
  queryFn: api.getMeta,
  staleTime: Infinity,
} as const;

/** The instance-settings singleton (§6.1). Same shape and reasoning as
 * `metaQuery`: one shared key, fetched once, fresh until a save invalidates it.
 * A save must also invalidate `metaQuery` — `/meta` serves the same
 * `reference_currency`, and the order/inventory forms default from *that*. */
export const settingsQuery = {
  queryKey: ["settings"],
  queryFn: api.getSettings,
  staleTime: Infinity,
} as const;
