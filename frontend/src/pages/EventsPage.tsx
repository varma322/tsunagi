import { useCallback, useEffect, useRef, useState } from "react";
import { Pause, Play, ScrollText, Trash2 } from "lucide-react";

import { api, type SystemEvent } from "../lib/api";
import { useCredentials } from "../lib/auth";
import { useApi, useLiveFrames, type LiveFrame } from "../lib/hooks";
import { clock } from "../lib/format";
import {
  Button,
  Card,
  EmptyState,
  ErrorNotice,
  PageHeader,
  Spinner,
  StatusDot,
} from "../components/ui";

const MAX_ROWS = 1000;

const LEVEL_TEXT: Record<string, string> = {
  info: "text-ok",
  warn: "text-warn",
  error: "text-danger",
};

function typeColor(event: SystemEvent): string {
  if (event.level === "error") return "text-danger";
  if (event.level === "warn") return "text-warn";
  return event.type.startsWith("MSG") ? "text-ok" : "text-brand";
}

function describe(event: SystemEvent): string {
  const entries = Object.entries(event.payload ?? {});
  if (entries.length === 0) return "—";
  return `{${entries.map(([key, value]) => `"${key}":${JSON.stringify(value)}`).join(", ")}}`;
}

export function EventsPage() {
  const credentials = useCredentials();
  const [level, setLevel] = useState("");
  const [paused, setPaused] = useState(false);
  const [live, setLive] = useState<SystemEvent[]>([]);
  const pausedRef = useRef(paused);
  pausedRef.current = paused;

  const load = useCallback(
    () => api.listEvents(credentials, { limit: 200, level: level || undefined }),
    [credentials, level],
  );
  const backlog = useApi(load, [credentials, level]);

  // The REST backlog seeds the view; the socket appends from there.
  useEffect(() => setLive([]), [level]);

  const onFrame = useCallback((frame: LiveFrame) => {
    if (frame.type !== "system.event" || pausedRef.current) return;
    const event = frame.data as unknown as SystemEvent;
    setLive((current) => [event, ...current].slice(0, MAX_ROWS));
  }, []);

  const connection = useLiveFrames(credentials, onFrame);

  const rows = [...live, ...(backlog.data ?? [])]
    .filter((event) => !level || event.level === level)
    .slice(0, MAX_ROWS);

  const connectionTone =
    connection === "open" ? "ok" : connection === "connecting" ? "warn" : "danger";

  return (
    <>
      <PageHeader
        title="Events"
        subtitle="System activity from the server, newest first."
      />

      <Card className="mb-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <span className="inline-flex items-center gap-2 text-sm font-medium">
              <StatusDot tone={connectionTone} />
              {connection === "open"
                ? "Live stream"
                : connection === "connecting"
                  ? "Connecting"
                  : "Disconnected"}
            </span>
            <span className="font-mono text-xs text-content-subtle">
              showing {rows.length} of last {MAX_ROWS} events
            </span>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <select
              className="tsunagi-input w-auto"
              value={level}
              onChange={(event) => setLevel(event.target.value)}
              aria-label="Filter by level"
            >
              <option value="">All levels</option>
              <option value="info">Info</option>
              <option value="warn">Warn</option>
              <option value="error">Error</option>
            </select>
            <Button variant="secondary" onClick={() => setPaused((value) => !value)}>
              {paused ? <Play className="size-4" aria-hidden /> : <Pause className="size-4" aria-hidden />}
              {paused ? "Resume" : "Pause"}
            </Button>
            <Button variant="secondary" onClick={() => setLive([])}>
              <Trash2 className="size-4" aria-hidden /> Clear
            </Button>
          </div>
        </div>

        {paused && (
          <p className="mt-3 text-xs text-warn">
            Stream paused. Incoming events are dropped rather than buffered; resume and refresh
            to catch up from the server.
          </p>
        )}
      </Card>

      {backlog.error && <ErrorNotice error={backlog.error} onRetry={backlog.reload} />}

      {!backlog.error && (
        <div className="tsunagi-card overflow-hidden">
          {backlog.loading && !backlog.data ? (
            <Spinner label="Loading events" />
          ) : rows.length === 0 ? (
            <EmptyState
              icon={<ScrollText className="size-8" aria-hidden />}
              title="No events recorded"
              description="Events appear as devices register, upload messages, or fail to authenticate."
            />
          ) : (
            <div className="max-h-[70vh] overflow-auto">
              <table className="w-full min-w-[46rem] text-left font-mono text-xs">
                <thead className="sticky top-0 border-b border-line bg-surface-container">
                  <tr className="font-sans text-xs uppercase tracking-wide text-content-subtle">
                    <th className="px-4 py-3 font-medium">Timestamp</th>
                    <th className="px-4 py-3 font-medium">Event type</th>
                    <th className="px-4 py-3 font-medium">Payload</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((event, index) => (
                    <tr
                      key={`${event.timestamp}-${index}`}
                      className="border-b border-line/40 last:border-0 hover:bg-white/[0.03]"
                    >
                      <td className="whitespace-nowrap px-4 py-2.5 text-content-subtle">
                        {clock(event.timestamp)}
                      </td>
                      <td className={`whitespace-nowrap px-4 py-2.5 ${typeColor(event)}`}>
                        {event.type}
                      </td>
                      <td
                        className={`px-4 py-2.5 ${LEVEL_TEXT[event.level] ?? "text-content-muted"}`}
                      >
                        <span className="line-clamp-1">{describe(event)}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </>
  );
}
