import { useCallback } from "react";
import { Server } from "lucide-react";

import { api } from "../lib/api";
import { useAuth, useCredentials } from "../lib/auth";
import { useApi } from "../lib/hooks";
import { Badge, Button, Card, ErrorNotice, PageHeader } from "../components/ui";

export function SettingsPage() {
  const credentials = useCredentials();
  const { signOut, isAdmin, identity } = useAuth();

  const load = useCallback(() => api.health(credentials), [credentials]);
  const { data, error, reload } = useApi(load, [credentials]);

  return (
    <>
      <PageHeader title="Settings" subtitle="Connection details for this dashboard session." />

      <div className="space-y-4">
        {error && <ErrorNotice error={error} onRetry={reload} />}

        <Card>
          <div className="flex items-center gap-3">
            <Server className="size-5 text-brand" aria-hidden />
            <h2 className="text-lg font-semibold">Server</h2>
          </div>

          <dl className="mt-4 grid gap-4 sm:grid-cols-2">
            <div>
              <dt className="text-xs uppercase tracking-wide text-content-subtle">Endpoint</dt>
              <dd className="mt-1 font-mono text-sm break-all">
                {credentials.serverUrl || `${window.location.origin} (same origin)`}
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-content-subtle">Status</dt>
              <dd className="mt-1 font-mono text-sm">
                {data ? `${data.status} · v${data.version}` : "checking…"}
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-content-subtle">API key</dt>
              <dd className="mt-1 font-mono text-sm">
                {credentials.apiKey.slice(0, 12)}
                {"•".repeat(16)}
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-content-subtle">Access</dt>
              <dd className="mt-1 flex items-center gap-2 text-sm">
                <Badge tone={isAdmin ? "brand" : "neutral"}>
                  {identity?.scope ?? "unknown"}
                </Badge>
                <span className="text-content-subtle">
                  {isAdmin
                    ? "Full access, including devices and keys"
                    : "Read-only: messages, devices, and statistics"}
                </span>
              </dd>
            </div>
          </dl>
        </Card>

        <Card>
          <h2 className="text-lg font-semibold">Session</h2>
          <p className="mt-2 text-sm text-content-muted">
            Signing out removes the API key from this browser. The key itself stays valid —
            {isAdmin
              ? " revoke it on the API Keys page if it has been exposed."
              : " ask an administrator to revoke it if it has been exposed."}
          </p>
          <Button variant="secondary" className="mt-4" onClick={signOut}>
            Sign out
          </Button>
        </Card>
      </div>
    </>
  );
}
