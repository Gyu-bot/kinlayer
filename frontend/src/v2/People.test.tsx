import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { People } from "./People";
import { Graph } from "./Graph";
import { Shell } from "./Shell";
import type { PersonSummary } from "./data";

const ontology = {
  fact_types: [],
  claim_bases: [],
  participant_roles: [],
  observation_types: [],
  edge_types: [
    { relation_type: "parent_of", label: "부모", inverse_label: "자녀", active: true, directed_default: true },
    {
      relation_type: "friend",
      active: true,
      directed_default: false,
      description: "Friend",
    },
    {
      relation_type: "coworker",
      active: true,
      directed_default: false,
      description: "Coworker",
    },
    {
      relation_type: "manager_of",
      active: true,
      directed_default: true,
      description: "Manager of",
    },
    {
      relation_type: "new_relation",
      active: true,
      directed_default: true,
      description: "새 관계 설명",
    },
  ],
};
function person(id: string, name: string): PersonSummary {
  return {
    id,
    display_name: name,
    canonical_name: null,
    status: "active",
    system_role: null,
    is_system: false,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    last_referenced_at: null,
    properties: {},
    aliases: [`${name} 별칭`],
    relations: [],
    profile_facts: [],
    memory_count: 0,
  };
}
const alpha = person("person-a", "김민지"),
  beta = person("person-b", "박서준");
