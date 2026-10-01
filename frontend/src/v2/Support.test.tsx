import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";

import { Diagnostics, operationsCsv, Search, Settings } from "./Support";
import type { AgentWriteOperation } from "../types/agentOperations";

const fetchMock = vi.fn();
const response = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
const page = <T,>(items: T[], total = items.length, offset = 0) => ({
  items,
  total,
  offset,
  limit: 25,
});
const embedding = {
  provider: "openai_compatible",
  model: "example-model",
  dim: 1024,
  status: "ready",
  api_url_configured: true,
  api_key_configured: true,
  observations: { total: 10, pending: 10, ready: 0, failed: 0, stale: 0 },
};
const operation: AgentWriteOperation = {
  id: "operation-1",
  operation_type: "candidate_submit",
  source_path: "/api/candidates",
  actor: "ai_agent",
  result_status: "success",
  api_error_code: null,
  request_summary: {
    content_excerpt: "저장한 내용",
    ai_use_policy: "never_surface",
  },
  diagnostics: {},
  related_refs: {},
  candidate_id: "candidate-1",
  correction_id: null,
  episode_id: "episode-1",
  canonical_record_ref: "entity_facts:fact-1",
  bounded_excerpt: "원래 발언",
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
};

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
  window.localStorage.clear();
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("새 설정 화면", () => {
  it("인증 실패를 확인 불가로 표시하고 토큰 저장·삭제 후 다시 검사하며 비밀 값을 표시하지 않는다", async () => {
    fetchMock.mockImplementation(async (input: string, init: RequestInit) => {
      const path = new URL(input).pathname;
      if (path === "/api/system/health")
        return response({ status: "ok", database: "ok", embedding: "ready" });
      const authorized =
        (init.headers as Record<string, string>).Authorization ===
        "Bearer private-token";
      if (!authorized)
        return response(
          { error: { code: "unauthorized", message: "Token required" } },
          401,
        );
      if (path === "/api/system/config")
        return response({
          auth_token_configured: true,
          bind_host: "0.0.0.0",
          embedding,
        });
      return response(embedding);
    });
    render(<Settings />);
    expect(await screen.findByRole("alert")).toHaveTextContent("연결 인증");
    expect(screen.getByText("서버 인증").nextElementSibling).toHaveTextContent(
      "확인하지 못함",
    );
    const input = screen.getByLabelText("API 토큰");
    fireEvent.change(input, { target: { value: "private-token" } });
    fireEvent.click(screen.getByRole("button", { name: "토큰 저장" }));
    await waitFor(() =>
      expect(
        screen.getByText("서버 인증").nextElementSibling,
      ).toHaveTextContent("토큰 필요"),
    );
    expect(input).toHaveValue("");
    expect(document.body.textContent).not.toContain("private-token");
    expect(
      screen.getByText("검색 준비됨").nextElementSibling,
    ).toHaveTextContent("0건");
    expect(
      screen.getByText("서버 설정 상태").nextElementSibling,
    ).toHaveTextContent("준비됨");
    fireEvent.click(screen.getByRole("button", { name: "토큰 삭제" }));
    await screen.findByRole("alert");
    expect(window.localStorage.getItem("kinlayer.apiToken")).toBeNull();
    expect(screen.getByText("서버 인증").nextElementSibling).toHaveTextContent(
      "확인하지 못함",
    );
    expect(screen.queryByText("example-model")).not.toBeInTheDocument();
  });
});

