/** The mark beside the wordmark — three bars in the accent, from the Workbench
 *  artboards (§13). Decorative: the wordmark next to it is the name. */
export function BrandMark({ size = 20 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="currentColor"
      aria-hidden="true"
      className="shrink-0 text-accent"
    >
      <rect x="2" y="9" width="5" height="13" rx="1" />
      <rect x="9.5" y="2" width="5" height="20" rx="1" />
      <rect x="17" y="6" width="5" height="16" rx="1" />
    </svg>
  );
}
