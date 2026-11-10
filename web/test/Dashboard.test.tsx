import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App, Dashboard } from "../src/app/App";
import type { Summary } from "../src/shared/data/types";
import raw from "../public/data/summary.json";

const summary = raw as unknown as Summary;
const ok = (body: unknown) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) } as Response);
afterEach(cleanup);

describe("states", () => {
  it("shows a skeleton while loading", () => {
    render(<App fetcher={() => new Promise<Response>(() => {})} />);
    expect(screen.getByRole("status", { name: "Loading results" })).toBeTruthy();
  });
  it("explains a failure and retries", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce({ ok: false, status: 503 } as Response).mockImplementation(() => ok(summary));
    render(<App fetcher={fetcher as unknown as (u: string) => Promise<Response>} />);
    expect((await screen.findByRole("alert")).textContent).toContain("503");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(screen.getByRole("heading", { level: 1 })).toBeTruthy());
  });
  it("names the command when there are no results", () => {
    render(<Dashboard summary={{ ...summary, dev: null, heldout: null }} />);
    expect(screen.getAllByText(/make eval && make report/).length).toBeGreaterThan(0);
  });
});

describe("content", () => {
  it("draws one bar per design", () => {
    render(<Dashboard summary={summary} />);
    const run = summary.heldout ?? summary.dev!;
    expect(screen.getAllByRole("img").length).toBe(Object.keys(run.designs).length + 1); // + the ownership chart
  });
  it("answers as of the date on the slider", () => {
    render(<Dashboard summary={summary} />);
    const slider = screen.getByLabelText(/As of/);
    fireEvent.change(slider, { target: { value: "0" } });
    expect(screen.getByLabelText(/As of/).getAttribute("aria-valuetext")).toContain(new Date(summary.story.start).getUTCFullYear().toString());
    expect(screen.getAllByRole("status").length).toBeGreaterThan(0);
  });
});
