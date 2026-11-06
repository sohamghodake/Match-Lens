import { render, screen } from "@testing-library/react";

import { AtsPanel } from "@/components/AtsPanel";
import { api, type AtsReport } from "@/lib/api";

const report: AtsReport = {
  resume_id: "abc",
  generated_at: "2026-11-06T12:00:00Z",
  score: 72.7,
  analysis_method: "llm",
  job: { title: "Backend Engineer", seniority: "junior", min_years: 1 },
  keywords: [
    { keyword: "Python", importance: "required", status: "found", resume_term: null },
    { keyword: "Postgres", importance: "required", status: "synonym", resume_term: "PostgreSQL" },
    { keyword: "Redis", importance: "preferred", status: "missing", resume_term: null },
  ],
  parts: [
    {
      key: "keywords", name: "Keyword coverage", max_points: 40, points: 37.3,
      deductions: [{ points: 2.7, reason: 'Preferred keyword "Redis" is not in your resume.', suggestion: "Name it." }],
      notes: [{ message: 'The posting says "Postgres" and your resume says "PostgreSQL".' }],
    },
    { key: "sections", name: "Sections and contact details", max_points: 20, points: 20, deductions: [], notes: [] },
    { key: "formatting", name: "Formatting risks", max_points: 20, points: 20, deductions: [], notes: [] },
    {
      key: "seniority", name: "Seniority and experience", max_points: 20, points: 6,
      deductions: [
        { points: 6, reason: "The role is junior-level.", suggestion: "Apply anyway." },
        { points: 8, reason: "Asks for 1+ years.", suggestion: "Count internships." },
      ],
      notes: [],
    },
  ],
};

it("shows the score, every deduction and the keyword groups", async () => {
  jest.spyOn(api, "ats").mockResolvedValue(report);
  render(<AtsPanel resumeId="abc" jobId={7} />);

  expect(await screen.findByText("73")).toBeInTheDocument();
  expect(screen.getByText("Fair match")).toBeInTheDocument();
  // Every deduction the API returned is on screen, with its points.
  for (const part of report.parts) {
    for (const d of part.deductions) {
      expect(screen.getByText(d.reason, { exact: false })).toBeInTheDocument();
      expect(screen.getByText(`−${d.points}`)).toBeInTheDocument();
    }
  }
  expect(screen.getByText("Postgres ≈ PostgreSQL")).toBeInTheDocument();
  expect(screen.getByText("Redis (nice to have)")).toBeInTheDocument();
  expect(api.ats).toHaveBeenCalledWith("abc", { jobId: 7 });
});

it("asks for a pasted description when there's no job", () => {
  render(<AtsPanel resumeId="abc" />);
  expect(screen.getByRole("button", { name: "Check ATS score" })).toBeDisabled();
});
