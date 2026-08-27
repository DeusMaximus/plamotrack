import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from "react";
import { forwardRef } from "react";

const BUTTON_VARIANTS = {
  primary: "bg-indigo-600 text-white hover:bg-indigo-500 disabled:bg-indigo-300",
  secondary:
    "bg-white text-zinc-700 border border-zinc-300 hover:bg-zinc-50 disabled:text-zinc-400",
  danger: "bg-white text-red-600 border border-red-200 hover:bg-red-50 disabled:text-red-300",
} as const;

export function Button({
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: keyof typeof BUTTON_VARIANTS }) {
  return (
    <button
      className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors disabled:cursor-not-allowed ${BUTTON_VARIANTS[variant]} ${className}`}
      {...props}
    />
  );
}

const CONTROL_CLASSES =
  "w-full rounded-md border border-zinc-300 bg-white px-2.5 py-1.5 text-sm " +
  "focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className = "", ...props }, ref) {
    return <input ref={ref} className={`${CONTROL_CLASSES} ${className}`} {...props} />;
  },
);

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  function Select({ className = "", ...props }, ref) {
    return <select ref={ref} className={`${CONTROL_CLASSES} ${className}`} {...props} />;
  },
);

export const Textarea = forwardRef<
  HTMLTextAreaElement,
  TextareaHTMLAttributes<HTMLTextAreaElement>
>(function Textarea({ className = "", ...props }, ref) {
  return <textarea ref={ref} rows={3} className={`${CONTROL_CLASSES} ${className}`} {...props} />;
});

export function Field({
  label,
  required,
  error,
  children,
  className = "",
}: {
  label: string;
  required?: boolean;
  error?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <label className={`block ${className}`}>
      <span className="mb-1 block text-xs font-medium text-zinc-600">
        {label}
        {required && <span className="text-red-500"> *</span>}
      </span>
      {children}
      {error && <span className="mt-1 block text-xs text-red-600">{error}</span>}
    </label>
  );
}

export function ErrorBanner({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div role="alert" className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
      {message}
    </div>
  );
}

/** A titled panel. The heading is an h3 because every consumer sits under a
 *  page h1 and a section h2 (the Settings sections); a new consumer at a
 *  different depth should say so here rather than skip a level silently. */
export function Card({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-lg border border-zinc-200 bg-white p-4">
      <h3 className="text-sm font-semibold text-zinc-800">{title}</h3>
      <p className="mt-0.5 text-xs text-zinc-500">{description}</p>
      <div className="mt-3">{children}</div>
    </section>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-zinc-300 bg-white px-6 py-10 text-center text-sm text-zinc-500">
      {children}
    </div>
  );
}
