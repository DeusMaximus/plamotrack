/** The sent import, held above the routes (#315): what a section mounted
 *  before, during and after it is told, and when. The page's half — a section
 *  left and come back to, the browser's "leave this page?" — is
 *  e2e/pages.spec.ts's. */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ImportResult } from "../api/types";

type Run = typeof import("./importRun");
type ImportOutcome = import("./importRun").ImportOutcome;

const RESULT = {
  mode: "add_only",
  source: "kits.csv",
  created: 3,
  updated: 0,
  skipped: 0,
  kits_spawned: 0,
  kits_removed: 0,
  kits_advanced: 0,
  rows_deleted: {},
  warnings: [],
} as unknown as ImportResult;

/** A request the test answers when it chooses. */
function held() {
  let answer!: (result: ImportResult) => void;
  let refuse!: (err: unknown) => void;
  const promise = new Promise<ImportResult>((resolve, reject) => {
    answer = resolve;
    refuse = reject;
  });
  return { send: vi.fn(() => promise), answer, refuse };
}

/** Lets the request's `then` run. */
const answered = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

// The module is state for the life of the tab: a fresh one per test — and
// `ApiError` from the same fresh graph, or `instanceof` asks of another class.
let run: Run;
let ApiError: typeof import("../api/client").ApiError;
beforeEach(async () => {
  vi.resetModules();
  run = await import("./importRun");
  ({ ApiError } = await import("../api/client"));
});

describe("an import sent", () => {
  it("is pending, by its mode, until it answers", async () => {
    const request = held();
    expect(run.sendImport("add_only", request.send, async () => {})).toBe(true);
    expect(request.send).toHaveBeenCalledOnce();
    expect(run.importRunState()).toEqual({ pending: "add_only", outcome: null });
    request.answer(RESULT);
    await answered();
    expect(run.importRunState().pending).toBeNull();
  });

  it("is the only one: a second, sent while it is in flight, is refused unsent", async () => {
    const first = held();
    const second = held();
    run.sendImport("add_only", first.send, async () => {});
    expect(run.sendImport("add_only", second.send, async () => {})).toBe(false);
    expect(second.send).not.toHaveBeenCalled();
    expect(run.importRunState().pending).toBe("add_only");
    first.answer(RESULT);
    await answered();
    expect(run.sendImport("merge", second.send, async () => {}), "once it has answered, the next may go").toBe(true);
  });
});

describe("a section watching when it answers", () => {
  it("is told, and the refresh comes after", async () => {
    const order: string[] = [];
    const request = held();
    run.watchImportRun((ended) => order.push("result" in ended ? `told ${ended.result.created}` : "told error"));
    run.sendImport("add_only", request.send, async () => {
      order.push("refreshed");
    });
    request.answer(RESULT);
    await answered();
    expect(order).toEqual(["told 3", "refreshed"]);
    const told = run.importRunState().outcome;
    expect(told, "told is not shown: it waits until the section has painted it").toEqual({ result: RESULT });
    run.acknowledgeImportOutcome(told!);
    expect(run.importRunState(), "painted, so nothing waits").toEqual({ pending: null, outcome: null });
  });

  it("is told again on the next visit when it was torn down before it painted (PR #332 review)", async () => {
    const request = held();
    // Told during the navigation that removes it: the listener is still
    // hooked, the section's state is about to be thrown away.
    const leaving = run.watchImportRun(() => {});
    run.sendImport("add_only", request.send, async () => {});
    request.answer(RESULT);
    await answered();
    leaving();
    const back: unknown[] = [];
    run.watchImportRun((ended) => back.push(ended));
    expect(back, "the next section is told").toEqual([{ result: RESULT }]);
  });

  it("is told of a failure, in the API's words, and nothing is refreshed", async () => {
    const told: unknown[] = [];
    const refreshed = vi.fn(async () => {});
    const request = held();
    run.watchImportRun((ended) => told.push(ended));
    run.sendImport("merge", request.send, refreshed);
    request.refuse(new ApiError(409, "The collection changed since this preview."));
    await answered();
    expect(told).toEqual([{ error: "The collection changed since this preview." }]);
    expect(refreshed).not.toHaveBeenCalled();
  });

  it("is told of a failure that is not the API's — a dropped connection — as it was thrown", async () => {
    const told: unknown[] = [];
    const request = held();
    run.watchImportRun((ended) => told.push(ended));
    run.sendImport("merge", request.send, async () => {});
    request.refuse(new TypeError("Failed to fetch"));
    await answered();
    expect(told).toEqual([{ error: "TypeError: Failed to fetch" }]);
  });
});

