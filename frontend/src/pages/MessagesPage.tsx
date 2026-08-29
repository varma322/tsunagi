import { useCallback, useEffect, useMemo, useState } from "react";
import { Download, Inbox, RefreshCw, Search, X } from "lucide-react";

import { ApiError, api, type Device } from "../lib/api";
import { useCredentials } from "../lib/auth";
import { useApi } from "../lib/hooks";
import { absoluteTime, count, relativeTime } from "../lib/format";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorNotice,
  PageHeader,
  Spinner,
} from "../components/ui";

const PAGE_SIZE = 50;

export function MessagesPage() {
  const credentials = useCredentials();

  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [deviceId, setDeviceId] = useState("");
  const [sender, setSender] = useState("");
  const [page, setPage] = useState(0);

  // Debounce so a search does not fire a request per keystroke.
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSearch(searchInput.trim());
      setPage(0);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  const loadDevices = useCallback(() => api.listDevices(credentials), [credentials]);
  const devices = useApi(loadDevices, [credentials]);

  const loadMessages = useCallback(() => {
    const paging = { limit: PAGE_SIZE, offset: page * PAGE_SIZE };
    return search
      ? api.searchMessages(credentials, { query: search, sender: sender || undefined, ...paging })
      : api.listMessages(credentials, {
          device_id: deviceId || undefined,
          sender: sender || undefined,
          ...paging,
        });
  }, [credentials, search, deviceId, sender, page]);

  const messages = useApi(loadMessages, [credentials, search, deviceId, sender, page]);

  const deviceNames = useMemo(() => {
    const map = new Map<string, string>();
    for (const device of devices.data ?? []) map.set(device.id, device.name);
    return map;
  }, [devices.data]);

  const total = messages.data?.total ?? 0;
  const rows = messages.data?.messages ?? [];
  const from = total === 0 ? 0 : page * PAGE_SIZE + 1;
  const to = Math.min(total, (page + 1) * PAGE_SIZE);
  const hasFilters = Boolean(search || deviceId || sender);

  const [exporting, setExporting] = useState<"csv" | "json" | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);

  /**
   * Exports what the filters currently select, not the page on screen — the
   * filter chips above say what that is.
   */
  async function exportMessages(format: "csv" | "json") {
    setExporting(format);
    setExportError(null);
    try {
      const { blob, filename } = await api.exportMessages(credentials, {
        format,
        query: search || undefined,
        device_id: deviceId || undefined,
        sender: sender || undefined,
      });
      // The blob lives in this tab's memory, so the object URL has to be
      // revoked once the download has taken it; leaving it holds the whole
      // export until a reload.
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      link.click();
      URL.revokeObjectURL(url);
    } catch (caught) {
      setExportError(
        caught instanceof ApiError ? caught.message : "The export could not be downloaded.",
      );
    } finally {
      setExporting(null);
    }
  }

  function clearFilters() {
    setSearchInput("");
    setSearch("");
    setDeviceId("");
    setSender("");
    setPage(0);
  }

  return (
    <>
      <PageHeader
        title="Messages"
        subtitle={
          messages.data
            ? `${count(total)} synchronized SMS record${total === 1 ? "" : "s"}.`
            : "Loading synchronized messages."
        }
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="secondary"
              onClick={() => exportMessages("csv")}
              disabled={exporting !== null}
              title="Download every message matching the current filters"
            >
              <Download className="size-4" aria-hidden />
              {exporting === "csv" ? "Exporting…" : "CSV"}
            </Button>
            <Button
              variant="secondary"
              onClick={() => exportMessages("json")}
              disabled={exporting !== null}
              title="Download every message matching the current filters"
            >
              <Download className="size-4" aria-hidden />
              {exporting === "json" ? "Exporting…" : "JSON"}
            </Button>
            <Button variant="secondary" onClick={messages.reload}>
              <RefreshCw className="size-4" aria-hidden /> Refresh
            </Button>
          </div>
        }
      />

      {exportError && (
        <p className="mb-4 rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger">{exportError}</p>
      )}

      <Card className="mb-4">
        <div className="flex flex-col gap-3 lg:flex-row">
          <div className="relative flex-1">
            <Search
              className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-content-subtle"
              aria-hidden
            />
            <input
              className="tsunagi-input pl-9"
              placeholder="Search message bodies…"
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
              aria-label="Search messages"
            />
          </div>

          <input
            className="tsunagi-input lg:w-56"
            placeholder="Filter by sender"
            value={sender}
            onChange={(event) => {
              setSender(event.target.value);
              setPage(0);
            }}
            aria-label="Filter by sender"
          />

          <select
            className="tsunagi-input lg:w-56"
            value={deviceId}
            disabled={Boolean(search)}
            onChange={(event) => {
              setDeviceId(event.target.value);
              setPage(0);
            }}
            aria-label="Filter by device"
          >
            <option value="">All devices</option>
            {(devices.data ?? []).map((device: Device) => (
              <option key={device.id} value={device.id}>
                {device.name}
              </option>
            ))}
          </select>
        </div>

        {hasFilters && (
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {search && <Badge tone="brand">search: {search}</Badge>}
            {sender && <Badge tone="brand">sender: {sender}</Badge>}
            {deviceId && <Badge tone="brand">device: {deviceNames.get(deviceId) ?? deviceId}</Badge>}
            <button
              onClick={clearFilters}
              className="inline-flex items-center gap-1 text-xs text-content-subtle hover:text-content"
            >
              <X className="size-3" aria-hidden /> Clear all
            </button>
          </div>
        )}

        {search && (
          <p className="mt-2 text-xs text-content-subtle">
            Search covers message bodies across all devices, so the device filter is paused.
          </p>
        )}
      </Card>

      {messages.error && <ErrorNotice error={messages.error} onRetry={messages.reload} />}

      {!messages.error && (
        <div className="tsunagi-card overflow-hidden">
          {messages.loading && !messages.data ? (
            <Spinner label="Loading messages" />
          ) : rows.length === 0 ? (
            <EmptyState
              icon={<Inbox className="size-8" aria-hidden />}
              title={hasFilters ? "No messages match these filters" : "No messages yet"}
              description={
                hasFilters
                  ? "Try clearing the filters or widening your search."
                  : "Messages appear here as soon as a registered device uploads them."
              }
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[46rem] text-left text-sm">
                <thead className="border-b border-line bg-surface-container">
                  <tr className="text-xs uppercase tracking-wide text-content-subtle">
                    <th className="px-4 py-3 font-medium">Sender</th>
                    <th className="px-4 py-3 font-medium">Message</th>
                    <th className="px-4 py-3 font-medium">Device</th>
                    <th className="px-4 py-3 font-medium">Received</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((message) => (
                    <tr
                      key={message.id}
                      className="border-b border-line/50 transition-colors last:border-0 hover:bg-white/[0.03]"
                    >
                      <td className="whitespace-nowrap px-4 py-3 font-mono text-xs">
                        {message.sender}
                      </td>
                      <td className="max-w-md px-4 py-3">
                        <span className="line-clamp-2 text-content-muted">{message.body}</span>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3">
                        <Badge>{deviceNames.get(message.device_id) ?? "unknown"}</Badge>
                      </td>
                      <td
                        className="whitespace-nowrap px-4 py-3 text-content-subtle"
                        title={absoluteTime(message.received_at)}
                      >
                        {relativeTime(message.received_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {total > PAGE_SIZE && (
            <div className="flex items-center justify-between border-t border-line px-4 py-3 text-sm">
              <span className="text-content-subtle">
                {count(from)}–{count(to)} of {count(total)}
              </span>
              <div className="flex gap-2">
                <Button
                  variant="secondary"
                  disabled={page === 0}
                  onClick={() => setPage((value) => Math.max(0, value - 1))}
                >
                  Previous
                </Button>
                <Button
                  variant="secondary"
                  disabled={to >= total}
                  onClick={() => setPage((value) => value + 1)}
                >
                  Next
                </Button>
              </div>
            </div>
          )}
        </div>
      )}
    </>
  );
}
