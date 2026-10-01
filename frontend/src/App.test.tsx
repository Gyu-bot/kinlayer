import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { apiDate, useResource } from "./v2/data";

const page = { items: [], total: 0, offset: 0, limit: 25 };
const ontology = {
  edge_types: [],
  observation_types: [],
  fact_types: [],
  claim_bases: [],
  participant_roles: [],
};
beforeEach(() => {
  window.history.replaceState({}, "", "/people");
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => ({
      ok: true,
      json: async () => (url.includes("/ontology") ? ontology : page),
    })),
  );
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
describe("replacement routes", () => {
  it("exposes Korean save-first navigation and no approval or policy controls", async () => {
    render(<App />);
    const nav = within(screen.getByRole("navigation", { name: "주요 탐색" }));
    for (const name of ["사람", "기억", "관계 그래프", "변경 이력"])
      expect(nav.getByRole("link", { name })).toBeInTheDocument();
    expect(screen.queryByText("Candidates")).not.toBeInTheDocument();
    fireEvent.click(nav.getByRole("link", { name: "기억" }));
    await screen.findByRole("heading", { name: "기억" });
    expect(screen.queryByText("AI 사용 범위")).not.toBeInTheDocument();
    fireEvent.click(nav.getByRole("link", { name: "변경 이력" }));
    await screen.findByRole("heading", { name: "변경 이력" });
    expect(window.location.pathname).toBe("/changes");
  });
  it("keeps unknown pages distinct from valid people", () => {
    window.history.replaceState({}, "", "/missing");
    render(<App />);
    expect(
      screen.getByRole("heading", { name: "페이지를 찾을 수 없어요" }),
    ).toBeInTheDocument();
  });
  it("clears a prior resource error when the next change has no source or prior record", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: false,
        status: 404,
        json: async () => ({ error: { message: "gone", code: "not_found" } }),
      })),
    );
    function Subject({ path }: { path: string | null }) {
      const r = useResource(path);
      return <p>{r.error ? "error" : r.loading ? "loading" : "empty"}</p>;
    }
    const r = render(<Subject path="/api/memories/observations/missing" />);
    await screen.findByText("error");
    r.rerender(<Subject path={null} />);
    await waitFor(() => expect(screen.getByText("empty")).toBeInTheDocument());
  });
  it("renders SQLite UTC timestamps and PostgreSQL aware timestamps at the same instant", () => {
    expect(apiDate("2026-10-01T07:01:00").getTime()).toBe(
      apiDate("2026-10-01T07:01:00Z").getTime(),
    );
    expect(apiDate("2026-10-01T16:01:00+09:00").getTime()).toBe(
      apiDate("2026-10-01T07:01:00Z").getTime(),
    );
  });
});
