import type { QueryClient, UseMutationOptions } from "@tanstack/react-query";

import { api, ApiError } from "../api/client";
import type { Kit, KitStatus } from "../api/types";

export interface KitStatusMove {
  id: string;
  status: KitStatus;
}

/** Where the card sat before an optimistic move, so a failure can put back
 *  exactly that card and nothing else. */
type PreviousPlacement = Pick<Kit, "status" | "status_updated_at"> | undefined;

/** The board's status-change policy, kept out of the component so it can be
 *  tested without a browser (#50).
 *
 *  Everything here is about *ordering*, which is invisible in a single move and
 *  is the whole defect in two. Driving it through real drags was not a workable
 *  test: dnd-kit's drop animation swallows a gesture that starts too soon after
 *  the last one, so a second drag that never happens looks identical to a second
 *  drag that was correctly serialised — the test passes either way. The policy is
 *  the thing that changed, so the policy is what is tested.
 */
export function kitStatusMutationOptions(
  queryClient: QueryClient,
  onError: (message: string) => void,
): UseMutationOptions<Kit, Error, KitStatusMove, PreviousPlacement> {
  return {
    // Serialised, because two drags of one card are two *intents* and
    // unserialised they race: both PATCHes go out at once, and whichever reaches
    // the server last is what gets stored — which can be the move the user made
    // first. The requests are independent, so response order says nothing; only
    // arrival order writes, and nothing was ordering it.
    //
    // The scope is board-wide rather than per kit because the scope id is fixed
    // when the mutation is defined and one definition serves every card. Moves
    // are human-paced, so a queue nobody can outrun costs nothing — and a
    // board-wide queue means at most one optimistic write is ever in flight,
    // which is what makes the rollback below sound rather than usually-right.
    scope: { id: "kit-status" },
    mutationFn: ({ id, status }) => api.updateKit(id, { status }),
    // Optimistic: the card lands in its new column immediately, even while an
    // earlier move is still queued ahead of it, so a second drag has something
    // to pick up.
    onMutate: async ({ id, status }) => {
      await queryClient.cancelQueries({ queryKey: ["kits"] });
      const moved = queryClient.getQueryData<Kit[]>(["kits"])?.find((kit) => kit.id === id);
      queryClient.setQueryData<Kit[]>(["kits"], (current) =>
        (current ?? []).map((kit) =>
          kit.id === id ? { ...kit, status, status_updated_at: new Date().toISOString() } : kit,
        ),
      );
      return moved && { status: moved.status, status_updated_at: moved.status_updated_at };
    },
    onError: (err, { id }, previous) => {
      // Restores this card only. Snapshotting the whole `kits` array and writing
      // it back wholesale re-asserts every row it captured, so a rollback from
      // one failed move also reverts any *other* card that changed in between —
      // undoing something the user never touched.
      if (previous) {
        queryClient.setQueryData<Kit[]>(["kits"], (current) =>
          (current ?? []).map((kit) => (kit.id === id ? { ...kit, ...previous } : kit)),
        );
      }
      onError(err instanceof ApiError ? err.message : "Move failed");
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["kits"] }),
  };
}
