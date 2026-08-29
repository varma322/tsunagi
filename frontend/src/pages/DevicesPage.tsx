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
  type Tone,
} from "../components/ui";

type CaptureNotice = { tone: Tone; label: string; detail: string };

/**
 * What to say about a device's ability to receive SMS.
 *
 * Online status cannot answer this: the app answers the heartbeat as long as it
 * can run at all. Returns null when capture is healthy and nothing needs
 * saying — a phone that is simply quiet is not a problem to report.
 */
function captureNotice(device: Device): CaptureNotice | null {
  if (device.capture === "blocked") {
    return {
      tone: "danger",
      label: "Not capturing",
      detail:
        device.capture_permitted === false
          ? "SMS permission has been revoked on the phone. Nothing is being captured until it is granted again."
          : "The phone cannot read its SMS inbox, so a broadcast it misses can no longer be recovered.",
    };
  }
  if (device.capture === "unknown") {
    return {
      tone: "neutral",
      label: "Capture unreported",
      detail:
        "This app is older than capture reporting. Until it is updated, a phone that has stopped receiving SMS looks the same as a quiet one.",
    };
  }
  if (device.battery_exempt === false) {
    return {
      tone: "warn",
      label: "Capture at risk",
      detail:
        "Battery optimization is on, so the system can park the app — where no SMS broadcast is delivered. The inbox sweep still recovers those, late.",
    };
  }
  return null;
}

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
          {(data ?? []).map((device) => {
            const notice = captureNotice(device);
            return (
              <Card
                key={device.id}
                className={`flex flex-col ${
                  device.capture === "blocked"
                    ? "border-danger/40"
                    : device.enabled
                      ? ""
                      : "border-warn/40"
                }`}
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
                  <div className="flex flex-wrap items-center justify-end gap-2">
                    {device.enabled ? (
                      <StatusBadge
                        tone={device.status ? "ok" : "neutral"}
                        label={device.status ? "Online" : "Offline"}
                      />
                    ) : (
                      <Badge tone="warn">Turned off</Badge>
                    )}
                    {notice && <StatusBadge tone={notice.tone} label={notice.label} />}
                  </div>
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
                      Last message
                    </dt>
                    <dd className="mt-1" title={absoluteTime(device.last_captured_at)}>
                      {device.last_captured_at ? relativeTime(device.last_captured_at) : "—"}
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

                {notice && (
                  <p
                    className={`mt-4 rounded-lg px-3 py-2 text-xs leading-relaxed ${
                      notice.tone === "danger"
                        ? "bg-danger/10 text-danger"
                        : notice.tone === "warn"
                          ? "bg-warn/10 text-warn"
                          : "bg-white/5 text-content-subtle"
                    }`}
                  >
                    {notice.detail}
                  </p>
                )}

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
            );
          })}
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
