import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  Database,
  HardDrive,
  Inbox,
  MessageSquareText,
  Smartphone,
  TrendingUp,
} from "lucide-react";

import { api, type Message } from "../lib/api";
import { useCredentials } from "../lib/auth";
import { useApi, useLiveFrames, type LiveFrame } from "../lib/hooks";
import { absoluteTime, bytes, count, relativeTime } from "../lib/format";
import { MessageVolumeChart } from "../components/MessageVolumeChart";
import {
  Badge,
  Card,
  EmptyState,
  ErrorNotice,
  PageHeader,
  Spinner,
  StatusBadge,
  StatusDot,
} from "../components/ui";

const RECENT_LIMIT = 6;

export function DashboardPage() {
  const credentials = useCredentials();

  const loadStats = useCallback(() => api.stats(credentials), [credentials]);
  const loadVolume = useCallback(() => api.volume(credentials, 7), [credentials]);
  const loadDevices = useCallback(() => api.listDevices(credentials), [credentials]);
  const loadRecent = useCallback(
    () => api.listMessages(credentials, { limit: RECENT_LIMIT }),
    [credentials],
  );

  const stats = useApi(loadStats, [credentials]);
  const volume = useApi(loadVolume, [credentials]);
  const devices = useApi(loadDevices, [credentials]);
  const recent = useApi(loadRecent, [credentials]);

  const [liveMessages, setLiveMessages] = useState<Message[]>([]);

  const onFrame = useCallback((frame: LiveFrame) => {
    if (frame.type !== "message.new") return;
    setLiveMessages((current) =>
      [frame.data as unknown as Message, ...current].slice(0, RECENT_LIMIT),
    );
  }, []);

  const connection = useLiveFrames(credentials, onFrame);

  // Live frames only prepend rows; totals still come from the server.
  useEffect(() => {
    if (liveMessages.length === 0) return;
    stats.reload();
    volume.reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveMessages.length]);

  const deviceNames = new Map((devices.data ?? []).map((device) => [device.id, device.name]));
  const messages = [
    ...liveMessages,
    ...(recent.data?.messages ?? []).filter(
      (message) => !liveMessages.some((live) => live.id === message.id),
    ),
  ].slice(0, RECENT_LIMIT);

  const onlineDevices = (devices.data ?? []).filter((device) => device.status).length;

  return (
    <>
      <PageHeader
        title="Overview"
        subtitle="Real-time SMS synchronization metrics."
        actions={
          <span className="inline-flex items-center gap-2 rounded-lg border border-line px-3 py-2 text-xs">
            <StatusDot
              tone={connection === "open" ? "ok" : connection === "connecting" ? "warn" : "danger"}
            />
            {connection === "open"
              ? "Live"
              : connection === "connecting"
                ? "Connecting"
                : "Reconnecting"}
          </span>
        }
      />

      {stats.error && <ErrorNotice error={stats.error} onRetry={stats.reload} />}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile
          icon={<MessageSquareText className="size-5" aria-hidden />}
          label="Total messages"
          value={stats.data ? count(stats.data.messages_total) : "—"}
        />
        <StatTile
          icon={<Smartphone className="size-5" aria-hidden />}
          label="Active devices"
          value={stats.data ? count(stats.data.active_devices) : "—"}
          footnote={
            devices.data ? `${onlineDevices} of ${devices.data.length} online` : undefined
          }
        />
        <StatTile
          icon={<TrendingUp className="size-5" aria-hidden />}
          label="Messages today"
          value={stats.data ? count(stats.data.messages_today) : "—"}
        />
        <StatTile
          icon={<HardDrive className="size-5" aria-hidden />}
          label="Message storage"
          value={stats.data ? bytes(stats.data.storage_bytes) : "—"}
          footnote="Sender and body text"
        />
      </div>

      <Card className="mt-4">
        {volume.loading && !volume.data ? (
          <Spinner label="Loading volume" />
        ) : volume.error ? (
          <ErrorNotice error={volume.error} onRetry={volume.reload} />
        ) : (
          <MessageVolumeChart points={volume.data?.points ?? []} />
        )}
      </Card>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-lg font-semibold">Recent messages</h2>
            <Link to="/messages" className="text-sm text-brand hover:underline">
              View all
            </Link>
          </div>

          {recent.loading && !recent.data ? (
            <Spinner label="Loading messages" />
          ) : messages.length === 0 ? (
            <EmptyState
              icon={<Inbox className="size-7" aria-hidden />}
              title="No messages yet"
              description="They appear here the moment a device uploads one."
            />
          ) : (
            <ul className="divide-y divide-line/50">
              {messages.map((message) => (
                <li key={message.id} className="flex items-start gap-3 py-3 first:pt-0">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs">{message.sender}</span>
                      <Badge>{deviceNames.get(message.device_id) ?? "unknown"}</Badge>
                    </div>
                    <p className="mt-1 line-clamp-1 text-sm text-content-muted">{message.body}</p>
                  </div>
                  <span
                    className="whitespace-nowrap text-xs text-content-subtle"
                    title={absoluteTime(message.received_at)}
                  >
                    {relativeTime(message.received_at)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card>
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-lg font-semibold">Devices</h2>
            <Link to="/devices" className="text-sm text-brand hover:underline">
              Manage
            </Link>
          </div>

          {devices.loading && !devices.data ? (
            <Spinner label="Loading devices" />
          ) : (devices.data?.length ?? 0) === 0 ? (
            <EmptyState
              icon={<Database className="size-7" aria-hidden />}
              title="No devices"
              description="Register the Android app to start syncing."
            />
          ) : (
            <ul className="space-y-3">
              {(devices.data ?? []).map((device) => (
                <li
                  key={device.id}
                  className="rounded-lg border border-line bg-surface-low p-3"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate font-medium">{device.name}</span>
                    {device.enabled ? (
                      <StatusBadge
                        tone={device.status ? "ok" : "neutral"}
                        label={device.status ? "Online" : "Offline"}
                      />
                    ) : (
                      <Badge tone="warn">Turned off</Badge>
                    )}
                  </div>
                  <p className="mt-1 text-xs text-content-subtle">
                    Last seen {relativeTime(device.last_seen)}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  );
}

function StatTile({
  icon,
  label,
  value,
  footnote,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  footnote?: string;
}) {
  return (
    <Card>
      <div className="flex items-start justify-between">
        <span className="text-sm text-content-muted">{label}</span>
        <span className="text-content-subtle">{icon}</span>
      </div>
      <p className="mt-3 font-display text-3xl font-bold tabular-nums">{value}</p>
      {footnote && <p className="mt-1 text-xs text-content-subtle">{footnote}</p>}
    </Card>
  );
}
