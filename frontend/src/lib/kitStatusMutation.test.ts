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
    build_started_at: null,
    build_completed_at: null,
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

  it("a failed move releases the ones queued behind it", async () => {
    // The risk serialisation introduces, and the one worth a standing test:
    // a queue is only safe if every outcome drains it. If a refused move — a 409
    // from a guard, a dropped connection — left its successors parked, one bad
    // drag would wedge every later move on the board, and the optimistic UI would
    // keep cheerfully showing moves that were never sent.
    const queryClient = clientWith([kit("k1", "backlog")]);
    const sent: KitStatus[] = [];
    const first = deferred<Kit>();
    first.promise.catch(() => {});

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

    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(sent).toEqual(["building"]);

    first.reject(new Error("refused"));
    await vi.waitFor(() => expect(sent).toEqual(["building", "complete"]));
  });

  it("a failed move does not undo a later move of the same card", async () => {
    // The P2 from the Cursor Grok 4.6 review of #101, which was live at head
    // `b11770c` with all three tests green — because none of them read the cache
    // after a rejection with a successor queued.
    //
    // `scope` pauses `mutationFn`, not `onMutate`, so the queued move has already
    // applied its optimistic write when the one ahead of it fails. Restoring this
    // move's snapshot then reverts the *later* move as well, and `onDragEnd` will
    // not re-issue a PATCH for a column the card already appears to be in — so
    // the user cannot drag it back to where they just put it.
    const queryClient = clientWith([kit("k1", "backlog")]);
    const sent: KitStatus[] = [];
    const first = deferred<Kit>();
    first.promise.catch(() => {});

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
    await vi.waitFor(() => expect(statusOf(queryClient, "k1")).toBe("complete"));

    first.reject(new Error("refused"));
    await vi.waitFor(() => expect(sent).toEqual(["building", "complete"]));

    // The later intent survives the earlier failure.
    expect(statusOf(queryClient, "k1")).toBe("complete");
  });

  it("serialises moves of different cards too, and rolls each back independently", async () => {
    // Every other test in this file drives one kit, so a per-kit scope — or one
    // that only collides when `variables.id` matches — passes them all. The
    // board-wide choice was a comment rather than something pinned.
    const queryClient = clientWith([kit("k1", "backlog"), kit("k2", "backlog")]);
    const sent: string[] = [];
    const first = deferred<Kit>();
    first.promise.catch(() => {});

    vi.mocked(api.updateKit).mockImplementation((id, patch) => {
      sent.push(`${id}:${patch.status}`);
      return sent.length === 1 ? first.promise : Promise.resolve(kit(id, patch.status!));
    });

    const observer = new MutationObserver(
      queryClient,
      kitStatusMutationOptions(queryClient, () => {}),
    );
    void observer.mutate({ id: "k1", status: "building" }).catch(() => {});
    void observer.mutate({ id: "k2", status: "building" }).catch(() => {});

    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(sent).toEqual(["k1:building"]);

    first.reject(new Error("refused"));
    await vi.waitFor(() => expect(sent).toEqual(["k1:building", "k2:building"]));

    // k1 reverts because its own move failed; k2 keeps the move that succeeded.
    expect(statusOf(queryClient, "k1")).toBe("backlog");
    expect(statusOf(queryClient, "k2")).toBe("building");
  });

  it("a rollback restores the timestamp the column order is read from", async () => {
    // `status` alone is not the whole card. The board sorts each column by
    // `status_updated_at` (most recently moved first), and the optimistic write
    // stamps it with the client clock — so a rollback that restores the status
    // and keeps the optimistic timestamp leaves the card in the right column in
    // the wrong place, which no assertion on `status` can see.
    const queryClient = clientWith([kit("k1", "backlog")]);
    const stamped = queryClient.getQueryData<Kit[]>(["kits"])![0].status_updated_at;
    const failing = deferred<Kit>();
    failing.promise.catch(() => {});
    vi.mocked(api.updateKit).mockImplementation(() => failing.promise);

    const observer = new MutationObserver(
      queryClient,
      kitStatusMutationOptions(queryClient, () => {}),
    );
    void observer.mutate({ id: "k1", status: "building" }).catch(() => {});
    await vi.waitFor(() => expect(statusOf(queryClient, "k1")).toBe("building"));
    expect(queryClient.getQueryData<Kit[]>(["kits"])![0].status_updated_at).not.toBe(stamped);

    failing.reject(new Error("refused"));
    await vi.waitFor(() => expect(statusOf(queryClient, "k1")).toBe("backlog"));
    expect(queryClient.getQueryData<Kit[]>(["kits"])![0].status_updated_at).toBe(stamped);
  });
});
