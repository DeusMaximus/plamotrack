import { useState } from "react";

/** What a form waits on before it may mount, and whether it failed (#238).
 *
 *  A form mounts only on everything it reconstructs the stored row from, because
 *  react-hook-form takes its defaults once (#65, and #366 for `/meta`). So an
 *  input that failed is not one to mount without: the dialog says which, and
 *  Retry asks again for exactly those (owner's call, 2026-11-23). */
export interface DialogInput {
  /** Set once the input's last attempt has failed and nothing usable is held:
   *  what the banner says. Null while it is loading, loaded, or being retried. */
  failure: string | null;
  /** Ask again, under the query's own retry policy. */
  retry: () => Promise<unknown>;
}

export interface DialogLoadFailureState {
  /** One message per input that failed. */
  messages: readonly string[];
  /** A Retry is in flight: Retry is waiting, and keeps the keyboard. */
  retrying: boolean;
  retry: () => void;
}

/** The dialog's failure state, or null while nothing it waits on has failed.
 *
 *  Held through a Retry: a list with nothing cached forgets its error the moment
 *  its refetch starts (TanStack resets a data-less query to pending), and a
 *  dialog that fell back to Loading… there would take the keyboard off Retry and
 *  give a press nothing to say until both attempts were spent. */
export function useDialogLoadFailure(inputs: readonly DialogInput[]): DialogLoadFailureState | null {
  const [retrying, setRetrying] = useState<readonly string[] | null>(null);
  const failed = inputs.filter((input) => input.failure !== null);
  if (retrying !== null) {
    return { messages: retrying, retrying: true, retry: () => {} };
  }
  if (failed.length === 0) return null;
  const messages = failed.map((input) => input.failure!);
  return {
    messages,
    retrying: false,
    retry: () => {
      setRetrying(messages);
      // Only what failed: an input that loaded is not asked again.
      void Promise.allSettled(failed.map((input) => input.retry())).finally(() => setRetrying(null));
    },
  };
}
