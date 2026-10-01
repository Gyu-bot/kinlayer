import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { Person } from "./Person";
import type { MemoryItem } from "./data";

const fetchMock = vi.fn();
const response = (body: unknown) => new Response(JSON.stringify(body), {
  headers: { "Content-Type": "application/json" },
});
const ontology = {
  fact_types: [
    { value: "job", label: "직업", is_active: true, support_level: "supported" },
    { value: "birthday", label: "생일", is_active: true, support_level: "supported" },
    { value: "legacy_profile", label: "이전 프로필", is_active: false, support_level: "unsupported" },
  ],
  edge_types: [{ relation_type: "friend", label: "친구", active: true, directed_default: false, write_supported: true }],
  observation_types: [{ observation_type: "recent_interaction", active: true }],
  claim_bases: [{ value: "reported" }, { value: "inferred" }, { value: "unknown" }],
  participant_roles: [],
};
function fact(index: number): MemoryItem {
  return {
    id: `fact-${index}`,
    record_ref: `entity_facts:fact-${index}`,
    record_type: "entity_facts",
    content: `프로필 값 ${index}`,
    claim_basis: "reported",
    confidence: 1,
    status: "active",
    is_current: true,
    created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-01T00:00:00Z",
    valid_from: null,
    valid_to: null,
    payload: { entity_id: "person-a", fact_type: "external_handle", value: null, claim_basis: "reported", confidence: 1, valid_from: null, valid_to: null },
    entities: [{ id: "person-a", display_name: "민지", role: "subject" }],
    sources: [],
  };
}
const facts = Array.from({ length: 23 }, (_, index) => fact(index));
facts[6] = { ...facts[6], content: "소프트웨어 엔지니어", payload: { ...facts[6].payload, fact_type: "job" } };
facts[7] = { ...facts[7], content: "--05-12", payload: { ...facts[7].payload, fact_type: "birthday", value: { month: 5, day: 12, precision: "day" } } };
facts[8] = { ...facts[8], content: "이전 유형의 보존된 정보", payload: { ...facts[8].payload, fact_type: "legacy_profile" } };
const edge: MemoryItem = {
  ...fact(30), id: "edge-a", record_ref: "entity_edges:edge-a", record_type: "entity_edges", content: "오래된 친구 관계",
  payload: { claim_basis: "reported", confidence: 1, valid_from: null, valid_to: null, from_entity_id: "person-a", to_entity_id: "person-b", relation_type: "friend", directed: false },
  entities: [{ id: "person-a", display_name: "민지", role: "from" }, { id: "person-b", display_name: "서준", role: "to" }],
};
const context: MemoryItem = {
  ...fact(31), id: "context-a", record_ref: "observations:context-a", record_type: "observations", content: "최근 함께 점심을 먹음",
  payload: { claim_basis: "reported", confidence: 1, valid_from: null, valid_to: null, subject_entity_id: "person-a", observation_type: "recent_interaction" },
};
const previous: MemoryItem = { ...fact(32), content: "철회된 직업 정보", is_current: false, status: "retracted" };
const current = [facts[8], edge, context, ...facts.filter((item) => item !== facts[8])];

beforeAll(() => {
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value: function (this: HTMLDialogElement) { this.open = true; } });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value: function (this: HTMLDialogElement) { this.open = false; } });
});
beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  window.localStorage.clear();
  fetchMock.mockImplementation(async (input: string) => {
    const url = new URL(input);
    if (url.pathname === "/api/ontology") return response(ontology);
    if (url.pathname === "/api/system/config") return response({ memory_write: { endpoint: "/api/memories", contract_version: "2", review_required: false } });
    if (url.pathname === "/api/entities/person-a") return response({
      id: "person-a", display_name: "민지", status: "active", system_role: null, last_referenced_at: null,
      properties: { job: "속성에만 보존된 직업", imported_profile: { location: "서울", preferences: ["차", "산책"] }, empty_value: null, active_member: false, visits: 0, merged_entity_ref: "entities:technical-reference" },
    });
    if (url.pathname === "/api/entities/person-a/aliases") return response({ items: [], total: 0, limit: 20, offset: 0 });
    if (url.pathname === "/api/entities") return response({ items: [{ id: "person-a", display_name: "민지" }, { id: "person-b", display_name: "서준" }], total: 2, limit: 30, offset: 0 });
    if (url.pathname === "/api/memories") {
      const type = url.searchParams.get("record_type");
      const status = url.searchParams.get("status");
      const rows = status === "history" ? [previous] : status === "all" ? [...current, previous] : type === "entity_facts" ? facts : type === "entity_edges" ? [edge] : type === "observations" ? [context] : current;
      const offset = Number(url.searchParams.get("offset") || 0);
      const limit = Number(url.searchParams.get("limit") || 20);
      return response({ items: rows.slice(offset, offset + limit), total: rows.length, limit, offset });
    }
    throw new Error(`Unexpected request: ${url.pathname}`);
  });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function memoryRequests() {
  return fetchMock.mock.calls.map(([url]) => new URL(url)).filter((url) => url.pathname === "/api/memories");
}

