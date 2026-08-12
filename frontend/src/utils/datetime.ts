/**
 * Date/time helpers.
 *
 * The backend stores and serializes timestamps as *naive UTC* — ISO strings with
 * no timezone designator, e.g. "2026-06-11T05:20:00" (see Python `datetime.utcnow()`
 * + `.isoformat()`). JavaScript's `new Date("2026-06-11T05:20:00")` parses such a
 * string as *browser-local* time, which makes every timestamp wrong by the viewer's
 * UTC offset (e.g. +5:30 in India).
 *
 * `parseServerDate` normalizes those strings to a correct UTC instant. Once parsed
 * correctly, the standard `toLocale*` formatters render in the viewer's own timezone
 * automatically — so the same code is correct for a user in any timezone.
 */

// Matches a trailing timezone designator: "Z", "z", "+05:30", "-0800", etc.
const HAS_TZ = /([zZ]|[+-]\d{2}:?\d{2})$/;
// Matches an ISO-ish date *with a time component* ("2026-06-11T05:20" or "2026-06-11 05:20").
const IS_DATE_TIME = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/;

/**
 * Parse a value coming from the API into a Date.
 *
 * If the value is a datetime string with no timezone designator, it is treated as
 * UTC (matching how the backend serializes timestamps). Date objects, numbers, and
 * already-zoned strings are passed through unchanged.
 */
export function parseServerDate(
  value: string | number | Date | null | undefined,
): Date {
  if (value === null || value === undefined || value === "") {
    return new Date(NaN);
  }
  if (value instanceof Date) return value;
  if (typeof value === "number") return new Date(value);

  let s = value.trim();
  if (IS_DATE_TIME.test(s) && !HAS_TZ.test(s)) {
    // Naive backend timestamp → pin it to UTC.
    s = s.replace(" ", "T") + "Z";
  }
  return new Date(s);
}

/** Format a server timestamp as date + time in the viewer's local timezone. */
export function formatDateTime(
  value: string | number | Date | null | undefined,
  locales?: Intl.LocalesArgument,
  options?: Intl.DateTimeFormatOptions,
): string {
  const d = parseServerDate(value);
  return isNaN(d.getTime()) ? "—" : d.toLocaleString(locales, options);
}

/** Format a server timestamp as a date (no time) in the viewer's local timezone. */
export function formatDate(
  value: string | number | Date | null | undefined,
  locales?: Intl.LocalesArgument,
  options?: Intl.DateTimeFormatOptions,
): string {
  const d = parseServerDate(value);
  return isNaN(d.getTime()) ? "—" : d.toLocaleDateString(locales, options);
}

/** Format a server timestamp as a time (no date) in the viewer's local timezone. */
export function formatTime(
  value: string | number | Date | null | undefined,
  locales?: Intl.LocalesArgument,
  options?: Intl.DateTimeFormatOptions,
): string {
  const d = parseServerDate(value);
  return isNaN(d.getTime()) ? "—" : d.toLocaleTimeString(locales, options);
}
