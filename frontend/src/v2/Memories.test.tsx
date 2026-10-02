import {
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import {
  ChangeRows,
  Changes,
  Memories,
  MemoryDetail,
  SourceEvidence,
  SourcePage,
} from "./Memories";
import { Person } from "./Person";
import type { MemoryItem } from "./data";

const fetchMock = vi.fn();
const memoryConfig = {
  memory_write: {
    endpoint: "/api/memories",
    contract_version: "2",
    review_required: false,
  },
};
const response = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
const page = <T,>(
  items: T[],
  total = items.length,
  offset = 0,
  limit = 20,
) => ({ items, total, offset, limit });
const item: MemoryItem = {
  id: "fact-old",
  record_ref: "entity_facts:fact-old",
  record_type: "entity_facts",
  content: "--05",
  claim_basis: "reported",
  confidence: 0.8,
  status: "active",
  is_current: true,
  created_at: "2026-09-30T00:00:00Z",
  updated_at: "2026-10-01T00:00:00.123456Z",
  valid_from: null,
  valid_to: null,
  payload: {
    entity_id: "person-a",
    fact_type: "birthday",
    content: "--05",
    value: { year: null, month: 5, day: null, precision: "month" },
    claim_basis: "reported",
    confidence: 0.8,
    valid_from: null,
    valid_to: null,
  },
  entities: [{ id: "person-a", display_name: "민지", role: "subject" }],
  sources: [
    {
      episode_id: "source-a",
      actor: "민지",
      source_type: "manual_entry",
      source_ref: "대화 발췌 위치",
      excerpt: "생일은 5월이에요",
      occurred_at: null,
    },
  ],
};
const history = {
  id: "change-a",
  request_id: "request-a",
  change_kind: "correct",
  old_record_ref: item.record_ref,
  new_record_ref: "entity_facts:fact-new",
  source_episode_id: "source-change",
  actor: "user",
  reason: "생일 월 정정",
  created_at: "2026-10-01T03:00:00Z",
};
const identityMigration = {
  ...history,
  id: "change-migrate",
  request_id: "migration-person-a",
  change_kind: "migrate",
  old_record_ref: "entities:person-a",
  new_record_ref: "entities:person-a",
  source_episode_id: null,
  actor: "system",
  reason: "기존 인물 기록 이관",
};
const ontology = {
  fact_types: [
    { value: "birthday", is_active: true, support_level: "supported" },
  ],
  edge_types: [],
  observation_types: [],
  claim_bases: [{ value: "reported" }],
  participant_roles: [],
};

beforeAll(() => {
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", {
    configurable: true,
    value: function (this: HTMLDialogElement) {
      this.open = true;
    },
  });
  Object.defineProperty(HTMLDialogElement.prototype, "close", {
    configurable: true,
    value: function (this: HTMLDialogElement) {
      this.open = false;
    },
  });
});
beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
  window.localStorage.clear();
  window.history.replaceState({}, "", "/memories");
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.history.replaceState({}, "", "/");
});

