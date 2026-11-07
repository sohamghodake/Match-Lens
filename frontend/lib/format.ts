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

/** "today", "3 days ago", "2 months ago" */
export function formatPostedAgo(iso: string | null, now: number = Date.now()): string | null {
  if (!iso) return null;
  const days = Math.floor((now - new Date(iso).getTime()) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 30) return `${days} days ago`;
  const months = Math.round(days / 30);
  return `${months} ${months === 1 ? "month" : "months"} ago`;
}

/** How each source must be credited (Remotive and Remote OK require naming them). */
export function sourceLabel(source: string): string {
  return (
    { remotive: "Remotive", remoteok: "Remote OK", greenhouse: "Greenhouse" }[source] ??
    source
  );
}

/** "today at 9:57 PM", "yesterday at 9:57 PM", "3 days ago": calendar days, not 24h spans. */
export function formatRunTime(iso: string, now: Date = new Date()): string {
  const then = new Date(iso);
  const time = then.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const day = (d: Date) => Date.UTC(d.getFullYear(), d.getMonth(), d.getDate());
  const days = Math.round((day(now) - day(then)) / 86_400_000);
  if (days <= 0) return `today at ${time}`;
  if (days === 1) return `yesterday at ${time}`;
  return `${days} days ago`;
}
