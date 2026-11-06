import {
  formatDateRange,
  formatPostedAgo,
  formatResumeDate,
  formatTimeUntil,
  formatYears,
  sourceLabel,
} from "@/lib/format";

describe("resume dates", () => {
  it.each([
    ["2022-03", "Mar 2022"],
    ["2019", "2019"],
    ["present", "Present"],
    [null, "?"],
  ])("%s -> %s", (input, expected) => {
    expect(formatResumeDate(input)).toBe(expected);
  });

  it("formats a range", () => {
    expect(formatDateRange("2022-03", "present")).toBe("Mar 2022 – Present");
  });
});

describe("relative times", () => {
  const now = Date.parse("2026-11-06T12:00:00Z");

  it("counts down to expiry", () => {
    expect(formatTimeUntil("2026-11-07T11:00:00Z", now)).toBe("in 23 hours");
    expect(formatTimeUntil("2026-11-06T12:01:00Z", now)).toBe("in 1 minute");
  });

  it("says how long ago a job was posted", () => {
    expect(formatPostedAgo(null, now)).toBeNull();
    expect(formatPostedAgo("2026-11-06T08:00:00Z", now)).toBe("today");
    expect(formatPostedAgo("2026-11-05T08:00:00Z", now)).toBe("yesterday");
    expect(formatPostedAgo("2026-10-27T12:00:00Z", now)).toBe("10 days ago");
    expect(formatPostedAgo("2026-08-06T12:00:00Z", now)).toBe("3 months ago");
  });
});

it("formats years of experience", () => {
  expect(formatYears(0)).toBe("No professional experience yet");
  expect(formatYears(1)).toBe("1 year of experience");
  expect(formatYears(7.44)).toBe("7.4 years of experience");
});

it("credits each job source by name", () => {
  expect(sourceLabel("remoteok")).toBe("Remote OK");
  expect(sourceLabel("remotive")).toBe("Remotive");
  expect(sourceLabel("greenhouse")).toBe("Greenhouse");
});