describe("기억 조회와 변경 이력", () => {
  it("이전 형식의 직업과 추가 속성을 상세의 전체 필드에서 읽을 수 있다", async () => {
    const legacy = { ...item, status: "superseded", is_current: false,
      payload: { ...item.payload, fact_type: "job", value: { job: "디자이너", schedule: "야간", extra: { location: "작업실" } } },
    };
    fetchMock.mockImplementation(async (input: string) => {
      const path = new URL(input).pathname;
      if (path === "/api/ontology") return response(ontology);
      if (path === "/api/memories/entity_facts/fact-old") return response(legacy);
      if (path === "/api/memory-changes") return response(page([]));
      throw new Error(`Unexpected request ${path}`);
    });
    render(<MemoryDetail recordRef={item.record_ref} onNavigate={() => {}} />);
    const disclosure = (await screen.findByText("저장된 전체 필드")).closest("details")!;
    fireEvent.click(screen.getByText("저장된 전체 필드"));
    expect(JSON.parse(disclosure.querySelector("pre")!.textContent!)).toEqual(legacy.payload);
    expect(screen.getByText("새 기록으로 정정된 이전 기억")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "이 기억 정정" })).not.toBeInTheDocument();
  });

  it("원본 출처가 없어도 남아 있는 발췌를 표시하고 끊어진 출처 링크는 만들지 않는다", () => {
    render(
      <SourceEvidence
        item={{
          ...item,
          sources: [
            { ...item.sources[0], episode_id: "missing-source", missing: true },
          ],
        }}
      />,
    );
    expect(screen.getByText("생일은 5월이에요")).toBeInTheDocument();
    expect(
      screen.getByText(
        "원래 출처 문서를 찾을 수 없어요. 남아 있는 발췌만 표시합니다.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("발화 시점 · 알 수 없음")).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "출처와 연결된 기억 보기" }),
    ).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("전체 기억 검색·근거·상태·인물과 페이지를 서버에서 좁히며 기록 참조를 보존한다", async () => {
    fetchMock.mockImplementation(async (input: string) => {
      const url = new URL(input);
      if (url.pathname === "/api/entities")
        return response(
          page(
            [{ id: "person-a", display_name: "민지", system_role: null }],
            1,
            0,
            30,
          ),
        );
      return response(page([item], 21, Number(url.searchParams.get("offset"))));
    });
    render(<Memories onNavigate={() => {}} />);
    expect(await screen.findByRole("link", { name: "5월" })).toHaveAttribute(
      "href",
      "/memories?record=entity_facts%3Afact-old",
    );
    fireEvent.change(screen.getByLabelText("기억 검색"), {
      target: { value: "생일" },
    });
    fireEvent.change(screen.getByLabelText("구분"), {
      target: { value: "entity_facts" },
    });
    fireEvent.change(screen.getByLabelText("근거"), {
      target: { value: "reported" },
    });
    fireEvent.change(screen.getByLabelText("상태"), {
      target: { value: "history" },
    });
    fireEvent.click(screen.getByText(/인물로 좁히기/));
    await screen.findByRole("option", { name: /민지/ });
    fireEvent.change(screen.getByLabelText("인물", { selector: "select" }), {
      target: { value: "person-a" },
    });
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input]) => {
          const url = new URL(input);
          const params = url.searchParams;
          return (
            url.pathname === "/api/memories" &&
            params.get("q") === "생일" &&
            params.get("record_type") === "entity_facts" &&
            params.get("claim_basis") === "reported" &&
            params.get("status") === "history" &&
            params.get("entity_id") === "person-a"
          );
        }),
      ).toBe(true),
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "다음" })).not.toBeDisabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input]) => {
          const params = new URL(input).searchParams;
          return (
            params.get("offset") === "20" &&
            params.get("q") === "생일" &&
            params.get("entity_id") === "person-a"
          );
        }),
      ).toBe(true),
    );
    fireEvent.change(screen.getByLabelText("기억 검색"), {
      target: { value: "다른 내용" },
    });
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input]) => {
          const params = new URL(input).searchParams;
          return (
            params.get("q") === "다른 내용" && params.get("offset") === "0"
          );
        }),
      ).toBe(true),
    );
  });

  it("상세는 지정된 기록과 연결된 이력을 읽고 알 수 없는 발화 시점을 만들지 않는다", async () => {
    fetchMock.mockImplementation(async (input: string) => {
      const url = new URL(input);
      if (url.pathname === "/api/memories/entity_facts/fact-old")
        return response(item);
      if (url.pathname === "/api/memory-changes")
        return response(page([history], 1, 0, 10));
      throw new Error(`Unexpected request ${url.pathname}`);
    });
    render(<MemoryDetail recordRef={item.record_ref} onNavigate={() => {}} />);
    await screen.findByRole("heading", { name: "5월" });
    expect(screen.getByText("생일은 5월이에요")).toBeInTheDocument();
    expect(screen.getByText("발화 시점 · 알 수 없음")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "출처와 연결된 기억 보기" }),
    ).toHaveAttribute("href", "/sources/source-a");
    expect(
      await screen.findByRole("link", { name: "이후 기억" }),
    ).toHaveAttribute("href", "/memories?record=entity_facts%3Afact-new");
    expect(
      fetchMock.mock.calls.some(
        ([input]) =>
          new URL(input).searchParams.get("record_ref") === item.record_ref,
      ),
    ).toBe(true);
    expect(document.body.textContent).not.toMatch(/AI 사용|확인됨|승인/);
  });

  it("철회 후 서버 상태를 다시 읽고 변경 버튼을 숨기며 원문 출처는 유지한다", async () => {
    let retracted = false;
    fetchMock.mockImplementation(async (input: string, init: RequestInit) => {
      const url = new URL(input);
      if (url.pathname === "/api/ontology") return response(ontology);
      if (url.pathname === "/api/system/config") return response(memoryConfig);
      if (url.pathname === "/api/memories" && init.method === "POST") {
        retracted = true;
        return response(
          {
            change_id: "change-retract",
            action: "retract",
            old_record_ref: item.record_ref,
            new_record_ref: null,
            source_episode_id: "source-retract",
          },
          201,
        );
      }
      if (url.pathname === "/api/memories/entity_facts/fact-old")
        return response(
          retracted
            ? {
                ...item,
                status: "deleted",
                is_current: false,
                updated_at: "2026-10-01T04:00:00Z",
              }
            : item,
        );
      if (url.pathname === "/api/memory-changes")
        return response(page([], 0, 0, 10));
      throw new Error(`Unexpected request ${url.pathname}`);
    });
    const navigate = vi.fn();
    render(<MemoryDetail recordRef={item.record_ref} onNavigate={navigate} />);
    fireEvent.click(await screen.findByRole("button", { name: "철회" }));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "철회 기록 저장" }),
      ).not.toBeDisabled(),
    );
    fireEvent.change(screen.getByLabelText("말한 사람"), {
      target: { value: "나" },
    });
    fireEvent.change(screen.getByLabelText("근거가 되는 발언·직접 입력"), {
      target: { value: "이전 생일 정보는 잘못 들었어요" },
    });
    fireEvent.click(screen.getByRole("button", { name: "철회 기록 저장" }));
    await waitFor(() =>
      expect(screen.getByText("철회된 기억")).toBeInTheDocument(),
    );
    expect(
      screen.queryByRole("button", { name: "이 기억 정정" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "다른 인물로 옮기기" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("생일은 5월이에요")).toBeInTheDocument();
    expect(navigate).not.toHaveBeenCalled();
    const write = fetchMock.mock.calls.find(
      ([, init]) => init?.method === "POST",
    )!;
    expect(JSON.parse(write[1].body)).toMatchObject({
      action: "retract",
      old_record_ref: item.record_ref,
      expected_updated_at: item.updated_at,
    });
    expect(JSON.parse(write[1].body)).not.toHaveProperty("record");
    expect(
      fetchMock.mock.calls.filter(
        ([input]) =>
          new URL(input).pathname === "/api/memories/entity_facts/fact-old",
      ),
    ).toHaveLength(2);
  });

  it("기본 인물 이관 이력은 기억 API를 호출하지 않고 일반 정정의 전후 기억과 출처는 보존한다", async () => {
    window.history.replaceState({}, "", "/changes");
    fetchMock.mockImplementation(async (input: string) => {
      const path = new URL(input).pathname;
      if (path === "/api/memory-changes")
        return response(page([identityMigration, history]));
      if (path === "/api/memory-changes/change-migrate")
        return response(identityMigration);
      if (path === "/api/memory-changes/change-a") return response(history);
      if (path === "/api/memories/entity_facts/fact-old")
        return response({ ...item, status: "superseded", is_current: false });
      if (path === "/api/memories/entity_facts/fact-new")
        return response({
          ...item,
          id: "fact-new",
          record_ref: "entity_facts:fact-new",
          content: "--06",
          payload: {
            ...item.payload,
            content: "--06",
            value: { year: null, month: 6, day: null, precision: "month" },
          },
        });
      if (path === "/api/episodes/source-change")
        return response({
          id: "source-change",
          actor: "민지",
          body_excerpt: "5월이 아니라 6월이에요",
          occurred_at: null,
        });
      if (path === "/api/entities") return response(page([]));
      throw new Error(`Unexpected request ${path}`);
    });
    render(<Changes />);
    expect(await screen.findByText("인물 이관·변경 기록이에요. 아래 링크는 현재 인물 정보로 연결됩니다.")).toBeInTheDocument();
    const currentPeople = screen.getAllByRole("link", { name: "현재 인물 보기" });
    expect(currentPeople).toHaveLength(2);
    currentPeople.forEach((link) => expect(link).toHaveAttribute("href", "/people/person-a"));
    expect(screen.getAllByText("당시 인물 상태는 보관되어 있지 않아 전후 값을 비교할 수 없어요.")).toHaveLength(2);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input]) => new URL(input).pathname.startsWith("/api/memories/"))).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: /생일 월 정정/ }));
    const before = await screen.findByRole("link", { name: "5월" });
    const after = await screen.findByRole("link", { name: "6월" });
    expect(before).toHaveAttribute(
      "href",
      "/memories?record=entity_facts%3Afact-old",
    );
    expect(after).toHaveAttribute(
      "href",
      "/memories?record=entity_facts%3Afact-new",
    );
    expect(
      await screen.findByText("5월이 아니라 6월이에요"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "출처 자세히 보기" }),
    ).toHaveAttribute("href", "/sources/source-change");
    expect(screen.getByText("정정 전 기록")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /기존 인물 기록 이관/ }));
    await screen.findByText("인물 이관·변경 기록이에요. 아래 링크는 현재 인물 정보로 연결됩니다.");
    expect(screen.queryByRole("link", { name: "5월" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "6월" })).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input]) => new URL(input).pathname === "/api/memories/entities/person-a")).toBe(false);
    expect(fetchMock.mock.calls.some(([input]) => new URL(input).pathname === "/api/entities/person-a")).toBe(false);
  });

  it("인물 참조로 좁힌 이력은 현재 인물로 연결하고 동일한 참조 필터를 유지한다", async () => {
    window.history.replaceState({}, "", "/changes?record=entities%3Aperson-a");
    fetchMock.mockImplementation(async (input: string) => {
      const url = new URL(input);
      if (url.pathname === "/api/memory-changes") {
        expect(url.searchParams.get("record_ref")).toBe("entities:person-a");
        return response(page([identityMigration]));
      }
      if (url.pathname === "/api/memory-changes/change-migrate")
        return response(identityMigration);
      throw new Error(`Unexpected request ${url.pathname}`);
    });
    render(<Changes />);
    expect(screen.getByRole("link", { name: "선택한 참조의 현재 인물 보기" })).toHaveAttribute("href", "/people/person-a");
    await screen.findByText("인물 이관·변경 기록이에요. 아래 링크는 현재 인물 정보로 연결됩니다.");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "선택한 기억 보기" })).not.toBeInTheDocument();
    expect(fetchMock.mock.calls).toHaveLength(2);
  });

  it.each(["entity_aliases:alias-a", "legacy_records:legacy-a"])(
    "%s 이력은 당시 값의 한계와 접힌 기술 참조만 보존한다",
    async (reference) => {
      window.history.replaceState({}, "", `/changes?record=${encodeURIComponent(reference)}`);
      const unknownMigration = { ...identityMigration, old_record_ref: reference, new_record_ref: reference };
      fetchMock.mockImplementation(async (input: string) => {
        const path = new URL(input).pathname;
        if (path === "/api/memory-changes") return response(page([unknownMigration]));
        if (path === "/api/memory-changes/change-migrate") return response(unknownMigration);
        throw new Error(`Unexpected request ${path}`);
      });
      render(<Changes />);
      expect(await screen.findAllByText("당시 값은 보관되어 있지 않아 전후 값을 비교할 수 없어요.")).toHaveLength(2);
      const references = screen.getAllByText(reference);
      expect(references).toHaveLength(3);
      references.forEach((element) => expect(element.closest("details")).not.toHaveAttribute("open"));
      expect(screen.getAllByRole("link")).toHaveLength(1);
      expect(screen.getByRole("link", { name: "전체 이력 보기" })).toHaveAttribute("href", "/changes");
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      expect(fetchMock.mock.calls).toHaveLength(2);
    },
  );

  it("변경 목록도 기억·인물·별칭·기타 참조를 구분해 끊어진 기억 링크를 만들지 않는다", async () => {
    fetchMock.mockImplementation(async (input: string) => {
      expect(new URL(input).pathname).toBe("/api/memory-changes");
      return response(page([
        identityMigration,
        history,
        { ...identityMigration, id: "change-alias", old_record_ref: "entity_aliases:alias-a", new_record_ref: "legacy_records:legacy-a" },
      ], 3, 0, 10));
    });
    render(<ChangeRows entityId="person-a" />);
    expect(await screen.findByRole("link", { name: "이전 참조의 현재 인물 보기" })).toHaveAttribute("href", "/people/person-a");
    expect(screen.getByRole("link", { name: "이후 참조의 현재 인물 보기" })).toHaveAttribute("href", "/people/person-a");
    expect(screen.getByRole("link", { name: "이전 기억" })).toHaveAttribute("href", "/memories?record=entity_facts%3Afact-old");
    expect(screen.getByRole("link", { name: "이후 기억" })).toHaveAttribute("href", "/memories?record=entity_facts%3Afact-new");
    for (const reference of ["entity_aliases:alias-a", "legacy_records:legacy-a"]) {
      expect(screen.getByText(reference).closest("details")).not.toHaveAttribute("open");
    }
    const memoryLinks = screen.getAllByRole("link").filter((link) => link.getAttribute("href")?.startsWith("/memories?"));
    expect(memoryLinks).toHaveLength(2);
    expect(fetchMock.mock.calls).toHaveLength(1);
  });

  it("출처 화면은 특정 출처에 연결된 모든 상태의 기억을 서버에서 조회한다", async () => {
    fetchMock.mockImplementation(async (input: string) => {
      const url = new URL(input);
      if (url.pathname === "/api/episodes/source-a")
        return response({
          id: "source-a",
          source_type: "manual_entry",
          actor: "민지",
          body_excerpt: "생일은 5월이에요",
          occurred_at: null,
          ingested_at: "2026-10-01T00:00:00Z",
          source_ref: "대화 발췌 위치",
        });
      if (url.pathname === "/api/memories")
        return response(
          page([{ ...item, status: "superseded", is_current: false }]),
        );
      throw new Error(`Unexpected request ${url.pathname}`);
    });
    render(<SourcePage id="source-a" />);
    await screen.findByText("생일은 5월이에요");
    expect(await screen.findByRole("link", { name: "5월" })).toHaveAttribute(
      "href",
      "/memories?record=entity_facts%3Afact-old",
    );
    expect(screen.getByText("발화 시점").nextElementSibling).toHaveTextContent(
      "알 수 없음",
    );
    const url = new URL(
      fetchMock.mock.calls.find(
        ([input]) => new URL(input).pathname === "/api/memories",
      )![0],
    );
    expect(url.searchParams.get("source_episode_id")).toBe("source-a");
    expect(url.searchParams.get("status")).toBe("all");
    expect(
      fetchMock.mock.calls.every(
        ([, init]) => !init?.method || init.method === "GET",
      ),
    ).toBe(true);
  });

  it("인물 이름을 저장해도 같은 창의 미저장 별칭 초안을 잃지 않는다", async () => {
    let name = "민지";
    fetchMock.mockImplementation(async (input: string, init: RequestInit) => {
      const path = new URL(input).pathname;
      if (path === "/api/entities/person-a") {
        if (init.method === "PATCH")
          name = JSON.parse(String(init.body)).display_name;
        return response({
          id: "person-a",
          display_name: name,
          status: "active",
          system_role: null,
          properties: {},
          last_referenced_at: null,
        });
      }
      if (path === "/api/entities/person-a/aliases") return response(page([]));
      if (path === "/api/memories") return response(page([]));
      throw new Error(`Unexpected request ${path}`);
    });
    render(<Person id="person-a" onNavigate={() => {}} />);
    fireEvent.click(
      await screen.findByRole("button", { name: "이름·별칭 편집" }),
    );
    fireEvent.change(screen.getByLabelText("새 별칭"), {
      target: { value: "아직 저장하지 않은 별칭" },
    });
    fireEvent.change(screen.getByLabelText("이름"), {
      target: { value: "김민지" },
    });
    fireEvent.click(screen.getByRole("button", { name: "이름 저장" }));
    await screen.findByText("저장했어요.");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByLabelText("새 별칭")).toHaveValue(
      "아직 저장하지 않은 별칭",
    );
    expect(screen.getByRole("button", { name: "이름 저장" })).toBeDisabled();
    expect(
      fetchMock.mock.calls.filter(([, init]) => init?.method === "PATCH"),
    ).toHaveLength(1);
    expect(
      fetchMock.mock.calls.some(([, init]) => init?.method === "POST"),
    ).toBe(false);
  });
});
