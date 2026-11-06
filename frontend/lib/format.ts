const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2022-03" -> "Mar 2022", "2019" -> "2019", "present" -> "Present". */
export function formatResumeDate(value: string | null): string {
  if (!value) return "?";
  if (value === "present") return "Present";
  const [year, month] = value.split("-");
  return month ? `${MONTHS[Number(month) - 1]} ${year}` : year;
}

export function formatDateRange(start: string | null, end: string | null): string {
  return `${formatResumeDate(start)} – ${formatResumeDate(end)}`;
}

export function formatYears(years: number): string {
  if (years === 0) return "No professional experience yet";
  const rounded = Math.round(years * 10) / 10;
  return `${rounded} ${rounded === 1 ? "year" : "years"} of experience`;
}

/** "in 23 hours", "in 40 minutes" */
export function formatTimeUntil(iso: string, now: number = Date.now()): string {
  const minutes = Math.max(0, Math.round((new Date(iso).getTime() - now) / 60_000));
  if (minutes < 60) return `in ${minutes} ${minutes === 1 ? "minute" : "minutes"}`;
  const hours = Math.round(minutes / 60);
  return `in ${hours} ${hours === 1 ? "hour" : "hours"}`;
}
