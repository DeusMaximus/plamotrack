/** Ending this browser's session. One hook for the three shells' Sign out
 *  controls (design §13.7) — the sidebar's, the rail's and the More page's. */

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useRef, useState } from "react";

import { api, authSessionQuery, setCsrfToken } from "../api/client";
import type { AuthSession } from "../api/types";
import { forgetImportRun } from "./importRun";

export interface SignOut {
  /** Never rejects: a sign-out that did not end the session says so through
   *  `failed`, beside the control that was pressed (#333). */
  signOut: () => Promise<void>;
  /** Waiting on the request: the control keeps the keyboard and refuses a
   *  second press (`aria-disabled`, #268), so two presses are one request. */
  pending: boolean;
  /** The last attempt left this browser signed in. */
  failed: boolean;
  dismiss: () => void;
}

export function useSignOut(): SignOut {
  const queryClient = useQueryClient();
  const [pending, setPending] = useState(false);
  const [failed, setFailed] = useState(false);
  // The guard itself: state lags a press by a render, and two presses in that
  // render would both read `pending` as false.
  const inFlight = useRef(false);

  const signOut = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    setPending(true);
    setFailed(false);
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
    // Unread, the server's word stands: a logout that answered ended it, one
    // that did not left this browser as it was.
    const signedIn = session ? session.state === "owner" : !ended;
    inFlight.current = false;
    setPending(false);
    if (signedIn) {
      // Still the owner, so the page carries on, and its writes owe the
      // session's CSRF token. It is never cleared before this point: the gate
      // sets it only when the token *changes*, and a refused logout leaves the
      // same one, so a token cleared here stayed cleared and every write that
      // followed was refused until a reload (#333).
      if (session?.csrf_token) setCsrfToken(session.csrf_token);
      setFailed(!ended);
      return;
    }
    // Signed out — the gate is swapping to the login screen and every page
    // unmounts. Forget the CSRF token and drop everything else so nothing from
    // this session lingers for the next owner.
    setCsrfToken(null);
    queryClient.removeQueries({
      predicate: (query) => query.queryKey[0] !== authSessionQuery.queryKey[0],
    });
  }, [queryClient]);

  const dismiss = useCallback(() => setFailed(false), []);
  return { signOut, pending, failed, dismiss };
}
