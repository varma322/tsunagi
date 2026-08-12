import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, socketUrl, type Credentials } from "./api";
import { useAuth } from "./auth";

export interface AsyncState<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
  reload: () => void;
}

/**
 * Runs an API call and tracks its state.
 *
 * A 401/403 signs the user out, since a revoked key cannot be recovered by
 * retrying. `deps` behaves like a useEffect dependency list.
 */
export function useApi<T>(loader: () => Promise<T>, deps: unknown[]): AsyncState<T> {
  const { signOut } = useAuth();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [nonce, setNonce] = useState(0);

  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);

    loaderRef
      .current()
      .then((result) => {
        if (cancelled) return;
        setData(result);
        setError(null);
      })
      .catch((caught: unknown) => {
        if (cancelled) return;
        const apiError =
          caught instanceof ApiError ? caught : new ApiError(0, "error", String(caught));
        setError(apiError);
        if (apiError.isAuthFailure) signOut();
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  const reload = useCallback(() => setNonce((value) => value + 1), []);

  return { data, error, loading, reload };
}

export interface LiveFrame {
  type: string;
  data: Record<string, unknown>;
}

export type ConnectionState = "connecting" | "open" | "closed";

/**
 * Subscribes to /ws/messages.
 *
 * Delivery is best-effort by design, so consumers reconcile with the REST API
 * rather than treating this as a complete record. Reconnects with backoff.
 */
export function useLiveFrames(
  credentials: Credentials,
  onFrame: (frame: LiveFrame) => void,
): ConnectionState {
  const [state, setState] = useState<ConnectionState>("connecting");
  const handlerRef = useRef(onFrame);
  handlerRef.current = onFrame;

  useEffect(() => {
    let socket: WebSocket | null = null;
    let retryTimer: number | undefined;
    let attempt = 0;
    let disposed = false;

    const connect = () => {
      if (disposed) return;
      setState("connecting");
      socket = new WebSocket(socketUrl(credentials));

      socket.onopen = () => {
        attempt = 0;
        setState("open");
      };

      socket.onmessage = (event) => {
        try {
          handlerRef.current(JSON.parse(event.data as string) as LiveFrame);
        } catch {
          // A malformed frame must not tear down the stream.
        }
      };

      socket.onclose = () => {
        if (disposed) return;
        setState("closed");
        const delay = Math.min(1000 * 2 ** attempt, 15000);
        attempt += 1;
        retryTimer = window.setTimeout(connect, delay);
      };

      socket.onerror = () => socket?.close();
    };

    connect();

    return () => {
      disposed = true;
      window.clearTimeout(retryTimer);
      socket?.close();
    };
  }, [credentials]);

  return state;
}

/** Re-runs `reload` on an interval, for views without a live feed. */
export function usePolling(reload: () => void, intervalMs: number) {
  useEffect(() => {
    const id = window.setInterval(reload, intervalMs);
    return () => window.clearInterval(id);
  }, [reload, intervalMs]);
}
