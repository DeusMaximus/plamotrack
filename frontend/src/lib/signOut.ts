/** Ending this browser's session. One hook for the three shells' Sign out
 *  controls (design §13.7) — the sidebar's, the rail's and the More page's. */

import { useQueryClient } from "@tanstack/react-query";

import { api, authSessionQuery, setCsrfToken } from "../api/client";

export function useSignOut(): () => Promise<void> {
  const queryClient = useQueryClient();
  return async () => {
    try {
      await api.logout();
    } finally {
      // Whatever the server said, this browser is done: forget the CSRF token,
      // re-read the session — it now reports anonymous, so the AuthGate swaps to
      // the login screen and every page unmounts — then drop everything else so
      // nothing from this session lingers for the next owner. The order matters:
      // the session query has to still exist to be refetched (a cleared cache
      // has nothing to invalidate, and the gate would keep rendering the app
      // from its last result — caught by e2e/auth.spec.ts).
      setCsrfToken(null);
      await queryClient.invalidateQueries({ queryKey: authSessionQuery.queryKey });
      queryClient.removeQueries({
        predicate: (query) => query.queryKey[0] !== authSessionQuery.queryKey[0],
      });
    }
  };
}