const page = (items: PersonSummary[], total = items.length, offset = 0) => ({
  items,
  total,
  limit: 25,
  offset,
});
function response(payload: unknown, status = 200) {
  return Promise.resolve({
    ok: status < 400,
    status,
    json: () => Promise.resolve(payload),
  } as Response);
}
function setupFetch(
  handler: (url: URL, init?: RequestInit) => Promise<Response> | undefined,
) {
  const mock = vi.fn((url: string, init?: RequestInit) => {
    const parsed = new URL(url);
    if (parsed.pathname === "/api/ontology") return response(ontology);
    const result = handler(parsed, init);
    if (!result) throw new Error(`Unexpected API request ${url}`);
    return result;
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

beforeEach(() => {
  window.history.replaceState({}, "", "/people");
  localStorage.clear();
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: () => ({ matches: false }),
  });
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute("open");
  };
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("real API people directory", () => {
  it("한 관계의 양 끝점을 서버에 정의된 부모와 자녀 역할로 표시한다", async () => {
    const linked = [
      { ...alpha, relations: [{ relation_type: "parent_of", directed: true, from_entity_id: "person-a", to_entity_id: "self" }] },
      { ...beta, relations: [{ relation_type: "parent_of", directed: true, from_entity_id: "self", to_entity_id: "person-b" }] },
    ];
    setupFetch((url) => url.pathname === "/api/people" ? response(page(linked)) : undefined);
    render(<People onNavigate={vi.fn()} />);
    await screen.findByRole("heading", { name: "김민지" });
    const rows = document.querySelectorAll('.relation-tags');
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent('부모');
    expect(rows[1]).toHaveTextContent('자녀');
  });

  it("uses alias search and clears the old preview for an empty result", async () => {
    const fetch = setupFetch((url) =>
      url.pathname === "/api/people"
        ? response(page(url.searchParams.get("q") ? [] : [alpha]))
        : undefined,
    );
    render(<People onNavigate={vi.fn()} />);
    expect(
      await screen.findByRole("heading", { name: "김민지" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("참조 기록 없음")).toHaveLength(2);
    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "없는 별칭" },
    });
    expect(
      await screen.findByText("일치하는 사람이 없어요"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "김민지" }),
    ).not.toBeInTheDocument();
    expect(
      fetch.mock.calls.some(
        ([url]) => new URL(url).searchParams.get("q") === "없는 별칭",
      ),
    ).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "검색과 필터 초기화" }));
    expect(
      await screen.findByRole("heading", { name: "김민지" }),
    ).toBeInTheDocument();
  });

  it("sends pagination, relation, and sort to the server and resets pagination on filtering", async () => {
    const fetch = setupFetch((url) =>
      url.pathname === "/api/people"
        ? response(
            page(
              url.searchParams.get("offset") === "25" ? [beta] : [alpha],
              26,
              Number(url.searchParams.get("offset")),
            ),
          )
        : undefined,
    );
    render(<People onNavigate={vi.fn()} />);
    await screen.findByRole("heading", { name: "김민지" });
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    expect(
      await screen.findByRole("heading", { name: "박서준" }),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("모든 관계 유형"), {
      target: { value: "manager_of" },
    });
    await screen.findByRole("heading", { name: "김민지" });
    fireEvent.change(screen.getByLabelText("사람 정렬"), {
      target: { value: "name" },
    });
    await waitFor(() =>
      expect(
        fetch.mock.calls.some(([raw]) => {
          const url = new URL(raw);
          return (
            url.searchParams.get("sort") === "name" &&
            url.searchParams.get("relation_type") === "manager_of" &&
            url.searchParams.get("offset") === "0"
          );
        }),
      ).toBe(true),
    );
    expect(
      screen.getByRole("option", { name: "새 관계 설명" }),
    ).toBeInTheDocument();
  });

  it("ignores an old search response even when fetch resolves after abort", async () => {
    let resolveOld: ((value: Response) => void) | undefined;
    setupFetch((url) => {
      if (url.pathname !== "/api/people") return;
      if (url.searchParams.get("q") === "old")
        return new Promise((resolve) => {
          resolveOld = resolve;
        });
      return response(
        page(url.searchParams.get("q") === "new" ? [beta] : [alpha]),
      );
    });
    render(<People onNavigate={vi.fn()} />);
    await screen.findByRole("heading", { name: "김민지" });
    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "old" },
    });
    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "new" },
    });
    await screen.findByRole("heading", { name: "박서준" });
    await act(async () => {
      resolveOld?.(await response(page([alpha])));
    });
    expect(screen.getByRole("heading", { name: "박서준" })).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "김민지" }),
    ).not.toBeInTheDocument();
  });

  it("retries a failed read and uses one name-only POST for new identity", async () => {
    let reads = 0;
    const navigate = vi.fn();
    const fetch = setupFetch((url, init) => {
      if (url.pathname === "/api/people")
        return ++reads === 1
          ? response({ error: { message: "연결 실패" } }, 503)
          : response(page([alpha]));
      if (url.pathname === "/api/entities" && init?.method === "POST")
        return response(person("new-person", "새 사람"));
    });
    render(<People onNavigate={navigate} />);
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "다시 시도" }));
    await screen.findByRole("heading", { name: "김민지" });
    fireEvent.click(screen.getByRole("button", { name: "사람 추가" }));
    const modal = within(screen.getByRole("dialog"));
    fireEvent.click(modal.getByRole("button", { name: "사람 추가" }));
    expect(modal.getByRole("alert")).toHaveTextContent("이름을 입력해 주세요");
    expect(
      fetch.mock.calls.filter(([, init]) => init?.method === "POST"),
    ).toHaveLength(0);
    fireEvent.change(modal.getByLabelText(/이름/), {
      target: { value: "  새 사람  " },
    });
    fireEvent.click(modal.getByRole("button", { name: "사람 추가" }));
    await waitFor(() =>
      expect(navigate).toHaveBeenCalledWith("/people/new-person"),
    );
    const writes = fetch.mock.calls.filter(
      ([, init]) => init?.method === "POST",
    );
    expect(writes).toHaveLength(1);
    expect(JSON.parse(String(writes[0][1]?.body))).toEqual({
      entity_type: "person",
      display_name: "새 사람",
      created_by: "user",
    });
  });

  it("keeps failed create input and never reports a successful navigation", async () => {
    const navigate = vi.fn();
    setupFetch((url, init) =>
      url.pathname === "/api/people"
        ? response(page([]))
        : init?.method === "POST"
          ? response({ error: { message: "저장 실패" } }, 503)
          : undefined,
    );
    render(<People onNavigate={navigate} />);
    await screen.findByText("아직 등록된 사람이 없어요");
    fireEvent.click(screen.getByRole("button", { name: "사람 추가" }));
    const modal = within(screen.getByRole("dialog"));
    fireEvent.change(modal.getByLabelText(/이름/), {
      target: { value: "보존할 이름" },
    });
    fireEvent.click(modal.getByRole("button", { name: "사람 추가" }));
    expect(await modal.findByRole("alert")).toHaveTextContent("저장 실패");
    expect(modal.getByLabelText(/이름/)).toHaveValue("보존할 이름");
    expect(navigate).not.toHaveBeenCalled();
  });

  it("renders typed yearless birthday and inferred basis without policy or approval labels", async () => {
    const item = {
      ...alpha,
      profile_facts: [
        {
          id: "fact",
          entity_id: alpha.id,
          fact_type: "birth_date",
          content: "생일",
          value: { month: 7, day: 10 },
          claim_basis: "inferred" as const,
          confidence: 0.7,
          status: "active",
          valid_from: null,
          valid_to: null,
          created_at: alpha.created_at,
          updated_at: alpha.updated_at,
        },
      ],
    };
    setupFetch((url) =>
      url.pathname === "/api/people" ? response(page([item])) : undefined,
    );
    render(<People onNavigate={vi.fn()} />);
    await screen.findByRole("heading", { name: "김민지" });
    expect(screen.getAllByText(/7월 10일/).length).toBeGreaterThan(0);
    expect(screen.getAllByText("추론").length).toBeGreaterThan(0);
    expect(
      screen.queryByText(/확인된 인물|확인됨|AI 사용 범위|사용 전 확인/),
    ).not.toBeInTheDocument();
  });
});