describe("with no section watching when it answers", () => {
  it("the outcome waits, and the next section claims it at once — once", async () => {
    const request = held();
    const refreshed = vi.fn(async () => {});
    const away = run.watchImportRun(() => {
      throw new Error("left before it answered: never told");
    });
    run.sendImport("add_only", request.send, refreshed);
    away();
    request.answer(RESULT);
    await answered();
    expect(refreshed, "the data is refreshed with nobody watching").toHaveBeenCalledOnce();
    expect(run.importRunState()).toEqual({ pending: null, outcome: { result: RESULT } });

    const back: unknown[] = [];
    run.watchImportRun((ended) => back.push(ended));
    expect(back, "handed over as it is watched, not on the next answer").toEqual([{ result: RESULT }]);
    run.acknowledgeImportOutcome(back[0] as ImportOutcome);
    expect(run.importRunState().outcome, "and forgotten once painted").toBeNull();

    const again: unknown[] = [];
    run.watchImportRun((ended) => again.push(ended));
    expect(again, "the visit after is a fresh one").toEqual([]);
  });

  it("a failure waits the same way", async () => {
    const request = held();
    run.sendImport("merge", request.send, async () => {});
    request.refuse(new ApiError(422, "Nothing to import."));
    await answered();
    expect(run.importRunState().outcome).toEqual({ error: "Nothing to import." });
  });

  it("an older section's goodbye does not unhook a newer one (StrictMode, a fast remount)", async () => {
    const request = held();
    const told: unknown[] = [];
    const first = run.watchImportRun(() => {});
    run.watchImportRun((ended) => told.push(ended));
    first();
    run.sendImport("add_only", request.send, async () => {});
    request.answer(RESULT);
    await answered();
    expect(told).toEqual([{ result: RESULT }]);
  });

  it("a stale acknowledgement leaves a newer outcome alone", async () => {
    const first = held();
    run.sendImport("add_only", first.send, async () => {});
    first.answer(RESULT);
    await answered();
    const old = run.importRunState().outcome!;
    const second = held();
    run.sendImport("merge", second.send, async () => {});
    second.refuse(new ApiError(409, "stale"));
    await answered();
    run.acknowledgeImportOutcome(old);
    expect(run.importRunState().outcome, "the newer outcome is still to be shown").toEqual({ error: "stale" });
  });

  it("a new import clears an outcome nobody claimed", async () => {
    const first = held();
    run.sendImport("add_only", first.send, async () => {});
    first.answer(RESULT);
    await answered();
    run.sendImport("merge", held().send, async () => {});
    expect(run.importRunState()).toEqual({ pending: "merge", outcome: null });
  });
});

describe("signing out", () => {
  it("forgets the import: in flight, its answer is dropped and nothing is refreshed", async () => {
    const request = held();
    const told = vi.fn();
    const refreshed = vi.fn(async () => {});
    run.watchImportRun(told);
    run.sendImport("add_only", request.send, refreshed);
    run.forgetImportRun();
    expect(run.importRunState()).toEqual({ pending: null, outcome: null });
    request.answer(RESULT);
    await answered();
    expect(told).not.toHaveBeenCalled();
    expect(refreshed).not.toHaveBeenCalled();
    expect(run.importRunState()).toEqual({ pending: null, outcome: null });
  });

  it("forgets an outcome nobody claimed", async () => {
    const request = held();
    run.sendImport("add_only", request.send, async () => {});
    request.answer(RESULT);
    await answered();
    run.forgetImportRun();
    expect(run.importRunState().outcome).toBeNull();
  });
});

describe("the page while it is in flight", () => {
  // Node has no window; an EventTarget stands in for one, which is all the
  // module asks of it.
  let page: EventTarget;
  beforeEach(() => {
    page = new EventTarget();
    vi.stubGlobal("window", page);
  });
  afterEach(() => vi.unstubAllGlobals());

  /** Whether leaving now would be asked about: the browser asks when a
   *  `beforeunload` listener cancels the event. */
  const leavingAsks = () => {
    const event = new Event("beforeunload", { cancelable: true });
    page.dispatchEvent(event);
    return event.defaultPrevented;
  };

  it("asks before it is left, and only then", async () => {
    expect(leavingAsks(), "before anything is sent").toBe(false);
    const request = held();
    run.sendImport("add_only", request.send, async () => {});
    expect(leavingAsks(), "in flight").toBe(true);
    request.answer(RESULT);
    await answered();
    expect(leavingAsks(), "answered").toBe(false);
  });

  it("lets go when it fails, too", async () => {
    const request = held();
    run.sendImport("merge", request.send, async () => {});
    request.refuse(new ApiError(409, "stale"));
    await answered();
    expect(leavingAsks()).toBe(false);
  });

  it("lets go on signing out, and a forgotten answer does not let go of the next import's hold", async () => {
    const forgotten = held();
    run.sendImport("add_only", forgotten.send, async () => {});
    run.forgetImportRun();
    expect(leavingAsks(), "signed out").toBe(false);
    run.sendImport("merge", held().send, async () => {});
    forgotten.answer(RESULT);
    await answered();
    expect(leavingAsks(), "the next import is still in flight").toBe(true);
  });
});
