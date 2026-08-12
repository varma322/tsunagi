import { NavLink, Outlet } from "react-router-dom";
import {
  Cable,
  KeyRound,
  LayoutDashboard,
  LogOut,
  MessageSquareText,
  ScrollText,
  Settings,
  ShieldCheck,
  Smartphone,
} from "lucide-react";

import { useAuth } from "../lib/auth";

const NAV = [
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard, adminOnly: false },
  { to: "/messages", label: "Messages", icon: MessageSquareText, adminOnly: false },
  { to: "/devices", label: "Devices", icon: Smartphone, adminOnly: false },
  { to: "/keys", label: "API Keys", icon: KeyRound, adminOnly: true },
  { to: "/events", label: "Events", icon: ScrollText, adminOnly: true },
  { to: "/settings", label: "Settings", icon: Settings, adminOnly: false },
];

function navClasses(isActive: boolean): string {
  return [
    "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
    isActive
      ? "bg-surface-high text-brand"
      : "text-content-muted hover:bg-white/5 hover:text-content",
  ].join(" ");
}

export function AppLayout() {
  const { signOut, isAdmin, identity } = useAuth();
  const nav = NAV.filter((item) => isAdmin || !item.adminOnly);

  return (
    <div className="min-h-dvh lg:flex">
      {/* Desktop sidebar. Glassmorphic per the design system: a translucent
          pane over the base surface rather than a drop shadow. */}
      <aside className="fixed inset-y-0 left-0 z-20 hidden w-64 flex-col border-r border-line bg-surface-low/80 backdrop-blur-xl lg:flex">
        <div className="flex items-center gap-3 px-5 py-6">
          <div className="grid size-10 place-items-center rounded-xl bg-brand/15 text-brand">
            <Cable className="size-5" aria-hidden />
          </div>
          <div>
            <p className="font-display text-lg font-bold leading-tight">Tsunagi</p>
            <p className="text-xs text-content-subtle">SMS Synchronization</p>
          </div>
        </div>

        <nav className="flex-1 space-y-1 px-3">
          {nav.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} className={({ isActive }) => navClasses(isActive)}>
              <Icon className="size-5" aria-hidden />
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="space-y-1 p-3">
          <div className="flex items-center gap-2 px-3 py-2 text-xs text-content-subtle">
            <ShieldCheck className="size-4" aria-hidden />
            <span className="truncate">
              {identity?.name ?? "signed in"} · {isAdmin ? "admin" : "read-only"}
            </span>
          </div>
          <button
            onClick={signOut}
            className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-content-muted transition-colors hover:bg-white/5 hover:text-danger"
          >
            <LogOut className="size-5" aria-hidden />
            Sign out
          </button>
        </div>
      </aside>

      <main className="flex-1 pb-24 lg:ml-64 lg:pb-0">
        <div className="mx-auto max-w-6xl px-4 py-6 sm:px-6 lg:px-8 lg:py-10">
          <Outlet />
        </div>
      </main>

      {/* Mobile bottom navigation. Settings is reachable from the Dashboard,
          so it is dropped here to keep targets comfortably wide. */}
      <nav className="fixed inset-x-0 bottom-0 z-20 flex border-t border-line bg-surface-low/95 backdrop-blur-xl lg:hidden">
        {nav.slice(0, 5).map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `flex flex-1 flex-col items-center gap-1 py-3 text-[11px] font-medium transition-colors ${
                isActive ? "text-brand" : "text-content-subtle"
              }`
            }
          >
            <Icon className="size-5" aria-hidden />
            {label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
