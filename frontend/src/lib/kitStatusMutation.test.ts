/** Issue #50: two board moves of one card must reach the server in the order they
 *  were made, and a failed move must put back only the card it moved.
 *
 *  Both are ordering properties, and ordering is what a single move can never
 *  show. Driven here rather than through Playwright because the browser test
 *  could not tell the two outcomes apart: dnd-kit's `DragOverlay` swallows a
 *  gesture that begins before the previous drop animation ends, so the second
 *  drag simply never happened — which produces one request, in order, and looks
 *  exactly like the serialisation working. Measured at 1 pass in 5, and adding a
 *  `console.log` to the drag handlers flipped it to passing. A test whose result
 *  moves when you observe it is not evidence.
 */
import { MutationObserver, QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import type { Kit, KitStatus } from "../api/types";
import { kitStatusMutationOptions } from "./kitStatusMutation";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return { ...actual, api: { ...actual.api, updateKit: vi.fn() } };
});

function kit(id: string, status: KitStatus): Kit {
  return {
    id,
    name: `Kit ${id}`,
    grade: "HG",
    scale: "1/144",
    kit_number: null,
    status,
    status_updated_at: "2026-08-01T00:00:00Z",
    rating: null,
    build_notes: null,
    order_item_id: null,
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function clientWith(kits: Kit[]): QueryClient {
  const queryClient = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
  });
  queryClient.setQueryData<Kit[]>(["kits"], kits);
  return queryClient;
}

const statusOf = (queryClient: QueryClient, id: string) =>
  queryClient.getQueryData<Kit[]>(["kits"])?.find((k) => k.id === id)?.status;

describe("board status moves", () => {
  // Braces matter: an arrow body would *return* the mock, and vitest calls a
  // value returned from `beforeEach` as a teardown hook — which invoked
  // `api.updateKit()` with no arguments after every test.
  beforeEach(() => {
    vi.mocked(api.updateKit).mockReset();
  });

  it("holds the second move until the first has landed", async () => {
    const queryClient = clientWith([kit("k1", "backlog")]);
    const sent: KitStatus[] = [];
    const first = deferred<Kit>();

    vi.mocked(api.updateKit).mockImplementation((id, patch) => {
      const status = patch.status!;
      sent.push(status);
      return sent.length === 1 ? first.promise : Promise.resolve(kit(id, status));
    });

    const observer = new MutationObserver(
      queryClient,
      kitStatusMutationOptions(queryClient, () => {}),
    );
    void observer.mutate({ id: "k1", status: "building" }).catch(() => {});
    void observer.mutate({ id: "k1", status: "complete" }).catch(() => {});

    // Long enough for an unserialised second request to have gone out — it is
    // issued a few microtasks after `mutate`, not on a timer.
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(sent).toEqual(["building"]);

    // Optimistic all the same: the card is already showing the second move, which
    // is what lets a user keep dragging while the first request is in flight.
    expect(statusOf(queryClient, "k1")).toBe("complete");

    first.resolve(kit("k1", "building"));
    await vi.waitFor(() => expect(sent).toEqual(["building", "complete"]));
  });

  it("a failed move restores only the card it moved", async () => {
    const queryClient = clientWith([kit("k1", "backlog"), kit("k2", "backlog")]);
    const failing = deferred<Kit>();
    vi.mocked(api.updateKit).mockImplementation(() => failing.promise);

    const messages: string[] = [];
    const observer = new MutationObserver(
      queryClient,
      kitStatusMutationOptions(queryClient, (m) => messages.push(m)),
    );
    void observer.mutate({ id: "k1", status: "building" }).catch(() => {});
    await vi.waitFor(() => expect(statusOf(queryClient, "k1")).toBe("building"));

    // Another writer moves a different card while this one is in flight — a
    // receive, an MCP agent, or the board's own refetch. Three writer types exist
    // by design, so this is the ordinary case, not a contrived one.
    queryClient.setQueryData<Kit[]>(["kits"], (current) =>
      (current ?? []).map((k) => (k.id === "k2" ? { ...k, status: "complete" } : k)),
    );

    failing.reject(new Error("boom"));

    await vi.waitFor(() => expect(statusOf(queryClient, "k1")).toBe("backlog"));
    // The whole-array rollback reverted this to backlog: a card the failed move
    // never touched, changed back under the user.
    expect(statusOf(queryClient, "k2")).toBe("complete");
    expect(messages).toEqual(["Move failed"]);
  });
});
