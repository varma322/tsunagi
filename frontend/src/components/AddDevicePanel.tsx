import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Check, Copy, Plus, X } from "lucide-react";

import { ApiError, api, type CreatedEnrolment, type Enrolment } from "../lib/api";
import { useCredentials } from "../lib/auth";
import { useApi } from "../lib/hooks";
import { relativeTime } from "../lib/format";
import { Badge, Button, Card, type Tone } from "./ui";

const STATUS_TONE: Record<Enrolment["status"], Tone> = {
  pending: "brand",
  used: "ok",
  expired: "neutral",
  cancelled: "neutral",
};

/** Ticks once a second so the countdown stays honest. */
function useCountdown(expiresAt: string | null): number {
  const [remaining, setRemaining] = useState(0);

  useEffect(() => {
    if (!expiresAt) return;
    const tick = () =>
      setRemaining(Math.max(0, Math.floor((new Date(expiresAt).getTime() - Date.now()) / 1000)));
    tick();
    const id = window.setInterval(tick, 1000);
    return () => window.clearInterval(id);
  }, [expiresAt]);

  return remaining;
}

function formatRemaining(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return `${minutes}:${String(rest).padStart(2, "0")}`;
}

export function AddDevicePanel({ onDeviceAdded }: { onDeviceAdded: () => void }) {
  const credentials = useCredentials();

  const load = useCallback(() => api.listEnrolments(credentials), [credentials]);
  const enrolments = useApi(load, [credentials]);

  const [label, setLabel] = useState("");
  const [issuing, setIssuing] = useState(false);
  const [issued, setIssued] = useState<CreatedEnrolment | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const remaining = useCountdown(issued?.expires_at ?? null);

  // The code is spent the moment a phone uses it, so keep the list fresh while
  // one is outstanding — that is how the admin sees it land.
  useEffect(() => {
    if (!issued || remaining === 0) return;
    const id = window.setInterval(() => {
      enrolments.reload();
      onDeviceAdded();
    }, 5000);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [issued, remaining === 0]);

  const pending = (enrolments.data ?? []).filter((item) => item.status === "pending");

  async function issue(event: FormEvent) {
    event.preventDefault();
    setIssuing(true);
    setError(null);
    try {
      setIssued(await api.createEnrolment(credentials, label.trim() || undefined));
      setLabel("");
      enrolments.reload();
    } catch (caught) {
      setError((caught as ApiError).message);
    } finally {
      setIssuing(false);
    }
  }

  async function cancel(id: string) {
    setError(null);
    try {
      await api.cancelEnrolment(credentials, id);
      if (issued?.id === id) setIssued(null);
      enrolments.reload();
    } catch (caught) {
      setError((caught as ApiError).message);
    }
  }

  async function copyCode(code: string) {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setError("Clipboard access was denied; type the code manually.");
    }
  }

  const expired = issued !== null && remaining === 0;

  return (
    <Card className="mb-4">
      <h2 className="text-lg font-semibold">Add a device</h2>
      <p className="mt-1 text-sm text-content-muted">
        Generate a code, then type it into the Android app. Each code registers one phone and
        expires shortly after it is issued.
      </p>

      {error && (
        <p className="mt-3 rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger">{error}</p>
      )}

      {issued && !expired ? (
        <div className="mt-4 rounded-card border border-brand/40 bg-surface-lowest p-5 text-center">
          <p className="text-xs uppercase tracking-wide text-content-subtle">
            Enter this code on the phone
          </p>
          <p className="mt-2 font-mono text-4xl font-bold tracking-[0.2em] text-brand">
            {issued.code}
          </p>
          <p className="mt-3 text-sm text-content-muted">
            Expires in{" "}
            <span className={remaining < 60 ? "text-warn" : ""}>
              {formatRemaining(remaining)}
            </span>
            {issued.label ? ` · ${issued.label}` : ""}
          </p>
          <div className="mt-4 flex justify-center gap-2">
            <Button variant="secondary" onClick={() => copyCode(issued.code)}>
              {copied ? <Check className="size-4" aria-hidden /> : <Copy className="size-4" aria-hidden />}
              {copied ? "Copied" : "Copy"}
            </Button>
            <Button variant="ghost" onClick={() => cancel(issued.id)}>
              <X className="size-4" aria-hidden /> Cancel code
            </Button>
          </div>
        </div>
      ) : (
        <form onSubmit={issue} className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-end">
          <div className="flex-1">
            <label htmlFor="enrolment-label" className="mb-1.5 block text-sm font-medium">
              Label <span className="text-content-subtle">(optional)</span>
            </label>
            <input
              id="enrolment-label"
              className="tsunagi-input"
              placeholder="Arun's Pixel"
              value={label}
              onChange={(event) => setLabel(event.target.value)}
            />
          </div>
          <Button type="submit" disabled={issuing}>
            <Plus className="size-4" aria-hidden />
            {issuing ? "Generating…" : "Generate code"}
          </Button>
        </form>
      )}

      {expired && (
        <p className="mt-3 text-sm text-warn">
          That code expired before it was used. Generate another.
        </p>
      )}

      {pending.length > 0 && (
        <div className="mt-5 border-t border-line pt-4">
          <p className="mb-2 text-xs uppercase tracking-wide text-content-subtle">
            Outstanding codes
          </p>
          <ul className="space-y-2">
            {pending.map((item) => (
              <li
                key={item.id}
                className="flex items-center justify-between gap-3 text-sm"
              >
                <span className="flex items-center gap-2">
                  <Badge tone={STATUS_TONE[item.status]}>{item.status}</Badge>
                  <span className="text-content-muted">{item.label ?? "unlabelled"}</span>
                </span>
                <span className="flex items-center gap-3">
                  <span className="text-xs text-content-subtle">
                    expires {relativeTime(item.expires_at)}
                  </span>
                  <button
                    onClick={() => cancel(item.id)}
                    className="text-xs text-content-subtle hover:text-danger"
                  >
                    Cancel
                  </button>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}
