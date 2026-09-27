"use client";

import clsx from "clsx";
import { AlertTriangle, ChevronLeft, ChevronRight, Loader2, X } from "lucide-react";
import { forwardRef, useEffect, useId, useRef } from "react";

import { ApiError } from "@/lib/api";

// ------------------------------------------------------------------ buttons
type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";

export const Button = forwardRef<
  HTMLButtonElement,
  React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; loading?: boolean; size?: "sm" | "md" }
>(function Button({ variant = "secondary", loading, size = "md", className, children, disabled, ...rest }, ref) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={clsx(
        "inline-flex items-center justify-center gap-1.5 rounded-sm font-mono font-semibold disabled:cursor-not-allowed disabled:opacity-60",
        size === "sm" ? "h-8 px-2.5 text-xs" : "h-9 px-3.5 text-sm",
        variant !== "ghost" && "px-press border-2 border-line-strong disabled:hatch",
        variant === "primary" && "bg-butter text-on-pastel",
        variant === "secondary" && "bg-surface text-ink hover:bg-lavender-soft",
        variant === "ghost" && "text-ink-2 hover:bg-lavender-soft hover:text-ink disabled:hover:bg-transparent",
        variant === "danger" && "bg-pink text-on-pastel",
        className,
      )}
      {...rest}
    >
      {loading && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
      {children}
    </button>
  );
});

// ------------------------------------------------------------------ form fields
// Full width by default; a caller's own width class (w-auto, sm:w-64…) replaces it rather than fighting it.
const fieldWidth = (className?: string) => (/(^|\s|:)w-/.test(className ?? "") ? className : clsx("w-full", className));

const fieldClass =
  "h-9 rounded-sm border-2 border-line-strong bg-surface px-3 font-mono text-sm text-ink placeholder:font-sans placeholder:text-ink-3 focus:shadow-sm disabled:border-dashed disabled:opacity-60";

export const Input = forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className, ...rest },
  ref,
) {
  return <input ref={ref} className={clsx(fieldClass, fieldWidth(className))} {...rest} />;
});

export function Select({ className, children, ...rest }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={clsx(fieldClass, "pr-8", fieldWidth(className))} {...rest}>
      {children}
    </select>
  );
}

export function Textarea({ className, ...rest }: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={clsx(fieldClass, "h-auto min-h-20 py-2", fieldWidth(className))} {...rest} />;
}

export function Field({
  label,
  hint,
  error,
  children,
  className,
}: {
  label: string;
  hint?: string;
  error?: string;
  children: (id: string) => React.ReactNode;
  className?: string;
}) {
  const id = useId();
  return (
    <div className={clsx("flex flex-col gap-1", className)}>
      <label htmlFor={id} className="text-[13px] font-semibold leading-4 text-ink">
        {label}
      </label>
      {children(id)}
      {error ? (
        <p className="text-xs text-critical-ink">{error}</p>
      ) : hint ? (
        <p className="text-xs text-ink-3">{hint}</p>
      ) : null}
    </div>
  );
}

// ------------------------------------------------------------------ layout
export function Card({ className, children, ...rest }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={clsx("border-[3px] border-line-strong bg-surface shadow-md", className)} {...rest}>
      {children}
    </div>
  );
}

export function CardHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-2 border-b-[3px] border-line-strong px-4 py-3">
      <div>
        <h2 className="font-pixel text-xs leading-4 tracking-[0.02em]">{title}</h2>
        {subtitle && <p className="mt-1 font-mono text-xs text-ink-3">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="font-pixel text-lg leading-8 sm:text-2xl">{title}</h1>
        {subtitle && <p className="mt-0.5 text-sm text-ink-2">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

// ------------------------------------------------------------------ feedback
export function Sprite({ name, size = 12, className }: { name: "crate" | "alert" | "check" | "cross" | "sparkle"; size?: number; className?: string }) {
  // Sprites are 12x12 pixel art: render at multiples of 12 so pixels stay square.
  // eslint-disable-next-line @next/next/no-img-element -- tiny static SVG, no optimisation needed
  return <img src={`/sprites/${name}.svg`} width={size} height={size} alt="" aria-hidden className={clsx("sprite inline-block shrink-0", className)} />;
}

export function Spinner({ label = "Counting shelves" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-10 font-mono text-sm text-ink-3" role="status">
      <Sprite name="crate" size={24} className="animate-bounce" />
      {label}…
    </div>
  );
}

export function ErrorBanner({ error, className }: { error: unknown; className?: string }) {
  if (!error) return null;
  const message = error instanceof ApiError ? error.message : error instanceof Error ? error.message : String(error);
  return (
    <div
      role="alert"
      className={clsx(
        "flex items-start gap-2 rounded-sm border-2 border-line-strong bg-pink-soft px-3 py-2 text-sm text-critical-ink",
        className,
      )}
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <span>{message}</span>
    </div>
  );
}

export function EmptyState({ title, hint, action }: { title: string; hint?: string; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 px-4 py-12 text-center">
      <Sprite name="crate" size={48} />
      <p className="text-sm font-semibold">{title}</p>
      {hint && <p className="max-w-sm text-sm text-ink-3">{hint}</p>}
      {action}
    </div>
  );
}

type Tone = "neutral" | "good" | "warning" | "critical" | "info";
export function Badge({ tone = "neutral", children }: { tone?: Tone; children: React.ReactNode }) {
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-sm border-2 border-line-strong px-1.5 py-px font-mono text-[11px] font-semibold uppercase tracking-[0.04em]",
        tone === "neutral" && "bg-surface-2 text-ink",
        tone === "good" && "bg-mint text-on-pastel",
        tone === "warning" && "bg-pink text-on-pastel",
        tone === "critical" && "bg-ink text-page",
        tone === "info" && "bg-sky text-on-pastel",
      )}
    >
      {children}
    </span>
  );
}

