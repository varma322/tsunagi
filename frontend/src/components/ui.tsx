import type { ReactNode } from "react";
import { AlertTriangle, Loader2 } from "lucide-react";

import type { ApiError } from "../lib/api";

export function Card({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={`tsunagi-card p-5 ${className}`}>{children}</div>;
}

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div>
        <h1 className="text-3xl font-semibold">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-content-subtle">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export type Tone = "ok" | "warn" | "danger" | "neutral" | "brand";

const TONE_DOT: Record<Tone, string> = {
  ok: "bg-ok",
  warn: "bg-warn",
  danger: "bg-danger",
  neutral: "bg-content-subtle",
  brand: "bg-brand",
};

const TONE_BADGE: Record<Tone, string> = {
  ok: "bg-ok/10 text-ok",
  warn: "bg-warn/10 text-warn",
  danger: "bg-danger/10 text-danger",
  neutral: "bg-white/5 text-content-subtle",
  brand: "bg-brand/10 text-brand",
};

export function StatusDot({ tone }: { tone: Tone }) {
  return <span className={`inline-block size-2 shrink-0 rounded-full ${TONE_DOT[tone]}`} />;
}

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${TONE_BADGE[tone]}`}
    >
      {children}
    </span>
  );
}

export function StatusBadge({ tone, label }: { tone: Tone; label: string }) {
  return (
    <Badge tone={tone}>
      <StatusDot tone={tone} />
      {label}
    </Badge>
  );
}

type ButtonProps = {
  children: ReactNode;
  variant?: "primary" | "secondary" | "ghost" | "danger";
} & React.ButtonHTMLAttributes<HTMLButtonElement>;

const VARIANTS = {
  primary: "bg-brand-strong text-white hover:bg-brand hover:text-brand-contrast",
  secondary:
    "border border-line text-content hover:bg-white/5 hover:border-line-strong",
  ghost: "text-content-muted hover:bg-white/5",
  danger: "text-danger hover:bg-danger/10",
};

export function Button({ children, variant = "primary", className = "", ...rest }: ButtonProps) {
  return (
    <button
      {...rest}
      className={`inline-flex items-center justify-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${VARIANTS[variant]} ${className}`}
    >
      {children}
    </button>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-12 text-sm text-content-subtle">
      <Loader2 className="size-4 animate-spin" aria-hidden />
      <span>{label}…</span>
    </div>
  );
}

export function ErrorNotice({ error, onRetry }: { error: ApiError; onRetry?: () => void }) {
  return (
    <div className="tsunagi-card flex items-start gap-3 border-danger/40 p-4">
      <AlertTriangle className="mt-0.5 size-5 shrink-0 text-danger" aria-hidden />
      <div className="flex-1">
        <p className="text-sm font-medium text-danger">{error.message}</p>
        <p className="mt-1 font-mono text-xs text-content-subtle">
          {error.code}
          {error.status ? ` · HTTP ${error.status}` : ""}
        </p>
      </div>
      {onRetry && (
        <Button variant="secondary" onClick={onRetry}>
          Retry
        </Button>
      )}
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  description,
}: {
  icon?: ReactNode;
  title: string;
  description?: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-16 text-center">
      {icon && <div className="text-content-subtle">{icon}</div>}
      <p className="font-medium">{title}</p>
      {description && <p className="max-w-sm text-sm text-content-subtle">{description}</p>}
    </div>
  );
}
