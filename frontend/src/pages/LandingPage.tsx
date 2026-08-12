import { Link } from "react-router-dom";
import {
  ArrowRight,
  Cable,
  Code2,
  Lock,
  RefreshCw,
  Smartphone,
  Webhook,
  Zap,
} from "lucide-react";

const FEATURES = [
  {
    icon: Zap,
    title: "Real-time APIs",
    body: "WebSocket push and long-polling, so a message reaches your script within a second of arriving on the phone.",
  },
  {
    icon: Webhook,
    title: "Open contract",
    body: "Every dashboard feature is a documented, token-authenticated HTTP endpoint. No private APIs.",
  },
  {
    icon: Smartphone,
    title: "Multi-device",
    body: "Register as many phones as you like against one server and read them from a single inbox.",
  },
  {
    icon: Lock,
    title: "Privacy-first",
    body: "Self-hosted end to end. Credentials are stored hashed and messages never touch a third party.",
  },
];

export function LandingPage() {
  return (
    <div className="min-h-dvh">
      <header className="border-b border-line">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-5">
          <div className="flex items-center gap-3">
            <div className="grid size-9 place-items-center rounded-xl bg-brand/15 text-brand">
              <Cable className="size-5" aria-hidden />
            </div>
            <span className="font-display text-lg font-bold">Tsunagi</span>
          </div>
          <Link
            to="/connect"
            className="rounded-lg px-3 py-2 text-sm font-medium text-content-muted transition-colors hover:bg-white/5 hover:text-content"
          >
            Dashboard
          </Link>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-6">
        <section className="py-20 text-center">
          <h1 className="mx-auto max-w-2xl text-4xl font-bold leading-tight text-brand sm:text-5xl">
            Open-source SMS synchronization platform
          </h1>
          <p className="mx-auto mt-5 max-w-xl text-lg text-content-muted">
            Sync messages from Android to any app. Self-hosted, secure, and
            developer-first.
          </p>
          <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <Link
              to="/connect"
              className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-brand-strong px-6 py-3 font-medium text-white transition-colors hover:bg-brand hover:text-brand-contrast sm:w-auto"
            >
              Get started <ArrowRight className="size-4" aria-hidden />
            </Link>
            <a
              href="https://github.com"
              className="inline-flex w-full items-center justify-center gap-2 rounded-lg border border-line px-6 py-3 font-medium transition-colors hover:bg-white/5 sm:w-auto"
            >
              <Code2 className="size-4" aria-hidden /> GitHub
            </a>
          </div>
        </section>

        <section className="tsunagi-card flex flex-col items-center justify-center gap-4 p-8 sm:flex-row sm:gap-10">
          {[
            { icon: Smartphone, label: "Android" },
            { icon: RefreshCw, label: "Tsunagi Core" },
            { icon: Code2, label: "Your app" },
          ].map(({ icon: Icon, label }, index) => (
            <div key={label} className="flex items-center gap-4 sm:gap-10">
              <div className="flex flex-col items-center gap-2">
                <div className="grid size-14 place-items-center rounded-full border border-line text-content-muted">
                  <Icon className="size-6" aria-hidden />
                </div>
                <span className="text-sm text-content-subtle">{label}</span>
              </div>
              {index < 2 && <span className="size-1.5 rounded-full bg-content-subtle" />}
            </div>
          ))}
        </section>

        <section className="mt-6 grid gap-4 sm:grid-cols-2">
          {FEATURES.map(({ icon: Icon, title, body }) => (
            <div key={title} className="tsunagi-card p-6">
              <Icon className="size-6 text-brand" aria-hidden />
              <h2 className="mt-4 text-lg font-semibold">{title}</h2>
              <p className="mt-2 text-sm text-content-muted">{body}</p>
            </div>
          ))}
        </section>

        <section className="mt-6 overflow-hidden rounded-card border border-line">
          <div className="flex items-center justify-between border-b border-line bg-surface-container px-4 py-2.5">
            <span className="font-mono text-xs text-content-subtle">Request</span>
            <div className="flex gap-1.5">
              {["bg-content-subtle/40", "bg-content-subtle/40", "bg-content-subtle/40"].map(
                (tone, index) => (
                  <span key={index} className={`size-2.5 rounded-full ${tone}`} />
                ),
              )}
            </div>
          </div>
          <pre className="overflow-x-auto bg-surface-lowest p-4 font-mono text-xs leading-relaxed">
            <code>
              <span className="text-brand">curl</span> -X GET \{"\n"}
              {"  "}
              <span className="text-ok">
                &quot;https://tsunagi.example.com/api/v1/messages&quot;
              </span>{" "}
              \{"\n"}
              {"  "}-H{" "}
              <span className="text-ok">&quot;Authorization: Bearer tsn_key_xxxx&quot;</span>
            </code>
          </pre>
        </section>

        <footer className="mt-16 border-t border-line py-10 text-center text-sm text-content-subtle">
          <p>Self-hosted &amp; open-source. Messages stay on infrastructure you control.</p>
        </footer>
      </main>
    </div>
  );
}