describe("새 검색 화면", () => {
  const fact = {
    id: "fact-1",
    fact_type: "birthday",
    content: "생일은 5월",
    claim_basis: "reported",
    confidence: 0.8,
    value: { year: null, month: 5, day: null, precision: "month" },
    valid_from: null,
    valid_to: null,
  };
  const source = {
    record_type: "fact",
    record_id: "fact-1",
    episode_id: "source-1",
    excerpt: "5월에 생일이에요.",
    source_occurred_at: null,
  };
  const retrieve = {
    matched_entities: [
      {
        entity_id: "person-2",
        display_name: "다음 인물",
        score: 0.8,
        confidence_band: "medium",
        surface_bucket: "safe_surface",
        ai_use_policy: "freely_use",
        match_reasons: [],
        profile_facts: [fact],
        observations: [],
      },
    ],
    observations: [],
    provenance: [source],
    ambiguity_detected: true,
    debug: {},
    score_breakdown: {},
  };
  const pack = {
    context_pack: {
      matched_entities: [],
      recent_context: [],
      stable_context: [],
      cautions: [],
      provenance: [source],
      ambiguity_detected: false,
      confidence: "medium",
      suggested_response_policy: "never_surface",
      buckets: {},
    },
    debug: {},
  };

  it("서버 인물 검색·페이지 이동과 현재 기억 참조·부분 날짜·근거·출처를 보존한다", async () => {
    fetchMock.mockImplementation(async (input: string) => {
      const url = new URL(input);
      if (url.pathname === "/api/entities") {
        return response(
          url.searchParams.get("offset") === "20"
            ? page([{ id: "person-2", display_name: "다음 인물" }], 21, 20)
            : page([{ id: "person-1", display_name: "첫 인물" }], 21),
        );
      }
      return response(url.pathname.endsWith("retrieve") ? retrieve : pack);
    });
    const navigate = vi.fn();
    render(<Search onNavigate={navigate} />);
    await screen.findByRole("option", { name: "첫 인물" });
    fireEvent.change(screen.getByLabelText("관련 인물 찾기"), {
      target: { value: "별칭" },
    });
    fireEvent.click(screen.getByRole("button", { name: "인물 검색" }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([url]) => new URL(url).searchParams.get("q") === "별칭",
        ),
      ).toBe(true),
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "다음" })).not.toBeDisabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    await screen.findByRole("option", { name: "다음 인물" });
    fireEvent.change(screen.getByLabelText("중심 인물 (선택)"), {
      target: { value: "person-2" },
    });
    fireEvent.change(screen.getByLabelText("찾을 내용"), {
      target: { value: "생일" },
    });
    fireEvent.change(screen.getByLabelText("현재 상황 (선택)"), {
      target: { value: "선물을 준비해요" },
    });
    fireEvent.click(screen.getByRole("button", { name: "기억 검색" }));
    expect(await screen.findByText("생일은 5월")).toBeInTheDocument();
    expect(
      screen.getByText(/연도 미상 5월 · 월까지만 기록/),
    ).toBeInTheDocument();
    expect(screen.getByText("전해 들은 내용")).toBeInTheDocument();
    expect(screen.getByText(/여러 인물이나 해석/)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(
      /freely_use|never_surface|safe_surface/,
    );
    const retrieveCall = fetchMock.mock.calls.find(
      ([url]) => new URL(url).pathname === "/api/context/retrieve",
    );
    const packCall = fetchMock.mock.calls.find(
      ([url]) => new URL(url).pathname === "/api/context/pack",
    );
    expect(JSON.parse(retrieveCall![1].body)).toMatchObject({
      query: "생일",
      focal_entity_id: "person-2",
      include_debug: true,
    });
    expect(JSON.parse(packCall![1].body)).toMatchObject({
      situation: "선물을 준비해요",
    });
    fireEvent.click(screen.getByRole("link", { name: "기억 보기" }));
    expect(navigate).toHaveBeenLastCalledWith(
      "/memories?record=entity_facts%3Afact-1",
    );
    fireEvent.click(screen.getByRole("link", { name: "출처 보기" }));
    expect(navigate).toHaveBeenLastCalledWith("/sources/source-1");
  });

  it("후속 검색의 인증 실패 시 이전 결과를 지우고 실패 원인을 표시한다", async () => {
    let fail = false;
    fetchMock.mockImplementation(async (input: string) => {
      const path = new URL(input).pathname;
      if (path === "/api/entities") return response(page([]));
      if (fail)
        return response(
          { error: { code: "unauthorized", message: "Token required" } },
          401,
        );
      return response(path.endsWith("retrieve") ? retrieve : pack);
    });
    render(<Search />);
    fireEvent.change(screen.getByLabelText("찾을 내용"), {
      target: { value: "생일" },
    });
    fireEvent.click(screen.getByRole("button", { name: "기억 검색" }));
    await screen.findByText("생일은 5월");
    fail = true;
    fireEvent.click(screen.getByRole("button", { name: "기억 검색" }));
    await waitFor(() => expect(screen.getAllByRole("alert")).toHaveLength(2));
    expect(screen.queryByText("생일은 5월")).not.toBeInTheDocument();
    expect(screen.getAllByRole("alert")[0]).toHaveTextContent("연결 인증");
  });
});

