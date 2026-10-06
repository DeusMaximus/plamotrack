import { createContext, useContext } from "react";

/** The folding table a cell is drawn in (`components/FoldToFit.tsx`, #329):
 *  its function chooses the table's fold stage again. */
export const RefitContext = createContext<(() => void) | null>(null);

/** Ask the table round this one to choose its stage again — for a part of it
 *  that changes its width without the table re-rendering. Null outside one. */
export function useRefit(): (() => void) | null {
  return useContext(RefitContext);
}
