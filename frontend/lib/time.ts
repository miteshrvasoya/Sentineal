import type { Time, UTCTimestamp } from "lightweight-charts";

export const IST_OFFSET = 19800; // lightweight-charts renders UTC; shift so axes show IST.

/** Daily bars use an IST calendar-date string; intraday uses IST-shifted epoch seconds. */
export function toTime(t: number, daily: boolean): Time {
  return daily ? (new Date((t + IST_OFFSET) * 1000).toISOString().slice(0, 10) as Time) : ((t + IST_OFFSET) as UTCTimestamp);
}
