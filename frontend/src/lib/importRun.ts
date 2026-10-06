/** The import that has been sent, held above the routes (#315, the owner's
 *  call). Settings → Data management keeps its draft — the file, the mode, the
 *  plan — in the section, where leaving throws it away, and that is fine: a
 *  draft has not happened. An import that has been sent has: the server runs
 *  it whether or not the page that sent it is still there. Kept in the section,
 *  it went with the section — coming back found a fresh draft, nothing said the
 *  import had run or how it ended, and nothing stopped it being sent again,
 *  which under Add only adds every kit a second time.
 *
 *  So the request, and what it answered, live here, in the module: one at a
 *  time, for the life of the tab.
 *  - While it is in flight the section, mounted again, says so and offers no
 *    file to pick — there is nothing to send twice.
 *  - When it answers, a section that is mounted is told in the same tick
 *    (`watchImportRun`), so the result and the emptied draft land in one
 *    commit (#314 round 3, Codex finding 9). With none mounted, the outcome
 *    waits here, and the next section to mount claims it: shown once, then
 *    gone, as an outcome seen in place goes when the section is left.
 *  - A reload or a closed tab would lose it all the same, and abort the
 *    request mid-flight besides; while it is in flight the page asks first. */

import { ApiError } from "../api/client";
import type { ImportMode, ImportResult } from "../api/types";

export type ImportOutcome = { result: ImportResult } | { error: string };

export interface ImportRunState {
  /** The mode of the import in flight, or null when none is. */
  pending: ImportMode | null;
  /** How the last one ended, if no section has claimed that yet. */
  outcome: ImportOutcome | null;
}

let pending: ImportMode | null = null;
let outcome: ImportOutcome | null = null;
let listener: ((outcome: ImportOutcome) => void) | null = null;
// Moved on by `forgetImportRun`: a request answering under an older number
// belongs to a session that has ended, and leaves nothing behind.
let generation = 0;

/** The browser's own "leave this page?" — the text is the browser's. */
function holdThePage(event: BeforeUnloadEvent) {
  event.preventDefault();
  // Chromium before 119 asks only when this is set.
  event.returnValue = "";
}

export function importRunState(): ImportRunState {
  return { pending, outcome };
}

/** Send an import, unless one is already in flight. `afterwards` runs once the
 *  answer has been delivered — refreshing the app's data, which is not part of
 *  the sent phase — and whether or not anyone is watching. */
export function sendImport(
  mode: ImportMode,
  send: () => Promise<ImportResult>,
  afterwards: () => Promise<unknown>,
): boolean {
  if (pending !== null) return false;
  const sent = generation;
  pending = mode;
  outcome = null;
  if (typeof window !== "undefined") window.addEventListener("beforeunload", holdThePage);
  void send().then(
    (result) => settle(sent, { result }, afterwards),
    (err: unknown) => settle(sent, { error: err instanceof ApiError ? err.message : String(err) }),
  );
  return true;
}

function settle(sent: number, answer: ImportOutcome, afterwards?: () => Promise<unknown>) {
  // Forgotten: `forgetImportRun` let the page go already, and the hold may be
  // a newer import's by now.
  if (sent !== generation) return;
  if (typeof window !== "undefined") window.removeEventListener("beforeunload", holdThePage);
  pending = null;
  if (listener) listener(answer);
  else outcome = answer;
  if (afterwards) void afterwards();
}

/** The Data section, while it is mounted: told how an import ended, once. An
 *  outcome that came while it was away is handed over at once and forgotten. */
export function watchImportRun(onOutcome: (outcome: ImportOutcome) => void): () => void {
  listener = onOutcome;
  if (outcome) {
    const waiting = outcome;
    outcome = null;
    onOutcome(waiting);
  }
  return () => {
    if (listener === onOutcome) listener = null;
  };
}

/** Signing out: nothing of this session's import is kept for the next one. A
 *  request still in flight runs on at the server, and its answer is dropped. */
export function forgetImportRun(): void {
  generation += 1;
  pending = null;
  outcome = null;
  if (typeof window !== "undefined") window.removeEventListener("beforeunload", holdThePage);
}
