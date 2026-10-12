/** Ending this browser's session. One hook for the three shells' Sign out
 *  controls (design §13.7) — the sidebar's, the rail's and the More page's.
 *
 *  The attempt is the tab's, not a control's: it lives here, in the module,
 *  as a sent import does (`importRun.ts`). A control drawn while one waits —
 *  another shell's after a resize, More's after leaving it and coming back —
 *  shows it waiting and refuses to send a second (Greptile #340), and the
 *  failure it ends in is said by whichever control is drawn then. */

import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useCallback, useSyncExternalStore } from "react";
import { useTranslation } from "react-i18next";

import { api, authSessionQuery, csrfTokenInUse, setCsrfToken } from "../api/client";
import type { AuthSession } from "../api/types";
import { forgetImportRun } from "./importRun";

export interface SignOut {
  /** Never rejects: a sign-out that did not end the session says so through
   *  `failed`, beside the control that was pressed (#333). */
  signOut: () => Promise<void>;
  /** Waiting on the request: the control keeps the keyboard and refuses a
   *  second press (`aria-disabled`, #268), so two presses — in one control or
   *  in two — are one request. */
  pending: boolean;
  /** What the last attempt ended in, when it did not sign out, for the session
   *  it was made in: refused — still signed in — or unconfirmed, when nothing
   *  answered to say either way. Null otherwise. */
  message: string | null;
  dismiss: () => void;
}

type Failure = "refused" | "unconfirmed";

interface Attempt {
  pending: boolean;
  /** How a sign-out failed, and the CSRF token — one per session — of the
   *  session it was made in. Keyed so that a failure never outlives its
   *  session: signed out from another tab and in again, this tab's controls
   *  say nothing. */
  failure: { kind: Failure; in: string } | null;
}

let attempt: Attempt = { pending: false, failure: null };
let running: Promise<void> | null = null;
const listeners = new Set<() => void>();

function update(next: Partial<Attempt>) {
  attempt = { ...attempt, ...next };
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

async function run(queryClient: QueryClient): Promise<void> {
  update({ pending: true, failure: null });
  // The session this press was made in, by the token the logout carries. A
  // re-read that finds another — signed out and in from another tab while
  // this one waited — says nothing about that one's logout (Codex #340).
  const startedIn = csrfTokenInUse();
  let ended = false;
  try {
    await api.logout();
    ended = true;
    // Ended, by the server's word: the import this tab sent goes with it
    // (#315), whether or not the session can be re-read below. A refused
    // logout leaves both running (PR #332 rounds 1 and 3).
    forgetImportRun();
  } catch {
    // A 500 or a dropped connection says nothing about the session — the
    // server may have ended it before the answer was lost. The re-read below
    // is what decides; the failure is said once it has (#333).
  }
  // Re-read the session. The order matters: the session query has to still
  // exist to be refetched (a cleared cache has nothing to invalidate, and the
  // gate would keep rendering the app from its last result — caught by
  // e2e/auth.spec.ts). A refetch that fails does not reject; it leaves the
  // query in `error` with its last data.
  await queryClient.invalidateQueries({ queryKey: authSessionQuery.queryKey });
  const read = queryClient.getQueryState<AuthSession>(authSessionQuery.queryKey);
  const session = read?.status === "success" ? read.data : undefined;
  if (session?.state === "owner") {
    // Still the owner, so the page carries on, and its writes owe the
    // session's CSRF token. It is never cleared before this point: the gate
    // sets it only when the token *changes*, and a refused logout leaves the
    // same one, so a token cleared here stayed cleared and every write that
    // followed was refused until a reload (#333).
    setCsrfToken(session.csrf_token);
    // Refused in the session it was pressed in — which the controls say only
    // while that is the session they are in: not in one begun since.
    const refused = !ended && startedIn !== null;
    update({ pending: false, failure: refused ? { kind: "refused", in: startedIn } : null });
    return;
  }
  if (!session && !ended) {
    // Neither the logout nor the re-read answered: the server may have ended
    // the session and lost both answers. Saying "still signed in" would be a
    // guess (Codex #340), so the page says it could not tell, keeps going as
    // it was, and a second press settles it — a logout of an ended session is
    // refused, and the re-read then finds it gone.
    update({ pending: false, failure: startedIn ? { kind: "unconfirmed", in: startedIn } : null });
    return;
  }
  // Signed out — the gate is swapping to the login screen and every page
  // unmounts. Forget the CSRF token and drop everything else so nothing from
  // this session lingers for the next owner.
  setCsrfToken(null);
  queryClient.removeQueries({
    predicate: (query) => query.queryKey[0] !== authSessionQuery.queryKey[0],
  });
  update({ pending: false });
}

export function useSignOut(): SignOut {
  const queryClient = useQueryClient();
  const { data: session } = useQuery(authSessionQuery);
  const { t } = useTranslation();
  const { pending, failure } = useSyncExternalStore(subscribe, () => attempt);

  const signOut = useCallback(() => {
    // The guard itself, for every control at once: state reaches a control a
    // render after the press, and a press in that render — or in a control
    // drawn since — would otherwise send a second request.
    running ??= run(queryClient).finally(() => {
      running = null;
    });
    return running;
  }, [queryClient]);

  const dismiss = useCallback(() => update({ failure: null }), []);
  const message =
    failure === null || failure.in !== session?.csrf_token
      ? null
      : t(failure.kind === "refused" ? "auth.signOutFailed" : "auth.signOutUnconfirmed");
  return { signOut, pending, message, dismiss };
}
