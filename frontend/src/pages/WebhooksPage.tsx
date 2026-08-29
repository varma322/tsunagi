import { useCallback, useState, type FormEvent } from "react";
import { Check, Copy, Plus, Power, Send, Trash2, Webhook as WebhookIcon } from "lucide-react";

import {
  ApiError,
  api,
  type CreatedWebhook,
  type Webhook,
  type WebhookEvent,
} from "../lib/api";
import { useCredentials } from "../lib/auth";
import { useApi } from "../lib/hooks";
import { absoluteTime, relativeTime } from "../lib/format";
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

const EVENTS: { value: WebhookEvent; label: string; hint: string }[] = [
  { value: "message.new", label: "New message", hint: "An SMS was stored." },
  {
    value: "device.status",
    label: "Device status",
    hint: "A phone was switched off, or stopped being able to capture.",
  },
];

export function WebhooksPage() {
  const credentials = useCredentials();
  const load = useCallback(() => api.listWebhooks(credentials), [credentials]);
  const { data, error, loading, reload } = useApi(load, [credentials]);

  const [showForm, setShowForm] = useState(false);
  const [url, setUrl] = useState("");
  const [description, setDescription] = useState("");
  const [events, setEvents] = useState<WebhookEvent[]>(["message.new"]);
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState<CreatedWebhook | null>(null);
  const [copied, setCopied] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<{ id: string; text: string; ok: boolean } | null>(
    null,
  );

  async function create(event: FormEvent) {
    event.preventDefault();
    setCreating(true);
    setActionError(null);
    try {
      const webhook = await api.createWebhook(credentials, {
        url: url.trim(),
        description: description.trim(),
        events,
      });
      setCreated(webhook);
      setUrl("");
      setDescription("");
      setShowForm(false);
      reload();
    } catch (caught) {
      setActionError((caught as ApiError).message);
    } finally {
      setCreating(false);
    }
  }

  async function toggle(webhook: Webhook) {
    setBusyId(webhook.id);
    setActionError(null);
    try {
      await api.setWebhookEnabled(credentials, webhook.id, !webhook.enabled);
      reload();
    } catch (caught) {
      setActionError((caught as ApiError).message);
    } finally {
      setBusyId(null);
    }
  }

  async function sendTest(webhook: Webhook) {
    setBusyId(webhook.id);
    setActionError(null);
    setTestResult(null);
    try {
      const result = await api.testWebhook(credentials, webhook.id);
      setTestResult({
        id: webhook.id,
        ok: result.delivered,
        text: result.delivered
          ? `Delivered — the endpoint answered ${result.status}.`
          : `Not delivered — ${result.error ?? `HTTP ${result.status}`}.`,
      });
      reload();
    } catch (caught) {
      setActionError((caught as ApiError).message);
    } finally {
      setBusyId(null);
    }
  }

  async function remove(webhook: Webhook) {
    const confirmed = window.confirm(
      `Delete the webhook for ${webhook.url}?\n\nNothing further is sent to it. ` +
        `Messages already stored are unaffected.`,
    );
    if (!confirmed) return;

    setBusyId(webhook.id);
    setActionError(null);
    try {
      await api.deleteWebhook(credentials, webhook.id);
      reload();
    } catch (caught) {
      setActionError((caught as ApiError).message);
    } finally {
      setBusyId(null);
    }
  }

  async function copySecret(value: string) {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setActionError("Clipboard access was denied; select and copy the secret manually.");
    }
  }

  function toggleEvent(value: WebhookEvent) {
    setEvents((current) =>
      current.includes(value)
        ? current.filter((event) => event !== value)
        : [...current, value],
    );
  }

  return (
    <>
      <PageHeader
        title="Webhooks"
        subtitle="Have this server tell another one when something happens, without it polling."
        actions={
          <Button onClick={() => setShowForm((value) => !value)}>
            <Plus className="size-4" aria-hidden /> Add webhook
          </Button>
        }
      />

      {error && <ErrorNotice error={error} onRetry={reload} />}
      {actionError && (
        <p className="mb-4 rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger">{actionError}</p>
      )}

      {created && (
        <Card className="mb-4 border-ok/40">
          <p className="font-medium text-ok">Webhook created — copy the signing secret now</p>
          <p className="mt-1 text-sm text-content-muted">
            Every delivery is signed with it, so your endpoint can tell a real one from anything
            else that finds the URL. This is the only time it is shown.
          </p>
          <div className="mt-3 flex flex-col gap-2 sm:flex-row">
            <code className="flex-1 overflow-x-auto rounded-lg bg-surface-lowest px-3 py-2 font-mono text-sm">
              {created.secret}
            </code>
            <Button variant="secondary" onClick={() => copySecret(created.secret)}>
              {copied ? (
                <Check className="size-4" aria-hidden />
              ) : (
                <Copy className="size-4" aria-hidden />
              )}
              {copied ? "Copied" : "Copy"}
            </Button>
            <Button variant="ghost" onClick={() => setCreated(null)}>
              Dismiss
            </Button>
          </div>
        </Card>
      )}

      {showForm && (
        <Card className="mb-4">
          <form onSubmit={create} className="flex flex-col gap-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
              <div className="flex-1">
                <label htmlFor="hook-url" className="mb-1.5 block text-sm font-medium">
                  Endpoint URL
                </label>
                <input
                  id="hook-url"
                  className="tsunagi-input"
                  placeholder="https://example.com/tsunagi"
                  value={url}
                  onChange={(event) => setUrl(event.target.value)}
                  required
                />
              </div>
              <div className="sm:w-56">
                <label htmlFor="hook-note" className="mb-1.5 block text-sm font-medium">
                  Description
                </label>
                <input
                  id="hook-note"
                  className="tsunagi-input"
                  placeholder="ticketing system"
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                />
              </div>
            </div>

            <fieldset>
              <legend className="mb-1.5 text-sm font-medium">Events</legend>
              <div className="flex flex-col gap-2 sm:flex-row sm:gap-6">
                {EVENTS.map((event) => (
                  <label key={event.value} className="flex items-start gap-2 text-sm">
                    <input
                      type="checkbox"
                      className="mt-0.5"
                      checked={events.includes(event.value)}
                      onChange={() => toggleEvent(event.value)}
                    />
                    <span>
                      <span className="font-medium">{event.label}</span>
                      <span className="block text-xs text-content-subtle">{event.hint}</span>
                    </span>
                  </label>
                ))}
              </div>
            </fieldset>

            <div>
              <Button type="submit" disabled={creating || !url.trim() || events.length === 0}>
                {creating ? "Creating…" : "Create"}
              </Button>
            </div>
          </form>
        </Card>
      )}

      {loading && !data ? (
        <Spinner label="Loading webhooks" />
      ) : (data?.length ?? 0) === 0 ? (
        <Card>
          <EmptyState
            icon={<WebhookIcon className="size-8" aria-hidden />}
            title="No webhooks"
            description="Add one to have an arriving SMS pushed straight to another system."
          />
        </Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {(data ?? []).map((webhook) => (
            <Card
              key={webhook.id}
              className={`flex flex-col ${webhook.enabled ? "" : "border-warn/40"}`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate font-mono text-sm" title={webhook.url}>
                    {webhook.url}
                  </p>
                  {webhook.description && (
                    <p className="mt-0.5 text-sm text-content-muted">{webhook.description}</p>
                  )}
                </div>
                <StatusBadge
                  tone={webhook.enabled ? "ok" : "warn"}
                  label={webhook.enabled ? "Active" : "Off"}
                />
              </div>

              <div className="mt-3 flex flex-wrap gap-1.5">
                {webhook.events.map((event) => (
                  <Badge key={event} tone="brand">
                    {event}
                  </Badge>
                ))}
              </div>

              <dl className="mt-4 grid grid-cols-2 gap-4 text-sm">
                <div>
                  <dt className="text-xs uppercase tracking-wide text-content-subtle">
                    Last delivery
                  </dt>
                  <dd className="mt-1" title={absoluteTime(webhook.last_delivery_at)}>
                    {webhook.last_delivery_at ? relativeTime(webhook.last_delivery_at) : "—"}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs uppercase tracking-wide text-content-subtle">Result</dt>
                  <dd className="mt-1">
                    {webhook.last_delivery_at
                      ? webhook.last_error
                        ? <span className="text-danger">{webhook.last_status ?? "failed"}</span>
                        : <span className="text-ok">{webhook.last_status}</span>
                      : "—"}
                  </dd>
                </div>
              </dl>

              {webhook.failure_count > 0 && (
                <p className="mt-3 rounded-lg bg-danger/10 px-3 py-2 text-xs leading-relaxed text-danger">
                  {webhook.failure_count} consecutive failure
                  {webhook.failure_count === 1 ? "" : "s"}
                  {webhook.last_error ? ` — ${webhook.last_error}` : ""}
                  {!webhook.enabled && ". Switched off automatically; turn it back on once the endpoint is fixed."}
                </p>
              )}

              {testResult?.id === webhook.id && (
                <p
                  className={`mt-3 rounded-lg px-3 py-2 text-xs ${
                    testResult.ok ? "bg-ok/10 text-ok" : "bg-danger/10 text-danger"
                  }`}
                >
                  {testResult.text}
                </p>
              )}

              <div className="mt-5 flex items-center justify-between border-t border-line pt-4">
                <div className="flex gap-2">
                  <Button
                    variant="secondary"
                    disabled={busyId === webhook.id}
                    onClick={() => sendTest(webhook)}
                  >
                    <Send className="size-4" aria-hidden /> Test
                  </Button>
                  <Button
                    variant={webhook.enabled ? "secondary" : "primary"}
                    disabled={busyId === webhook.id}
                    onClick={() => toggle(webhook)}
                  >
                    <Power className="size-4" aria-hidden />
                    {webhook.enabled ? "Turn off" : "Turn on"}
                  </Button>
                </div>
                <Button
                  variant="danger"
                  disabled={busyId === webhook.id}
                  onClick={() => remove(webhook)}
                >
                  <Trash2 className="size-4" aria-hidden /> Delete
                </Button>
              </div>
            </Card>
          ))}
        </div>
      )}
    </>
  );
}