describe("새 운영 기록 화면", () => {
  it("작업 필터와 페이지를 서버에 전달하고 공식 JSONL 및 읽기 전용 과거 후보를 제공한다", async () => {
    const createUrl = vi.fn(() => "blob:export");
    Object.defineProperty(URL, "createObjectURL", {
      value: createUrl,
      configurable: true,
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      value: vi.fn(),
      configurable: true,
    });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    fetchMock.mockImplementation(async (input: string) => {
      const url = new URL(input);
      if (url.pathname.endsWith("/export"))
        return new Response('{"record_type":"manifest"}\n', { status: 200 });
      if (url.pathname === "/api/candidates")
        return response(
          page([
            {
              id: "candidate-1",
              candidate_type: "profile_field",
              payload: { content: "과거 제안", ai_use_policy: "never_surface" },
              evidence: [],
              status: "accepted",
              created_by: "ai_agent",
              created_at: operation.created_at,
              updated_at: operation.updated_at,
              resolved_at: operation.created_at,
              resolved_by: "user",
              resolution_note: null,
              target_entity_id: null,
              canonical_record_ref: "entity_facts:fact-1",
              supersedes_candidate_id: null,
              supersedes_record_ref: null,
              confidence: 1,
            },
          ]),
        );
      return response(
        page(
          [{ ...operation, id: `operation-${url.searchParams.get("offset")}` }],
          26,
          Number(url.searchParams.get("offset")),
        ),
      );
    });
    render(<Diagnostics />);
    await screen.findByText("과거 후보 제출", { selector: "strong" });
    fireEvent.change(screen.getByLabelText("작성 주체"), {
      target: { value: "agent-foo" },
    });
    fireEvent.change(screen.getByLabelText("오류 여부"), {
      target: { value: "true" },
    });
    fireEvent.click(screen.getByRole("button", { name: "필터 적용" }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([input]) =>
            new URL(input).searchParams.get("actor") === "agent-foo" &&
            new URL(input).searchParams.get("has_error") === "true",
        ),
      ).toBe(true),
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "다음" })).not.toBeDisabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([input]) => new URL(input).searchParams.get("offset") === "25",
        ),
      ).toBe(true),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "JSONL 내보내기 · 최대 200건" }),
      ).not.toBeDisabled(),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "JSONL 내보내기 · 최대 200건" }),
    );
    await waitFor(() => expect(createUrl).toHaveBeenCalledOnce());
    const exportUrl = new URL(
      fetchMock.mock.calls.find(([input]) =>
        new URL(input).pathname.endsWith("/export"),
      )![0],
    );
    expect(exportUrl.searchParams.get("limit")).toBe("200");
    expect(exportUrl.searchParams.get("actor")).toBe("agent-foo");
    fireEvent.click(screen.getByRole("button", { name: "과거 후보 이력" }));
    await screen.findByText("과거 제안");
    expect(
      screen.getByText("과거 제안 상세").parentElement,
    ).not.toHaveTextContent("never_surface");
    expect(
      screen.queryByRole("button", { name: /승인|반영|거절/ }),
    ).not.toBeInTheDocument();
    const list = screen.getByRole("region", { name: "과거 후보 목록" });
    expect(within(list).getByText("기억 보기")).toHaveAttribute(
      "href",
      "/memories?record=entity_facts%3Afact-1",
    );
    expect(
      fetchMock.mock.calls.every(
        ([, init]) => !init?.method || init.method === "GET",
      ),
    ).toBe(true);
  });

  it("현재 페이지 CSV의 값과 줄바꿈을 보존하고 스프레드시트 수식 실행을 방지한다", () => {
    const csv = operationsCsv([
      {
        ...operation,
        bounded_excerpt: '=HYPERLINK("https://example.test")\n인용',
      },
    ]);
    expect(csv.startsWith("\uFEFF")).toBe(true);
    expect(csv).toContain('"\'=HYPERLINK(""https://example.test"")\n인용"');
    expect(csv).toContain('"entity_facts:fact-1"');
    expect(csv).not.toContain("never_surface");
  });

  it("과거 인물 참조는 인물로 열고 소유자를 모르는 별칭과 미지원 참조는 읽기 전용으로 남긴다", async () => {
    fetchMock.mockImplementation(async () =>
      response(
        page([
          {
            ...operation,
            id: "entity-op",
            canonical_record_ref: "entities:person-1",
          },
          {
            ...operation,
            id: "alias-op",
            canonical_record_ref: "entity_aliases:alias-1",
          },
          {
            ...operation,
            id: "unknown-op",
            canonical_record_ref: "historical_records:record-1",
          },
        ]),
      ),
    );
    const navigate = vi.fn();
    render(<Diagnostics onNavigate={navigate} />);
    await screen.findByText("entity_aliases:alias-1");
    const entityLink = screen.getByText("인물 보기");
    expect(entityLink).toHaveAttribute("href", "/people/person-1");
    fireEvent.click(entityLink);
    expect(navigate).toHaveBeenCalledWith("/people/person-1");
    expect(document.querySelector('a[href^="/memories"]')).toBeNull();
    expect(
      screen.getByText("entity_aliases:alias-1").closest("details"),
    ).toHaveTextContent("과거 기록 식별자");
    expect(
      screen.getByText("historical_records:record-1").closest("details"),
    ).toHaveTextContent("과거 기록 식별자");
  });

  it("별칭 후보는 알고 있는 대상 인물로 연결하며 별칭 ID를 기억 API로 보내지 않는다", async () => {
    fetchMock.mockImplementation(async (input: string) => {
      if (new URL(input).pathname === "/api/candidates")
        return response(
          page([
            {
              id: "alias-candidate",
              candidate_type: "alias",
              target_entity_id: "person-1",
              payload: { content: "과거 별칭 제안" },
              evidence: [],
              confidence: 1,
              status: "accepted",
              created_by: "ai_agent",
              created_at: operation.created_at,
              updated_at: operation.updated_at,
              resolved_at: operation.created_at,
              resolved_by: "user",
              resolution_note: null,
              canonical_record_ref: "entity_aliases:alias-1",
              supersedes_candidate_id: null,
              supersedes_record_ref: null,
            },
          ]),
        );
      return response(page([]));
    });
    render(<Diagnostics />);
    await screen.findByText("조건에 맞는 에이전트 작업이 없습니다.");
    fireEvent.click(screen.getByRole("button", { name: "과거 후보 이력" }));
    const aliasLink = await screen.findByText("별칭의 인물 보기");
    expect(aliasLink).toHaveAttribute("href", "/people/person-1");
    expect(document.querySelector('a[href^="/memories"]')).toBeNull();
    expect(
      fetchMock.mock.calls.some(([input]) =>
        new URL(input).pathname.startsWith("/api/memories"),
      ),
    ).toBe(false);
  });
});
