import type {
  CatalogSearchResult,
  Consumable,
  ConsumableCreate,
  ConsumableUpdate,
  ImportMode,
  ImportPlan,
  ImportResult,
  Kit,
  KitCreate,
  KitStatus,
  KitUpdate,
  Meta,
  Order,
  OrderCreate,
  OrderUpdate,
  Retailer,
  RetailerCreate,
  RetailerUpdate,
  Tool,
  ToolCreate,
  ToolUpdate,
  Upgrade,
  UpgradeApplication,
  UpgradeCreate,
  UpgradeUpdate,
} from "./types";

const API_BASE: string = import.meta.env.VITE_API_BASE ?? "/api";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") {
        detail = body.detail;
      } else if (Array.isArray(body.detail)) {
        detail = body.detail
          .map((d: { loc?: unknown[]; msg?: string }) =>
            [d.loc?.slice(1).join("."), d.msg].filter(Boolean).join(": "),
          )
          .join("; ");
      }
    } catch {
      // non-JSON error body — keep statusText
    }
    throw new ApiError(res.status, detail);
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
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // non-JSON error body — keep statusText
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

/** Pull a file down through fetch so an API error renders as a message rather
 *  than dumping a JSON error page into a download. */
export async function downloadFile(path: string, fallbackName: string): Promise<void> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    throw new ApiError(res.status, `Export failed (${res.status})`);
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
  updateKit: (id: string, data: KitUpdate) =>
    request<Kit>(`/kits/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  deleteKit: (id: string) => request<void>(`/kits/${id}`, { method: "DELETE" }),

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
  applyUpgrade: (upgradeId: string, data: { kit_id: string; quantity: number }) =>
    request<UpgradeApplication>(`/upgrades/${upgradeId}/apply`, post(data)),

  searchCatalog: (q: string) =>
    request<CatalogSearchResult[]>(`/catalog/search?q=${encodeURIComponent(q)}`),

  listRetailers: () => request<Retailer[]>("/retailers"),
  createRetailer: (data: RetailerCreate) => request<Retailer>("/retailers", post(data)),
  updateRetailer: (id: string, data: RetailerUpdate) =>
    request<Retailer>(`/retailers/${id}`, patch(data)),
  deleteRetailer: (id: string) => request<void>(`/retailers/${id}`, { method: "DELETE" }),

  getMeta: () => request<Meta>("/meta"),

  listOrders: () => request<Order[]>("/orders"),
  createOrder: (data: OrderCreate) => request<Order>("/orders", post(data)),
  updateOrder: (id: string, data: OrderUpdate) => request<Order>(`/orders/${id}`, patch(data)),
  receiveOrder: (id: string) => request<Order>(`/orders/${id}/receive`, { method: "POST" }),
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