// ------------------------------------------------------------------ table
export function Table({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={clsx("overflow-x-auto", className)}>
      <table className="w-full border-collapse text-sm">{children}</table>
    </div>
  );
}

export function Th({ children, className, ...rest }: React.ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      className={clsx(
        "whitespace-nowrap border-b-2 border-line-strong bg-surface-2 px-3 py-2 text-left font-mono text-xs font-semibold uppercase tracking-[0.04em] text-ink",
        className,
      )}
      {...rest}
    >
      {children}
    </th>
  );
}

export function Td({ children, className, ...rest }: React.TdHTMLAttributes<HTMLTableCellElement>) {
  return (
    <td className={clsx("border-b border-line px-3 py-2.5 align-middle", className)} {...rest}>
      {children}
    </td>
  );
}

export function Pagination({
  page,
  pageSize,
  total,
  onPage,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPage: (p: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(total, page * pageSize);
  return (
    <div className="flex items-center justify-between gap-2 px-3 py-2.5 font-mono text-xs text-ink-3">
      <span className="tabular">
        {from}–{to} of {total}
      </span>
      <div className="flex items-center gap-1">
        <Button size="sm" variant="ghost" disabled={page <= 1} onClick={() => onPage(page - 1)} aria-label="Previous page">
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <span className="tabular px-1">
          {page} / {pages}
        </span>
        <Button size="sm" variant="ghost" disabled={page >= pages} onClick={() => onPage(page + 1)} aria-label="Next page">
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ modal
export function Modal({
  open,
  onClose,
  title,
  children,
  footer,
  wide,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);
  // Focus the first field once when the dialog opens (not on every re-render).
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onCloseRef.current();
    window.addEventListener("keydown", onKey);
    const body = bodyRef.current;
    if (body && !body.contains(document.activeElement)) {
      body.querySelector<HTMLElement>("input,select,textarea,button")?.focus();
    }
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);
  if (!open) return null;
  return (
    <div className="no-print fixed inset-0 z-50 flex items-end justify-center bg-[var(--overlay)] sm:items-center sm:p-4" onMouseDown={onClose}>
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onMouseDown={(e) => e.stopPropagation()}
        className={clsx(
          "flex max-h-[92vh] w-full flex-col border-[3px] border-line-strong bg-surface shadow-xl",
          wide ? "sm:max-w-3xl" : "sm:max-w-lg",
        )}
      >
        <div className="flex items-center justify-between border-b-[3px] border-line-strong bg-lavender px-4 py-3 text-on-pastel">
          <h2 className="font-pixel text-xs leading-4">{title}</h2>
          <button onClick={onClose} className="rounded-sm border-2 border-transparent p-1 hover:border-on-pastel" aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div ref={bodyRef} className="overflow-y-auto px-4 py-4">
          {children}
        </div>
        {footer && <div className="flex justify-end gap-3 border-t-2 border-line-strong px-4 py-3">{footer}</div>}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ misc
export function SearchInput({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <Input
      type="search"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder ?? "Search…"}
      className="w-full sm:w-64"
      aria-label={placeholder ?? "Search"}
    />
  );
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex gap-1">
      {options.map((o) => (
        <button
          key={o.value}
          role="radio"
          aria-checked={value === o.value}
          onClick={() => onChange(o.value)}
          className={clsx(
            "rounded-md border-2 border-line-strong px-2.5 py-1 font-mono text-xs",
            value === o.value ? "bg-butter font-bold text-on-pastel shadow-sm" : "bg-surface text-ink-2 hover:bg-lavender-soft hover:text-ink",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