describe("API relationship graph", () => {
  const graph = {
    focal_entity_id: "actual-self",
    depth: 1,
    filters_applied: {},
    nodes: [
      {
        entity_id: "actual-self",
        display_name: "사용자",
        entity_type: "person",
        status: "active",
        is_focal: true,
      },
      {
        entity_id: "person-a",
        display_name: "김민지",
        entity_type: "person",
        status: "active",
        is_focal: false,
      },
    ],
    edges: [
      {
        edge_id: "edge-a",
        from_entity_id: "actual-self",
        to_entity_id: "person-a",
        relation_type: "manager_of",
        directed: true,
        status: "active",
        confidence: 0.6,
      },
    ],
  };

  it("uses actual protected self, directed ontology options, and the selected edge's real source", async () => {
    const fetch = setupFetch((url) => {
      if (url.pathname === "/api/entities")
        return response(
          page([
            {
              ...alpha,
              id: "actual-self",
              display_name: "사용자",
              system_role: "self",
            },
          ]),
        );
      if (url.pathname === "/api/graph/ego/actual-self") return response(graph);
      if (url.pathname === "/api/memories/entity_edges/edge-a")
        return response({
          record_ref: "entity_edges:edge-a",
          record_type: "entity_edges",
          id: "edge-a",
          content: "업무 보고 관계로 추정됨",
          claim_basis: "inferred",
          confidence: 0.6,
          status: "active",
          is_current: true,
          valid_from: null,
          valid_to: null,
          payload: {},
          sources: [
            {
              episode_id: "source-a",
              actor: "사용자",
              excerpt: "함께 프로젝트를 맡았다고 했어",
              occurred_at: null,
            },
          ],
        });
    });
    render(<Graph onNavigate={vi.fn()} />);
    await screen.findByRole("heading", { name: "사용자의 관계" });
    expect(
      fetch.mock.calls.some(([url]) => url.includes("/api/graph/ego/self")),
    ).toBe(false);
    expect(
      screen.getByRole("option", { name: "관리하는 관계 (방향 있음)" }),
    ).toBeInTheDocument();
    expect(
      document.querySelector(
        '.graph-edge[marker-end="url(#graph-direction-arrow)"]',
      ),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "사용자 → 김민지 · 관리하는 관계" }),
    );
    expect(
      await screen.findByText("업무 보고 관계로 추정됨"),
    ).toBeInTheDocument();
    expect(screen.getByText("추론한 내용")).toBeInTheDocument();
    expect(
      screen.getByText("함께 프로젝트를 맡았다고 했어"),
    ).toBeInTheDocument();
    expect(screen.getByText(/발언 시점 미상/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "그래프 확대" }));
    expect(screen.getByText("120%")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "그래프 전체 맞춤" }));
    expect(screen.getByText("100%")).toBeInTheDocument();
  });

  it("renders a merged focal URL using the response's canonical center and relation direction", async () => {
    window.history.replaceState({}, "", "/graph?focal=merged-person");
    const canonicalGraph = {
      ...graph,
      focal_entity_id: "person-a",
      nodes: [
        { ...graph.nodes[1], is_focal: true },
        { ...graph.nodes[1], entity_id: "person-b", display_name: "박서준" },
      ],
      edges: [
        {
          ...graph.edges[0],
          from_entity_id: "person-a",
          to_entity_id: "person-b",
        },
      ],
    };
    setupFetch((url) => {
      if (url.pathname === "/api/entities")
        return response(page([alpha, beta]));
      if (url.pathname === "/api/graph/ego/merged-person")
        return response(canonicalGraph);
      if (url.pathname === "/api/memories/entity_edges/edge-a")
        return response({
          record_ref: "entity_edges:edge-a",
          record_type: "entity_edges",
          id: "edge-a",
          content: "함께 일하는 관계",
          claim_basis: "reported",
          status: "active",
          is_current: true,
          valid_from: null,
          valid_to: null,
          sources: [],
          payload: {},
        });
    });
    render(<Graph onNavigate={vi.fn()} />);
    await screen.findByRole("heading", { name: "김민지의 관계" });
    const center = screen.getByRole("button", {
      name: "김민지 선택 · 중심 인물",
    });
    expect(center).toHaveAttribute("aria-pressed", "true");
    expect(center.querySelector("circle")).toHaveAttribute("r", "38");
    const mobile = within(
      document.querySelector(".graph-mobile-list") as HTMLElement,
    );
    const relation = mobile.getByRole("button", {
      name: /박서준.*중심에서 상대에게/,
    });
    fireEvent.click(relation);
    expect(screen.getByRole("heading", { name: "박서준" })).toBeInTheDocument();
    await screen.findByText("함께 일하는 관계");
    fireEvent.change(screen.getByRole("combobox", { name: "관계 유형" }), {
      target: { value: "manager_of" },
    });
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "김민지 선택 · 중심 인물" }),
      ).toHaveAttribute("aria-pressed", "true"),
    );
    fireEvent.click(screen.getByRole("button", { name: "김민지" }));
    const modal = within(screen.getByRole("dialog"));
    expect(modal.getByRole("combobox", { name: "중심 인물" })).toHaveValue(
      "person-a",
    );
  });

  it("preserves missing-source excerpts and actors while hiding the broken episode link", async () => {
    setupFetch((url) => {
      if (url.pathname === "/api/entities")
        return response(
          page([{ ...alpha, id: "actual-self", system_role: "self" }]),
        );
      if (url.pathname === "/api/graph/ego/actual-self") return response(graph);
      if (url.pathname === "/api/memories/entity_edges/edge-a")
        return response({
          record_ref: "entity_edges:edge-a",
          record_type: "entity_edges",
          id: "edge-a",
          content: "이전 출처에서 연결된 관계",
          claim_basis: "reported",
          status: "active",
          is_current: true,
          valid_from: null,
          valid_to: null,
          payload: {},
          sources: [
            {
              episode_id: "missing-episode",
              missing: true,
              actor: "말해 준 사람",
              excerpt: "이 문장은 증거에 남아 있어요",
              occurred_at: null,
            },
          ],
        });
    });
    render(<Graph onNavigate={vi.fn()} />);
    fireEvent.click(
      await screen.findByRole("button", {
        name: "사용자 → 김민지 · 관리하는 관계",
      }),
    );
    expect(
      await screen.findByText("이 문장은 증거에 남아 있어요"),
    ).toBeInTheDocument();
    expect(screen.getByText(/말해 준 사람/)).toBeInTheDocument();
    expect(
      screen.getByText("이전 출처가 연결되어 있지 않아요."),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "출처 보기" }),
    ).not.toBeInTheDocument();
  });

  it("preserves an invalid requested focal ID and reports the error rather than replacing it", async () => {
    window.history.replaceState({}, "", "/graph?focal=missing-person");
    const fetch = setupFetch((url) => {
      if (url.pathname === "/api/entities")
        return response(
          page([{ ...alpha, id: "actual-self", system_role: "self" }]),
        );
      if (url.pathname === "/api/graph/ego/missing-person")
        return response({ error: { message: "존재하지 않는 인물" } }, 404);
    });
    render(<Graph onNavigate={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "존재하지 않는 인물",
    );
    expect(
      fetch.mock.calls.some(([url]) =>
        url.includes("/api/graph/ego/actual-self"),
      ),
    ).toBe(false);
    expect(document.querySelector(".graph-svg")).not.toBeInTheDocument();
  });

  it("does not replace a user-selected focal person when a delayed self lookup finishes", async () => {
    let resolveSelf: ((value: Response) => void) | undefined;
    const fetch = setupFetch((url) => {
      if (url.pathname === "/api/entities") {
        if (url.searchParams.get("system_role") === "self")
          return new Promise((resolve) => {
            resolveSelf = resolve;
          });
        return response(page([alpha, beta]));
      }
      if (url.pathname === "/api/graph/ego/person-a")
        return response({ ...graph, focal_entity_id: "person-a" });
      if (url.pathname === "/api/graph/ego/actual-self") return response(graph);
    });
    render(<Graph onNavigate={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "불러오는 중…" }));
    const modal = within(screen.getByRole("dialog"));
    await modal.findByRole("option", { name: /김민지/ });
    fireEvent.change(modal.getByRole("combobox", { name: "중심 인물" }), {
      target: { value: "person-a" },
    });
    fireEvent.click(modal.getByRole("button", { name: "이 인물을 중심으로" }));
    await screen.findByRole("heading", { name: "김민지의 관계" });
    await act(async () => {
      resolveSelf?.(
        await response(
          page([{ ...alpha, id: "actual-self", system_role: "self" }]),
        ),
      );
    });
    expect(
      screen.getByRole("heading", { name: "김민지의 관계" }),
    ).toBeInTheDocument();
    expect(
      fetch.mock.calls.some(([url]) =>
        url.includes("/api/graph/ego/actual-self"),
      ),
    ).toBe(false);
  });
});

it("keeps all main routes and secondary routes reachable in the compact shell", () => {
  const navigate = vi.fn();
  render(
    <Shell path="/people" onNavigate={navigate}>
      <h1>사람</h1>
    </Shell>,
  );
  const main = within(screen.getByRole("navigation", { name: "주요 탐색" }));
  for (const name of ["사람", "기억", "관계 그래프", "변경 이력"])
    expect(main.getByRole("link", { name })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "검색과 설정 메뉴" }));
  const menu = within(screen.getByRole("navigation", { name: "검색과 설정" }));
  fireEvent.click(menu.getByRole("link", { name: "설정" }));
  expect(navigate).toHaveBeenCalledWith("/settings");
});
