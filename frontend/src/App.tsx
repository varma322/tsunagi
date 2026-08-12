import { Navigate, Outlet, Route, Routes } from "react-router-dom";

import { AppLayout } from "./components/AppLayout";
import { AuthProvider, useAuth } from "./lib/auth";
import { ConnectPage } from "./pages/ConnectPage";
import { DashboardPage } from "./pages/DashboardPage";
import { DevicesPage } from "./pages/DevicesPage";
import { EventsPage } from "./pages/EventsPage";
import { KeysPage } from "./pages/KeysPage";
import { LandingPage } from "./pages/LandingPage";
import { MessagesPage } from "./pages/MessagesPage";
import { SettingsPage } from "./pages/SettingsPage";

function RequireAuth() {
  const { credentials } = useAuth();
  return credentials ? <AppLayout /> : <Navigate to="/connect" replace />;
}

/**
 * Admin-only routes. This hides the page; the server rejects the underlying
 * requests independently, so a hand-typed URL gains nothing.
 */
function RequireAdmin() {
  const { isAdmin } = useAuth();
  return isAdmin ? <Outlet /> : <Navigate to="/dashboard" replace />;
}

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/connect" element={<ConnectPage />} />

        <Route element={<RequireAuth />}>
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/messages" element={<MessagesPage />} />
          <Route path="/devices" element={<DevicesPage />} />
          <Route path="/settings" element={<SettingsPage />} />

          <Route element={<RequireAdmin />}>
            <Route path="/keys" element={<KeysPage />} />
            <Route path="/events" element={<EventsPage />} />
          </Route>
        </Route>

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthProvider>
  );
}
