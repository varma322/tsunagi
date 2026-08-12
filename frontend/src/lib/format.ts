const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["second", 60],
  ["minute", 60],
  ["hour", 24],
  ["day", 7],
  ["week", 4.35],
  ["month", 12],
  ["year", Number.POSITIVE_INFINITY],
];

const relative = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });

export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "never";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "unknown";

  let delta = (then - Date.now()) / 1000;
  for (const [unit, step] of UNITS) {
    if (Math.abs(delta) < step) {
      return relative.format(Math.round(delta), unit);
    }
    delta /= step;
  }
  return relative.format(Math.round(delta), "year");
}

const dateTime = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "medium",
});

export function absoluteTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const parsed = new Date(iso);
  return Number.isNaN(parsed.getTime()) ? "—" : dateTime.format(parsed);
}

const clockTime = new Intl.DateTimeFormat(undefined, {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

export function clock(iso: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return "--:--:--";
  const millis = String(parsed.getMilliseconds()).padStart(3, "0");
  return `${clockTime.format(parsed)}.${millis}`;
}

export function bytes(value: number): string {
  if (value < 1024) return `${value} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let size = value / 1024;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size.toFixed(size >= 10 ? 0 : 1)} ${units[index]}`;
}

export function count(value: number): string {
  return new Intl.NumberFormat().format(value);
}

/** Short weekday label for chart axes, from an ISO date (no time component). */
export function weekday(isoDate: string): string {
  const parsed = new Date(`${isoDate}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return isoDate;
  return parsed.toLocaleDateString(undefined, { weekday: "short" });
}
