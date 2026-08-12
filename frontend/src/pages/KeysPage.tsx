import { useCallback, useState, type FormEvent } from "react";
import { Check, Copy, Info, KeyRound, Plus, Trash2 } from "lucide-react";

import { ApiError, api, type ApiKey, type CreatedApiKey } from "../lib/api";
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
  StatusDot,
} from "../components/ui";

export function KeysPage() {
  const credentials = useCredentials();
  const load = useCallback(() => api.listKeys(credentials), [credentials]);
  const { data, error, loading, reload } = useApi(load, [credentials]);

  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [scope, setScope] = useState("user");
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState<CreatedApiKey | null>(null);
  const [copied, setCopied] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  async function create(event: FormEvent) {
    event.preventDefault();
    setCreating(true);
    setActionError(null);
    try {
      const key = await api.createKey(credentials, name.trim(), scope);
      setCreated(key);
      setName("");
      setShowForm(false);
      reload();
    } catch (caught) {
      setActionError((caught as ApiError).message);
    } finally {
      setCreating(false);
    }
  }

  async function revoke(key: ApiKey) {
    const confirmed = window.confirm(
      `Revoke "${key.name}"?\n\nAnything using this key stops working immediately. ` +
        `If it is the key this dashboard is using, you will be signed out.`,
    );
    if (!confirmed) return;

    setActionError(null);
    try {
      await api.revokeKey(credentials, key.id);
      reload();
    } catch (caught) {
      setActionError((caught as ApiError).message);
    }
  }

  async function copyKey(value: string) {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setActionError("Clipboard access was denied; select and copy the key manually.");
    }
  }

  const active = (data ?? []).filter((key) => !key.revoked_at);

  return (
    <>
      <PageHeader
        title="API Keys"
        subtitle="Programmatic access to your Tsunagi server."
        actions={
          <Button onClick={() => setShowForm((value) => !value)}>
            <Plus className="size-4" aria-hidden /> Create key
          </Button>
        }
      />

      {error && <ErrorNotice error={error} onRetry={reload} />}
      {actionError && (
        <p className="mb-4 rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger">{actionError}</p>
      )}

      {created && (
        <Card className="mb-4 border-ok/40">
          <p className="font-medium text-ok">Key created — copy it now</p>
          <p className="mt-1 text-sm text-content-muted">
            This is the only time the full key is shown. If you lose it, revoke it and create
            another.
          </p>
          <div className="mt-3 flex flex-col gap-2 sm:flex-row">
            <code className="flex-1 overflow-x-auto rounded-lg bg-surface-lowest px-3 py-2 font-mono text-sm">
              {created.key}
            </code>
            <Button variant="secondary" onClick={() => copyKey(created.key)}>
              {copied ? <Check className="size-4" aria-hidden /> : <Copy className="size-4" aria-hidden />}
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
          <form onSubmit={create} className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <div className="flex-1">
              <label htmlFor="key-name" className="mb-1.5 block text-sm font-medium">
                Name
              </label>
              <input
                id="key-name"
                className="tsunagi-input"
                placeholder="home-automation"
                value={name}
                onChange={(event) => setName(event.target.value)}
                required
              />
            </div>
            <div className="sm:w-48">
              <label htmlFor="key-scope" className="mb-1.5 block text-sm font-medium">
                Scope
              </label>
              <select
                id="key-scope"
                className="tsunagi-input"
                value={scope}
                onChange={(event) => setScope(event.target.value)}
              >
                <option value="user">user — read only</option>
                <option value="admin">admin — full access</option>
              </select>
            </div>
            <Button type="submit" disabled={creating || !name.trim()}>
              {creating ? "Creating…" : "Create"}
            </Button>
          </form>
        </Card>
      )}

      {loading && !data ? (
        <Spinner label="Loading keys" />
      ) : (data?.length ?? 0) === 0 ? (
        <Card>
          <EmptyState
            icon={<KeyRound className="size-8" aria-hidden />}
            title="No API keys"
            description="Create one to give a script or integration access to your messages."
          />
        </Card>
      ) : (
        <div className="tsunagi-card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[40rem] text-left text-sm">
              <thead className="border-b border-line bg-surface-container">
                <tr className="text-xs uppercase tracking-wide text-content-subtle">
                  <th className="px-4 py-3 font-medium">Name</th>
                  <th className="px-4 py-3 font-medium">Scope</th>
                  <th className="px-4 py-3 font-medium">Created</th>
                  <th className="px-4 py-3 font-medium text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {(data ?? []).map((key) => {
                  const revoked = Boolean(key.revoked_at);
                  return (
                    <tr
                      key={key.id}
                      className={`border-b border-line/50 last:border-0 ${revoked ? "opacity-50" : ""}`}
                    >
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2.5">
                          <StatusDot tone={revoked ? "neutral" : "ok"} />
                          <span className={revoked ? "line-through" : "font-medium"}>
                            {key.name}
                          </span>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <Badge tone={key.scope === "admin" ? "brand" : "neutral"}>
                          {key.scope}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-content-subtle">
                        <span title={absoluteTime(key.created_at)}>
                          {relativeTime(key.created_at)}
                        </span>
                        {revoked && (
                          <span className="ml-2 text-danger">
                            revoked {relativeTime(key.revoked_at)}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right">
                        {!revoked && (
                          <Button variant="danger" onClick={() => revoke(key)}>
                            <Trash2 className="size-4" aria-hidden />
                            Revoke
                          </Button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <Card className="mt-4">
        <div className="flex items-start gap-3">
          <Info className="mt-0.5 size-5 shrink-0 text-brand" aria-hidden />
          <div className="text-sm">
            <p className="font-medium">Secret key visibility</p>
            <p className="mt-1 text-content-muted">
              Only a hash of each key is stored, so full keys are shown once at creation and
              cannot be recovered afterwards. Revoked keys stay listed so past usage remains
              auditable. {active.length} key{active.length === 1 ? "" : "s"} currently active.
            </p>
          </div>
        </div>
      </Card>
    </>
  );
}
