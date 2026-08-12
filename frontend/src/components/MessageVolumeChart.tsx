import { useState } from "react";

import type { VolumePoint } from "../lib/api";
import { absoluteTime, count, weekday } from "../lib/format";

/**
 * Daily message counts.
 *
 * One series, so there is no legend — the heading names it. The fill is
 * --color-chart rather than --color-brand: the brand tint is a text accent and
 * reads gray as a filled shape.
 */
export function MessageVolumeChart({ points }: { points: VolumePoint[] }) {
  const [hovered, setHovered] = useState<number | null>(null);

  const peak = Math.max(...points.map((point) => point.count), 0);
  const scale = niceMax(peak);
  const total = points.reduce((sum, point) => sum + point.count, 0);
  const peakIndex = points.findIndex((point) => point.count === peak && peak > 0);

  return (
    <figure className="m-0">
      <figcaption className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold">Message volume</h2>
        <span className="text-sm text-content-subtle">
          {count(total)} received over {points.length} days
        </span>
      </figcaption>

      {total === 0 ? (
        <p className="py-16 text-center text-sm text-content-subtle">
          No messages received in this period.
        </p>
      ) : (
        <div className="relative mt-6 h-56 pl-10">
          {/* Recessive gridlines with value labels down the left edge. */}
          {[1, 0.75, 0.5, 0.25, 0].map((fraction) => (
            <div
              key={fraction}
              className="absolute inset-x-0 flex items-center pl-10"
              style={{ top: `${(1 - fraction) * 100}%` }}
            >
              <span className="absolute left-0 -translate-y-1/2 font-mono text-[10px] text-content-subtle">
                {count(Math.round(scale * fraction))}
              </span>
              <div className="h-px w-full bg-line/40" />
            </div>
          ))}

          {/* 2px gaps keep adjacent bars from fusing into one shape. */}
          <div className="absolute inset-0 flex items-end gap-[2px] pl-10">
            {points.map((point, index) => {
              const ratio = scale === 0 ? 0 : point.count / scale;
              const isHovered = hovered === index;
              return (
                <div
                  key={point.date}
                  className="relative flex h-full flex-1 items-end"
                  onMouseEnter={() => setHovered(index)}
                  onMouseLeave={() => setHovered(null)}
                  onFocus={() => setHovered(index)}
                  onBlur={() => setHovered(null)}
                  tabIndex={0}
                  role="img"
                  aria-label={`${point.date}: ${point.count} messages`}
                >
                  <div
                    className="w-full rounded-t-[4px] transition-opacity"
                    style={{
                      height: `${Math.max(ratio * 100, point.count > 0 ? 1.5 : 0)}%`,
                      backgroundColor: "var(--color-chart)",
                      opacity: hovered === null || isHovered ? 1 : 0.45,
                    }}
                  />

                  {/* Direct label on the peak only — never a number on every bar. */}
                  {index === peakIndex && !isHovered && (
                    <span
                      className="pointer-events-none absolute inset-x-0 -translate-y-1 text-center font-mono text-[10px] text-content-muted"
                      style={{ bottom: `${Math.max(ratio * 100, 1.5)}%` }}
                    >
                      {count(point.count)}
                    </span>
                  )}

                  {isHovered && (
                    <div className="pointer-events-none absolute bottom-full left-1/2 z-10 mb-2 w-max -translate-x-1/2 rounded-lg border border-line bg-surface-high px-2.5 py-1.5 text-xs shadow-lg">
                      <p className="font-medium">{count(point.count)} messages</p>
                      <p className="text-content-subtle">{point.date}</p>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {total > 0 && (
        <div className="mt-2 flex gap-[2px] pl-10">
          {points.map((point) => (
            <span
              key={point.date}
              className="flex-1 text-center text-[11px] text-content-subtle"
              title={absoluteTime(`${point.date}T00:00:00`)}
            >
              {weekday(point.date)}
            </span>
          ))}
        </div>
      )}

      {/* Table view, so the data is reachable without reading the marks. */}
      <details className="mt-4">
        <summary className="cursor-pointer text-xs text-content-subtle hover:text-content">
          View as table
        </summary>
        <table className="mt-2 w-full text-left text-xs">
          <thead className="text-content-subtle">
            <tr>
              <th className="py-1 font-medium">Date</th>
              <th className="py-1 font-medium">Messages</th>
            </tr>
          </thead>
          <tbody className="font-mono">
            {points.map((point) => (
              <tr key={point.date} className="border-t border-line/40">
                <td className="py-1">{point.date}</td>
                <td className="py-1">{count(point.count)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}

/** Rounds the axis maximum up to a readable step so gridlines land on whole numbers. */
function niceMax(peak: number): number {
  if (peak <= 4) return 4;
  const magnitude = 10 ** Math.floor(Math.log10(peak));
  return Math.ceil(peak / magnitude) * magnitude;
}
