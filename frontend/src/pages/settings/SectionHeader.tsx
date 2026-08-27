/** Every settings section opens with one of these, so the h1 → h2 → Card h3
 *  heading order holds no matter which section a deep link lands on. */
export function SectionHeader({ title, description }: { title: string; description: string }) {
  return (
    <div>
      <h2 className="text-lg font-semibold">{title}</h2>
      <p className="mt-0.5 text-sm text-zinc-500">{description}</p>
    </div>
  );
}