describe("인물 전체 정보", () => {
  it("개요에 여섯 번째 이후 직업·생일과 이전 유형을 표시하고 프로필만 독립적으로 페이지를 넘긴다", async () => {
    render(<Person id="person-a" onNavigate={() => {}} />);
    const section = await screen.findByRole("region", { name: "기본 정보" });
    await within(section).findByText("소프트웨어 엔지니어");
    expect(within(section).getByText("5월 12일")).toBeInTheDocument();
    expect(within(section).getByText("이전 유형의 보존된 정보")).toBeInTheDocument();
    expect(within(section).getAllByRole("link")).toHaveLength(20);
    expect(within(section).getByText("전체 23개 · 1–20")).toBeInTheDocument();
    fireEvent.click(within(section).getByRole("button", { name: "다음" }));
    await within(section).findByText("프로필 값 22");
    expect(within(section).getByText("전체 23개 · 21–23")).toBeInTheDocument();
    expect(within(section).getByRole("button", { name: "다음" })).toBeDisabled();
    expect(screen.getByText("최근 함께 점심을 먹음")).toBeInTheDocument();
    expect(screen.getByText("소프트웨어 엔지니어")).toBeInTheDocument();
    expect(memoryRequests().some((url) => url.searchParams.get("record_type") === "entity_facts" && url.searchParams.get("offset") === "20" && url.searchParams.get("limit") === "20")).toBe(true);
    expect(memoryRequests().filter((url) => url.searchParams.get("record_type") === "observations").every((url) => url.searchParams.get("offset") === "0")).toBe(true);
  });

  it("전체 정보는 유형을 제한하지 않고 현재·이전·전체 상태를 조회하며 필터 변경 시 첫 페이지로 돌아간다", async () => {
    render(<Person id="person-a" onNavigate={() => {}} />);
    fireEvent.click(await screen.findByRole("button", { name: "전체 정보" }));
    expect(screen.getByLabelText("정보 상태")).toHaveValue("active");
    await screen.findByText("이전 유형의 보존된 정보");
    expect(screen.getByText("오래된 친구 관계")).toBeInTheDocument();
    expect(screen.getByText("최근 함께 점심을 먹음")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    await screen.findByText("프로필 값 22");
    expect(memoryRequests().at(-1)?.searchParams.get("offset")).toBe("20");
    fireEvent.change(screen.getByLabelText("정보 상태"), { target: { value: "history" } });
    await screen.findByText("철회된 직업 정보");
    expect(memoryRequests().at(-1)?.searchParams.get("offset")).toBe("0");
    expect(memoryRequests().at(-1)?.searchParams.get("status")).toBe("history");
    expect(memoryRequests().at(-1)?.searchParams.has("record_type")).toBe(false);
    fireEvent.change(screen.getByLabelText("정보 상태"), { target: { value: "all" } });
    await screen.findByText("이전 유형의 보존된 정보");
    expect(memoryRequests().at(-1)?.searchParams.get("status")).toBe("all");
    expect(memoryRequests().at(-1)?.searchParams.get("offset")).toBe("0");
    fireEvent.click(screen.getByRole("button", { name: "프로필" }));
    await screen.findByText("5월 12일");
    expect(memoryRequests().at(-1)?.searchParams.get("record_type")).toBe("entity_facts");
    expect(memoryRequests().at(-1)?.searchParams.get("offset")).toBe("0");
  });

  it("개요에서 프로필·관계·기억 추가를 각각 맞는 입력 형식으로 연다", async () => {
    render(<Person id="person-a" onNavigate={() => {}} />);
    for (const [name, kind] of [["프로필 추가", "entity_facts"], ["관계 추가", "entity_edges"], ["기억 추가", "observations"]]) {
      fireEvent.click(await screen.findByRole("button", { name }));
      const dialog = await screen.findByRole("dialog", { name });
      await waitFor(() => expect(within(dialog).getByLabelText("기억 구분")).toHaveValue(kind));
      fireEvent.click(within(dialog).getByRole("button", { name: "닫기" }));
      await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    }
    expect(fetchMock.mock.calls.every(([, init]) => !init?.method || init.method === "GET")).toBe(true);
  });

  it("추가 인물 속성의 문자열·구조화 값·빈 값도 보존된 형태로 열어볼 수 있다", async () => {
    render(<Person id="person-a" onNavigate={() => {}} />);
    const summary = await screen.findByText("추가 저장 정보 (5개)");
    fireEvent.click(summary);
    expect(screen.getByText("속성에만 보존된 직업")).toBeVisible();
    expect(screen.getByText(/"location": "서울"/)).toBeVisible();
    expect(screen.getByText("미설정", { exact: true })).toBeVisible();
    expect(screen.getByText("false", { exact: true })).toBeVisible();
    expect(screen.getByText("0", { exact: true })).toBeVisible();
    expect(screen.queryByText("entities:technical-reference")).not.toBeInTheDocument();
  });
});
