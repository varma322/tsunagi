import { useCallback, useState } from "react";
import { Power, RefreshCw, Smartphone, Trash2 } from "lucide-react";

import { ApiError, api, type Device } from "../lib/api";
import { useAuth, useCredentials } from "../lib/auth";
import { useApi, usePolling } from "../lib/hooks";
import { absoluteTime, relativeTime } from "../lib/format";
import { AddDevicePanel } from "../components/AddDevicePanel";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorNotice,
  PageHeader,
  Spinner,
  StatusBadge,
} from "../components/ui";

export function DevicesPage() {
  const credentials = useCredentials();
  const { isAdmin } = useAuth();
  const load = useCallback(() => api.listDevices(credentials), [credentials]);
  const { data, error, loading, reload } = useApi(load, [credentials]);

  const [pendingId, setPendingId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  // Online status is derived from last_seen, so it goes stale without a poll.
  usePolling(reload, 30_000);

  async function toggle(device: Device) {
    const turningOff = device.enabled;
    if (turningOff) {
      const confirmed = window.confirm(
        `Turn off "${device.name}"?\n\nIt stops uploading immediately and cannot re-register ` +
          `itself. Messages already synchronized are kept, and you can turn it back on at ` +
          `any time.`,
      );
      if (!confirmed) return;
    }

    setPendingId(device.id);
    setActionError(null);
    try {
      await api.setDeviceEnabled(credentials, device.id, !device.enabled);
      reload();
    } catch (caught) {
      setActionError((caught as ApiError).message);
    } finally {
      setPendingId(null);
    }
  }

  async function revoke(device: Device) {
    const confirmed = window.confirm(
      `Permanently revoke "${device.name}"?\n\nThis cannot be undone — use "Turn off" if you ` +
        `only want to pause it. Messages already synchronized are kept.`,
    );
    if (!confirmed) return;

    setPendingId(device.id);
    setActionError(null);
    try {
      await api.revokeDevice(credentials, device.id);
      reload();
    } catch (caught) {
      setActionError((caught as ApiError).message);
    } finally {
      setPendingId(null);
    }
  }

  return (
    <>
      <PageHeader
        title="Devices"
        subtitle={
          isAdmin
            ? "Registered phones uploading to this server."
            : "Registered phones uploading to this server (read-only)."
        }
        actions={
          <Button variant="secondary" onClick={reload}>
            <RefreshCw className="size-4" aria-hidden /> Refresh
          </Button>
        }
      />

      {error && <ErrorNotice error={error} onRetry={reload} />}
      {actionError && (
        <p className="mb-4 rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger">{actionError}</p>
      )}

      {isAdmin && <AddDevicePanel onDeviceAdded={reload} />}

      {loading && !data ? (
        <Spinner label="Loading devices" />
      ) : (data?.length ?? 0) === 0 ? (
        <Card>
          <EmptyState
            icon={<Smartphone className="size-8" aria-hidden />}
            title="No devices registered"
            description="Install the Android app, enter this server's URL and the setup key, and it will enrol itself."
          />
        </Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {(data ?? []).map((device) => (
            <Card
              key={device.id}
              className={`flex flex-col ${device.enabled ? "" : "border-warn/40"}`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-3">
                  <div
                    className={`grid size-10 place-items-center rounded-lg ${
                      device.enabled
                        ? "bg-surface-high text-content-muted"
                        : "bg-warn/10 text-warn"
                    }`}
                  >
                    <Smartphone className="size-5" aria-hidden />
                  </div>
                  <div>
                    <p className="font-semibold leading-tight">{device.name}</p>
                    <p className="font-mono text-xs text-content-subtle">
                      {device.id.slice(0, 8)}…
                    </p>
                  </div>
                </div>
                {device.enabled ? (
                  <StatusBadge
                    tone={device.status ? "ok" : "neutral"}
                    label={device.status ? "Online" : "Offline"}
                  />
                ) : (
                  <Badge tone="warn">Turned off</Badge>
                )}
              </div>

              <dl className="mt-5 grid grid-cols-2 gap-4 text-sm">
                <div>
                  <dt className="text-xs uppercase tracking-wide text-content-subtle">
                    Last seen
                  </dt>
                  <dd className="mt-1" title={absoluteTime(device.last_seen)}>
                    {relativeTime(device.last_seen)}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs uppercase tracking-wide text-content-subtle">
                    {device.enabled ? "Registered" : "Turned off"}
                  </dt>
                  <dd
                    className="mt-1"
                    title={absoluteTime(device.disabled_at ?? device.created_at)}
                  >
                    {relativeTime(device.disabled_at ?? device.created_at)}
                  </dd>
                </div>
              </dl>

              {isAdmin && (
                <div className="mt-5 flex items-center justify-between border-t border-line pt-4">
                  <Button
                    variant={device.enabled ? "secondary" : "primary"}
                    disabled={pendingId === device.id}
                    onClick={() => toggle(device)}
                  >
                    <Power className="size-4" aria-hidden />
                    {device.enabled ? "Turn off" : "Turn on"}
                  </Button>
                  <Button
                    variant="danger"
                    disabled={pendingId === device.id}
                    onClick={() => revoke(device)}
                  >
                    <Trash2 className="size-4" aria-hidden />
                    Revoke
                  </Button>
                </div>
              )}
            </Card>
          ))}
        </div>
      )}

      {isAdmin && (data?.length ?? 0) > 0 && (
        <Card className="mt-4">
          <p className="text-sm text-content-muted">
            <strong className="font-medium text-content">Turn off</strong> is reversible and
            blocks uploads immediately — the phone is told it was switched off and will not
            re-register itself.{" "}
            <strong className="font-medium text-content">Revoke</strong> is permanent. Neither
            deletes messages that have already synchronized.
          </p>
        </Card>
      )}
    </>
  );
}
