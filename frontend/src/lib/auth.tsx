import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import type { Credentials, Identity } from "./api";

const STORAGE_KEY = "tsunagi.credentials";

interface Session {
  credentials: Credentials;
  identity: Identity;
}

interface AuthValue {
  credentials: Credentials | null;
  identity: Identity | null;
  /** True when the credential may manage devices and keys. */
  isAdmin: boolean;
  signIn: (session: Session) => void;
  signOut: () => void;
}

const AuthContext = createContext<AuthValue | null>(null);

interface StoredSession {
  apiKey?: string;
  serverUrl?: string;
  identity?: Identity;
}

function load(): Session | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as StoredSession;
    if (!parsed.apiKey || !parsed.identity) return null;
    return {
      credentials: { apiKey: parsed.apiKey, serverUrl: parsed.serverUrl ?? "" },
      identity: parsed.identity,
    };
  } catch {
    // Corrupt or unavailable storage should log the user out, not crash the app.
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(load);

  const signIn = useCallback((next: Session) => {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ ...next.credentials, identity: next.identity }),
    );
    setSession(next);
  }, []);

  const signOut = useCallback(() => {
    window.localStorage.removeItem(STORAGE_KEY);
    setSession(null);
  }, []);

  const value = useMemo(
    () => ({
      credentials: session?.credentials ?? null,
      identity: session?.identity ?? null,
      // The stored scope only decides what the UI offers; the server enforces
      // it independently on every request.
      isAdmin: session?.identity.scope === "admin",
      signIn,
      signOut,
    }),
    [session, signIn, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}

/**
 * Credentials for pages that are only reachable behind the auth gate, so they
 * do not each need a null check.
 */
export function useCredentials(): Credentials {
  const { credentials } = useAuth();
  if (!credentials) throw new Error("useCredentials used outside a protected route");
  return credentials;
}
