import { api, ApiError, errorMessage } from "@/lib/api";

function mockFetch(status: number, body: unknown) {
  const fetchMock = jest.fn().mockResolvedValue({
    status,
    ok: status >= 200 && status < 300,
    json: () => Promise.resolve(body),
  });
  global.fetch = fetchMock as unknown as typeof fetch;
  return fetchMock;
}

describe("getMatches", () => {
  it("builds the query string from the filters", async () => {
    const fetchMock = mockFetch(200, { matches: [] });
    await api.getMatches(
      "abc",
      { posted_within_days: 30, seniority: ["junior", "mid"], country: "IN", include_unspecified: false },
      true,
    );
    const url = new URL(fetchMock.mock.calls[0][0] as string);
    expect(url.pathname).toBe("/resumes/abc/matches");
    expect(url.searchParams.get("posted_within_days")).toBe("30");
    expect(url.searchParams.getAll("seniority")).toEqual(["junior", "mid"]);
    expect(url.searchParams.get("country")).toBe("IN");
    expect(url.searchParams.get("include_unspecified")).toBe("false");
    expect(url.searchParams.get("refresh")).toBe("true");
  });

  it("leaves out filters that aren't set, so the server applies its defaults", async () => {
    const fetchMock = mockFetch(200, { matches: [] });
    await api.getMatches("abc");
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/resumes\/abc\/matches$/);
  });
});

it("posts ATS requests as JSON", async () => {
  const fetchMock = mockFetch(200, {});
  await api.ats("abc", { jobId: 7 });
  const init = fetchMock.mock.calls[0][1] as RequestInit;
  expect(init.method).toBe("POST");
  expect(JSON.parse(init.body as string)).toEqual({ resume_id: "abc", job_id: 7 });
  expect(init.headers).toEqual({ "Content-Type": "application/json" });
});

describe("errorMessage", () => {
  it("prefers the API's own explanation", async () => {
    mockFetch(413, { detail: "The file is larger than 5 MB." });
    const err = await api.getResume("x").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(errorMessage(err)).toBe("The file is larger than 5 MB.");
  });

  it("explains network failures and timeouts", () => {
    expect(errorMessage(new ApiError(0, null, "network error"))).toMatch(/Couldn't reach the server/);
    expect(errorMessage(new ApiError(0, null, "timed out"))).toMatch(/took too long/);
  });
});
