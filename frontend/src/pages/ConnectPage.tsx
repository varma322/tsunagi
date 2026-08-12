import { useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { Cable, Loader2 } from "lucide-react";

import { ApiError, api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { Button } from "../components/ui";

export function ConnectPage() {
  const { credentials, signIn } = useAuth();
  const navigate = useNavigate();

  const [apiKey, setApiKey] = useState("");
  const [serverUrl, setServerUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);

  if (credentials) return <Navigate to="/dashboard" replace />;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setChecking(true);

    const candidate = { apiKey: apiKey.trim(), serverUrl: serverUrl.trim() };
    try {
      // Verify the key before storing it, so a bad paste fails here rather
      // than on every page afterwards. /me also reports the scope, which
      // decides which parts of the dashboard are offered.
      const identity = await api.me(candidate);

      if (identity.scope !== "user" && identity.scope !== "admin") {
        setError(
          "That is a device token. The dashboard needs an API key with user or admin scope.",
        );
        return;
      }

      signIn({ credentials: candidate, identity });
      navigate("/dashboard", { replace: true });
    } catch (caught) {
      const failure = caught as ApiError;
      setError(
        failure.isAuthFailure
          ? "That key was rejected. Check it was copied in full."
          : failure.message,
      );
    } finally {
      setChecking(false);
    }
  }

  return (
    <div className="grid min-h-dvh place-items-center px-6 py-12">
      <div className="w-full max-w-md">
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <div className="grid size-12 place-items-center rounded-xl bg-brand/15 text-brand">
            <Cable className="size-6" aria-hidden />
          </div>
          <div>
            <h1 className="font-display text-2xl font-bold">Connect to your server</h1>
            <p className="mt-1 text-sm text-content-subtle">
              Paste an API key with user or admin scope.
            </p>
          </div>
        </div>

        <form onSubmit={submit} className="tsunagi-card space-y-4 p-6">
          <div>
            <label htmlFor="api-key" className="mb-1.5 block text-sm font-medium">
              API key
            </label>
            <input
              id="api-key"
              className="tsunagi-input font-mono"
              type="password"
              autoComplete="off"
              placeholder="tsn_key_…"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              required
            />
            <p className="mt-1.5 text-xs text-content-subtle">
              Printed once in the server log at first startup, or pinned via
              <code className="mx-1 font-mono">TSUNAGI_BOOTSTRAP_API_KEY</code>.
            </p>
          </div>

          <div>
            <label htmlFor="server-url" className="mb-1.5 block text-sm font-medium">
              Server URL <span className="text-content-subtle">(optional)</span>
            </label>
            <input
              id="server-url"
              className="tsunagi-input"
              type="url"
              placeholder="https://tsunagi.example.com"
              value={serverUrl}
              onChange={(event) => setServerUrl(event.target.value)}
            />
            <p className="mt-1.5 text-xs text-content-subtle">
              Leave blank when the dashboard is served by the same host as the API.
            </p>
          </div>

          {error && (
            <p className="rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger">{error}</p>
          )}

          <Button type="submit" className="w-full" disabled={checking || !apiKey.trim()}>
            {checking && <Loader2 className="size-4 animate-spin" aria-hidden />}
            {checking ? "Verifying" : "Connect"}
          </Button>
        </form>

        <p className="mt-4 text-center text-xs text-content-subtle">
          The key is kept in this browser&apos;s local storage and sent only to your server.
        </p>
      </div>
    </div>
  );
}
