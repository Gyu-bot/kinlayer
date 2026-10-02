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

import { MemoryEditor } from "./MemoryEditor";
import { relationshipProfileFixture } from "./relationshipProfileFixtures";
import type { MemoryItem, MemoryWrite } from "./data";

const fetchMock = vi.fn();
const memoryConfig = {
  memory_write: {
    endpoint: "/api/memories",
    contract_version: "2",
    review_required: false,
  },
};
const response = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
const ontology = {
  relationship_profile: relationshipProfileFixture,
  fact_types: [
    { value: "organization", is_active: true, support_level: "supported" },
    { value: "job", is_active: true, support_level: "supported" },
    { value: "birthday", is_active: true, support_level: "supported" },
    { value: "birth_date", is_active: true, support_level: "supported" },
  ],
  edge_types: [
    { relation_type: "friend", label: "친구", active: true, directed_default: false, write_supported: true },
    { relation_type: "reports_to", label: "부하", inverse_label: "상사", active: true, directed_default: true, write_supported: true },
    { relation_type: "situationship", label: "썸", active: true, directed_default: false, write_supported: true, description: "서로를 알아가는 관계" },
    { relation_type: "parent_of", label: "부모", inverse_label: "자녀", active: true, directed_default: true, write_supported: true },
    { relation_type: "dating_interest", label: "호감 (이전 유형)", active: true, directed_default: false, write_supported: false },
  ],
  observation_types: [
    { observation_type: "relationship_assessment", active: true },
    { observation_type: "recent_interaction", active: true },
    { observation_type: "feeling", active: true },
  ],
  claim_bases: [
    { value: "reported" },
    { value: "inferred" },
    { value: "unknown" },
  ],
  participant_roles: [
    { value: "speaker" },
    { value: "experiencer" },
    { value: "about" },
  ],
};
const people = {
  items: [
    { id: "person-a", display_name: "민지" },
    { id: "person-b", display_name: "서준" },
    { id: "person-c", display_name: "지호" },
  ],
  offset: 0,
  limit: 30,
  total: 3,
};
const item: MemoryItem = {
  id: "memory-a",
  record_ref: "observations:memory-a",
  record_type: "observations",
  content: "함께 이야기한 내용",
  claim_basis: "inferred",
  confidence: 0.7,
  status: "active",
  is_current: true,
  created_at: "2026-09-01T00:00:00.000Z",
  updated_at: "2026-10-01T00:00:00.123456Z",
  valid_from: "2026-09-01T01:02:03.456Z",
  valid_to: "2026-10-31T03:04:05.678Z",
  payload: {
    subject_entity_id: "person-a",
    observation_type: "feeling",
    content: "함께 이야기한 내용",
    claim_basis: "inferred",
    confidence: 0.7,
    valid_from: "2026-09-01T01:02:03.456Z",
    valid_to: "2026-10-31T03:04:05.678Z",
    occurred_at: "2026-09-30T10:20:30.123Z",
    related_entities: [
      { entity_id: "person-b", role: "speaker", confidence: 0.8 },
      { entity_id: "person-a", role: "experiencer", confidence: 0.6 },
    ],
  },
  entities: [
    { id: "person-a", display_name: "민지", role: "subject" },
    { id: "person-b", display_name: "서준", role: "speaker" },
  ],
  sources: [
    {
      episode_id: "source-old",
      source_type: "agent_conversation",
      source_ref: "conversation:original",
      actor: "서준",
      excerpt: "원래 발언",
      occurred_at: null,
    },
  ],
};
const receipt = {
  change_id: "change-new",
  action: "correct",
  old_record_ref: item.record_ref,
  new_record_ref: "observations:memory-new",
  source_episode_id: "source-new",
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
  fetchMock.mockImplementation(async (input: string) => {
    const path = new URL(input).pathname;
    if (path === "/api/ontology") return response(ontology);
    if (path === "/api/system/config") return response(memoryConfig);
    if (path === "/api/entities") return response(people);
    if (path === "/api/memories") return response(receipt, 201);
    throw new Error(`Unexpected request: ${path}`);
  });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function writes(): MemoryWrite[] {
  return fetchMock.mock.calls
    .filter(
      ([url, init]) =>
        new URL(url).pathname === "/api/memories" && init?.method === "POST",
    )
    .map(([, init]) => JSON.parse(init.body));
}
async function ready() {
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "저장" })).not.toBeDisabled(),
  );
}
function source() {
  fireEvent.change(screen.getByLabelText("말한 사람"), {
    target: { value: "나" },
  });
  fireEvent.change(screen.getByLabelText("근거가 되는 발언·직접 입력"), {
    target: { value: "직접 확인한 정정 근거" },
  });
}

describe("기억 쓰기 계약", () => {
  it("직업 값만 입력하면 별도 기억이나 근거 문장 없이 직접 입력 출처와 함께 저장한다", async () => {
    const saved = vi.fn();
    render(<MemoryEditor initialKind="entity_facts" personId="person-a" onClose={() => {}} onSaved={saved} />);
    await ready();
    fireEvent.change(screen.getByLabelText("종류"), { target: { value: "job" } });
    expect(screen.queryByLabelText("기억 내용")).not.toBeInTheDocument();
    expect(screen.getByLabelText("근거가 되는 발언·직접 입력")).not.toBeRequired();
    fireEvent.change(screen.getByLabelText("직업 값"), { target: { value: "  디자이너  " } });
    fireEvent.click(screen.getByRole("button", { name: "저장" }));
    await waitFor(() => expect(saved).toHaveBeenCalledOnce());
    expect(writes()[0]).toMatchObject({
      source: { source_type: "manual_entry", actor: "나", excerpt: "디자이너", occurred_at: null },
      record: { record_type: "entity_facts", payload: { fact_type: "job", content: "디자이너", value: { text: "디자이너" } } },
    });
  });

  it("생일은 월과 일만으로 저장하며 자동 출처에도 없는 연도를 넣지 않는다", async () => {
    const saved = vi.fn();
    render(<MemoryEditor initialKind="entity_facts" personId="person-a" onClose={() => {}} onSaved={saved} />);
    await ready();
    fireEvent.change(screen.getByLabelText("종류"), { target: { value: "birthday" } });
    fireEvent.change(screen.getByLabelText("월"), { target: { value: "4" } });
    fireEvent.change(screen.getByLabelText("일"), { target: { value: "12" } });
    fireEvent.click(screen.getByRole("button", { name: "저장" }));
    await waitFor(() => expect(saved).toHaveBeenCalledOnce());
    expect(writes()[0].record?.payload).toMatchObject({ content: "--04-12", value: { year: null, month: 4, day: 12, precision: "day" } });
    expect(writes()[0].source.excerpt).toBe("4월 12일");
  });

  it("관계는 두 인물과 유형만으로 저장하며 방향과 직접 입력한 속성을 출처에 남긴다", async () => {
    const saved = vi.fn();
    render(<MemoryEditor initialKind="entity_edges" personId="person-a" onClose={() => {}} onSaved={saved} />);
    await ready();
    await screen.findAllByRole("option", { name: /서준/ });
    fireEvent.change(screen.getByLabelText("종류"), { target: { value: "parent_of" } });
    fireEvent.change(screen.getByLabelText("관계 대상 인물"), { target: { value: "person-b" } });
    fireEvent.change(screen.getByLabelText("관계 배경 (학교·회사·모임)"), { target: { value: "가족" } });
    expect(screen.getByLabelText("관계 설명 (선택)")).not.toBeRequired();
    fireEvent.click(screen.getByRole("button", { name: "저장" }));
    await waitFor(() => expect(saved).toHaveBeenCalledOnce());
    expect(writes()[0].record?.payload).toMatchObject({ from_entity_id: "person-a", to_entity_id: "person-b", relation_type: "parent_of", directed: true, claim_text: "시작 인물은 대상 인물의 부모", properties: { context: "가족" } });
    expect(writes()[0].source.excerpt).toBe("시작 인물은 대상 인물의 부모\n관계 배경 (학교·회사·모임): 가족");
  });

  it("직접 프로필 입력에서도 사용자가 보완한 출처를 자동 문장으로 덮어쓰지 않는다", async () => {
    const saved = vi.fn();
    render(<MemoryEditor initialKind="entity_facts" personId="person-a" onClose={() => {}} onSaved={saved} />);
    await ready();
    fireEvent.change(screen.getByLabelText("소속 값"), { target: { value: "모노랩" } });
    source();
    fireEvent.click(screen.getByRole("button", { name: "저장" }));
    await waitFor(() => expect(saved).toHaveBeenCalledOnce());
    expect(writes()[0].source.excerpt).toBe("직접 확인한 정정 근거");
  });

  it("직접 등록한 관계의 유형을 정정하면 자동 설명과 출처도 새 방향에 맞춘다", async () => {
    const edge: MemoryItem = { ...item, record_type: "entity_edges", record_ref: "entity_edges:direct",
      content: "두 사람의 관계: 친구", payload: {
        claim_basis: "reported", confidence: 1, valid_from: null, valid_to: null,
        from_entity_id: "person-a", to_entity_id: "person-b", relation_type: "friend", directed: false,
        claim_text: "두 사람의 관계: 친구", properties: {},
      },
    };
    const saved = vi.fn();
    render(<MemoryEditor item={edge} action="correct" onClose={() => {}} onSaved={saved} />);
    await ready();
    fireEvent.change(screen.getByLabelText("종류"), { target: { value: "parent_of" } });
    fireEvent.click(screen.getByRole("button", { name: "저장" }));
    await waitFor(() => expect(saved).toHaveBeenCalledOnce());
    expect(writes()[0]).toMatchObject({ old_record_ref: edge.record_ref, expected_updated_at: edge.updated_at,
      record: { payload: { relation_type: "parent_of", directed: true, claim_text: "시작 인물은 대상 인물의 부모" } },
      source: { actor: "나", excerpt: "시작 인물은 대상 인물의 부모" },
    });
  });

  it("관계 정정에서 배경과 경위를 수정하고 세부 관계를 비우며 명시적 유형 변환을 보낸다", async () => {
    const edge: MemoryItem = { ...item, record_type: "entity_edges", record_ref: "entity_edges:editable", payload: {
      claim_basis: "reported", confidence: 0.7, valid_from: item.valid_from, valid_to: item.valid_to,
      from_entity_id: "person-a", to_entity_id: "person-b", relation_type: "friend", directed: false,
      claim_text: item.content, properties: { context: "이전 회사", relationship_detail: "이전 상세", origin: "이전 경위" },
    } };
    const saved = vi.fn();
    render(<MemoryEditor item={edge} action="correct" onClose={() => {}} onSaved={saved} />);
    await ready();
    expect(screen.getByLabelText("관계 배경 (학교·회사·모임)")).toHaveValue("이전 회사");
    expect(screen.getByLabelText("세부 관계 (예: 사촌·이모)")).toHaveValue("이전 상세");
    expect(screen.getByLabelText("알게 된 경위")).toHaveValue("이전 경위");
    fireEvent.change(screen.getByLabelText("관계 배경 (학교·회사·모임)"), { target: { value: "새 배경" } });
    fireEvent.change(screen.getByLabelText("세부 관계 (예: 사촌·이모)"), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText("알게 된 경위"), { target: { value: "정정한 경위" } });
    fireEvent.change(screen.getByLabelText("종류"), { target: { value: "parent_of" } });
    source();
    fireEvent.click(screen.getByRole("button", { name: "저장" }));
    await waitFor(() => expect(saved).toHaveBeenCalledOnce());
    expect(writes()[0].record?.payload).toMatchObject({ relation_type: "parent_of", directed: true,
      properties: { context: "새 배경", origin: "정정한 경위" } });
    expect(writes()[0].record?.payload.properties).not.toHaveProperty("relationship_detail");
  });


  it("관계 평가의 같은 값에서 문장만 정정하면 원래 시점 정밀도를 보존한다", async () => {
    const when = "2020-01-01T00:00:00.123456Z";
    const assessment: MemoryItem = { ...item, claim_basis: "reported", valid_from: when, valid_to: null, payload: {
      claim_basis: "reported", confidence: 0.7, valid_from: when, valid_to: null,
      subject_entity_id: "person-a", observation_type: "relationship_assessment", content: item.content,
      perspective_entity_id: "self", relationship_axis: "closeness", relationship_value: "comfortable",
      occurred_at: when, related_entities: [],
    } };
    const saved = vi.fn();
    render(<MemoryEditor item={assessment} action="correct" onClose={() => {}} onSaved={saved} />);
    await ready();
    fireEvent.change(screen.getByLabelText("기억 내용"), { target: { value: "시점과 평가값은 그대로" } });
    source();
    fireEvent.click(screen.getByRole("button", { name: "저장" }));
    await waitFor(() => expect(saved).toHaveBeenCalledOnce());
    expect(writes()[0].record?.payload).toEqual({ ...assessment.payload, content: "시점과 평가값은 그대로" });
  });

  it("구조화된 관계 평가를 일반 정정 화면에서 수정해도 관점과 축을 보존한다", async () => {
    const assessment: MemoryItem = { ...item, claim_basis: "reported", payload: {
      claim_basis: "reported", confidence: 0.7, valid_from: "2020-01-01T00:00:00.123456Z", valid_to: null,
      subject_entity_id: "person-a", observation_type: "relationship_assessment", content: item.content,
      perspective_entity_id: "self", relationship_axis: "closeness", relationship_value: "comfortable",
      occurred_at: "2020-01-01T00:00:00.123456Z", related_entities: [],
    }, valid_from: null, valid_to: null };
    const saved = vi.fn();
    render(<MemoryEditor item={assessment} action="correct" onClose={() => {}} onSaved={saved} />);
    await ready();
    expect(screen.getByLabelText("기억 구분")).toBeDisabled();
    expect(screen.getByLabelText("종류")).toBeDisabled();
    expect(screen.getByLabelText("관계 속성")).toBeDisabled();
    expect(screen.getByLabelText("근거 구분")).toBeDisabled();
    expect(screen.queryByLabelText("유효 종료 시점")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("관계 속성값"), { target: { value: "close" } });
    source();
    fireEvent.click(screen.getByRole("button", { name: "저장" }));
    await waitFor(() => expect(saved).toHaveBeenCalledOnce());
    expect(writes()[0].record?.payload).toEqual({ ...assessment.payload, relationship_value: "close", content: "친밀도: 친한", valid_from: null, occurred_at: null });
    expect(writes()[0].old_record_ref).toBe(assessment.record_ref);
    expect(writes()[0].expected_updated_at).toBe(assessment.updated_at);
  });

  it("새 관계는 서버의 쓰기 가능 유형과 역할을 사용하고 썸은 양방향으로 저장한다", async () => {
    const saved = vi.fn();
    render(<MemoryEditor personId="person-a" onClose={() => {}} onSaved={saved} />);
    await ready();
    fireEvent.change(screen.getByLabelText("기억 구분"), { target: { value: "entity_edges" } });
    expect(screen.queryByRole("option", { name: /호감/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("종류"), { target: { value: "parent_of" } });
    expect(screen.getByText(/시작 인물은 대상 인물의 부모 · 대상 인물은 시작 인물의 자녀/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("종류"), { target: { value: "situationship" } });
    expect(screen.getByText("서로를 알아가는 관계")).toBeInTheDocument();
    await screen.findAllByRole("option", { name: /서준/ });
    fireEvent.change(screen.getByLabelText("관계 대상 인물"), { target: { value: "person-b" } });
    fireEvent.change(screen.getByLabelText("관계 설명 (선택)"), { target: { value: "썸이라고 표현했다" } });
    fireEvent.change(screen.getByLabelText("알게 된 경위"), { target: { value: "앱에서 알게 됨" } });
    source();
    fireEvent.click(screen.getByRole("button", { name: "저장" }));
    await waitFor(() => expect(saved).toHaveBeenCalledOnce());
    expect(writes()[0].record?.payload).toMatchObject({ relation_type: "situationship", directed: false, properties: { origin: "앱에서 알게 됨" } });
  });

  it("지원 유형의 과거 방향과 임의 속성도 문장 정정만으로 변경하지 않는다", async () => {
    const payload = {
      from_entity_id: "person-a", to_entity_id: "person-b", relation_type: "friend",
      directed: true, claim_text: "이전 친구 기록", claim_basis: "reported" as const,
      confidence: 0.7, valid_from: item.valid_from, valid_to: item.valid_to,
      properties: { previous_note: "기존 속성", context: " 원문 공백 보존 " },
    };
    const edge: MemoryItem = {
      ...item, record_type: "entity_edges", record_ref: "entity_edges:historic-friend",
      content: payload.claim_text, claim_basis: "reported", payload,
    };
    const saved = vi.fn();
    render(<MemoryEditor item={edge} action="correct" onClose={() => {}} onSaved={saved} />);
    await ready();
    expect(screen.getByText(/기존 기록의 방향.*유지합니다/)).toBeInTheDocument();
    expect(screen.queryByText("두 사람 사이의 양방향 관계입니다.")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("관계 설명 (선택)"), { target: { value: "문장만 정정" } });
    source();
    fireEvent.click(screen.getByRole("button", { name: "저장" }));
    await waitFor(() => expect(saved).toHaveBeenCalledOnce());
    expect(writes()[0].record?.payload).toEqual({ ...payload, claim_text: "문장만 정정" });
  });

  it("이전 관계의 인물 변경은 저장하지 않고 명시적 유형 정정을 안내한다", async () => {
    const edge: MemoryItem = { ...item, record_type: "entity_edges", record_ref: "entity_edges:old", payload: {
      ...item.payload, relation_type: "dating_interest", from_entity_id: "person-a", to_entity_id: "person-b", directed: false, properties: {},
    } };
    render(<MemoryEditor item={edge} action="reattribute" onClose={() => {}} onSaved={vi.fn()} />);
    await ready();
    source();
    fireEvent.click(screen.getByRole("button", { name: "저장" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("먼저 기억 정정에서 현재 유형으로");
    expect(writes()).toHaveLength(0);
  });

  it("이전 호감을 썸으로 자동 변경하지 않고 기존 속성을 보존한다", async () => {
    const edge: MemoryItem = { ...item, record_type: "entity_edges", record_ref: "entity_edges:old", payload: {
      ...item.payload, relation_type: "dating_interest", from_entity_id: "person-a", to_entity_id: "person-b", directed: false, properties: { legacy_note: "한쪽의 느낌", context: "모임" },
    } };
    const saved = vi.fn();
    render(<MemoryEditor item={edge} action="correct" onClose={() => {}} onSaved={saved} />);
    await ready();
    expect(screen.getByLabelText("종류")).toHaveValue("dating_interest");
    expect(screen.getByRole("option", { name: /호감.*이전 종류/ })).toBeInTheDocument();
    expect(screen.getByLabelText("관계 배경 (학교·회사·모임)")).toBeDisabled();
    fireEvent.change(screen.getByLabelText("관계 설명 (선택)"), { target: { value: "한쪽의 호감이었다" } });
    source();
    fireEvent.click(screen.getByRole("button", { name: "저장" }));
    await waitFor(() => expect(saved).toHaveBeenCalledOnce());
    expect(writes()[0].record?.payload).toMatchObject({ relation_type: "dating_interest", directed: false, properties: { legacy_note: "한쪽의 느낌", context: "모임" } });
  });

  it("이전 서버가 저장 계약을 제공하지 않으면 저장을 막고 호환성 문제를 표시한다", async () => {
    fetchMock.mockImplementation(async (input: string) => {
      const path = new URL(input).pathname;
      if (path === "/api/system/config")
        return response({
          auth_token_configured: false,
          curation: { mode: "legacy" },
        });
      if (path === "/api/ontology") return response(ontology);
      if (path === "/api/entities") return response(people);
      throw new Error(`Unexpected request ${path}`);
    });
    const saved = vi.fn();
    render(
      <MemoryEditor
        item={item}
        action="correct"
        onClose={() => {}}
        onSaved={saved}
      />,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "현재 기억 저장 방식을 지원하지 않아요",
    );
    expect(screen.getByRole("button", { name: "저장" })).toBeDisabled();
    source();
    fireEvent.submit(screen.getByRole("dialog").querySelector("form")!);
    expect(writes()).toHaveLength(0);
    expect(saved).not.toHaveBeenCalled();
    expect(screen.getByLabelText("근거가 되는 발언·직접 입력")).toHaveValue(
      "직접 확인한 정정 근거",
    );
  });

  it("정정 시 정확한 이전 참조·갱신 시각과 관련 인물 역할·시간·출처를 보존한다", async () => {
    const saved = vi.fn();
    render(
      <MemoryEditor
        item={item}
        action="correct"
        onClose={() => {}}
        onSaved={saved}
      />,
    );
    await ready();
    expect(screen.getByLabelText("기억의 대상")).toBeDisabled();
    fireEvent.change(screen.getByLabelText("기억 내용"), {
      target: { value: "이번에 정정한 내용" },
    });
    source();
    fireEvent.change(screen.getByLabelText("출처의 발화 시점 (선택)"), {
      target: { value: "2026-10-01T14:30:20.123" },
    });
    fireEvent.change(screen.getByLabelText("변경 이유 (선택)"), {
      target: { value: "기존 해석을 정정" },
    });
    fireEvent.click(screen.getByRole("button", { name: "저장" }));
    await waitFor(() => expect(saved).toHaveBeenCalledOnce());
    expect(writes()).toHaveLength(1);
    expect(writes()[0]).toEqual({
      request_id: expect.any(String),
      action: "correct",
      created_by: "user",
      old_record_ref: "observations:memory-a",
      expected_updated_at: "2026-10-01T00:00:00.123456Z",
      record: {
        record_type: "observations",
        payload: { ...item.payload, content: "이번에 정정한 내용" },
      },
      source: {
        source_type: "manual_entry",
        actor: "나",
        excerpt: "직접 확인한 정정 근거",
        occurred_at: new Date("2026-10-01T14:30:20.123").toISOString(),
      },
      reason: "기존 해석을 정정",
    });
    expect(
      fetchMock.mock.calls.filter(
        ([, init]) => init?.method && init.method !== "GET",
      ),
    ).toHaveLength(1);
    expect(saved).toHaveBeenCalledWith(receipt);
  });

  it("409에서 초안을 유지하고 같은 요청 재시도는 같은 ID, 수정된 초안은 새 ID를 보낸다", async () => {
    let attempt = 0;
    fetchMock.mockImplementation(async (input: string) => {
      const path = new URL(input).pathname;
      if (path === "/api/ontology") return response(ontology);
      if (path === "/api/system/config") return response(memoryConfig);
      if (path === "/api/entities") return response(people);
      attempt++;
      return attempt < 3
        ? response(
            {
              error: {
                code: "stale_record_ref",
                message: "Memory changed since read.",
              },
            },
            409,
          )
        : response(receipt, 201);
    });
    const saved = vi.fn();
    render(
      <MemoryEditor
        item={item}
        action="correct"
        onClose={() => {}}
        onSaved={saved}
      />,
    );
    await ready();
    source();
    fireEvent.change(screen.getByLabelText("기억 내용"), {
      target: { value: "실패해도 남길 초안" },
    });
    fireEvent.click(screen.getByRole("button", { name: "저장" }));
    await screen.findByRole("alert");
    expect(screen.getByLabelText("기억 내용")).toHaveValue(
      "실패해도 남길 초안",
    );
    expect(screen.getByLabelText("근거가 되는 발언·직접 입력")).toHaveValue(
      "직접 확인한 정정 근거",
    );
    expect(
      screen.getByRole("link", { name: "변경 이력을 새 창에서 확인" }),
    ).toHaveAttribute("href", "/changes?record=observations%3Amemory-a");
    fireEvent.click(screen.getByRole("button", { name: "저장" }));
    await waitFor(() => expect(writes()).toHaveLength(2));
    await screen.findByRole("alert");
    expect(writes()[1]).toEqual(writes()[0]);
    fireEvent.change(screen.getByLabelText("기억 내용"), {
      target: { value: "다시 수정한 초안" },
    });
    fireEvent.click(screen.getByRole("button", { name: "저장" }));
    await waitFor(() => expect(saved).toHaveBeenCalledOnce());
    expect(writes()[2].request_id).not.toBe(writes()[0].request_id);
    expect(writes()[2].record?.payload.content).toBe("다시 수정한 초안");
    expect(writes()[2].expected_updated_at).toBe(item.updated_at);
  });

  it("LAN HTTP처럼 randomUUID가 없어도 저장하고 재시도 시 같은 요청 ID를 유지한다", async () => {
    const getRandomValues = vi.fn(crypto.getRandomValues.bind(crypto));
    vi.stubGlobal("crypto", { getRandomValues });
    expect(crypto.randomUUID).toBeUndefined();
    let attempt = 0;
    fetchMock.mockImplementation(async (input: string) => {
      const path = new URL(input).pathname;
      if (path === "/api/ontology") return response(ontology);
      if (path === "/api/system/config") return response(memoryConfig);
      if (path === "/api/entities") return response(people);
      attempt++;
      return attempt === 1
        ? response(
            { error: { code: "conflict", message: "Request is in progress." } },
            409,
          )
        : response(receipt, 201);
    });
    const saved = vi.fn();
    render(
      <MemoryEditor
        item={item}
        action="correct"
        onClose={() => {}}
        onSaved={saved}
      />,
    );
    await ready();
    source();
    fireEvent.change(screen.getByLabelText("기억 내용"), {
      target: { value: "LAN에서 정정한 내용" },
    });
    fireEvent.click(screen.getByRole("button", { name: "저장" }));
    await screen.findByRole("alert");
    expect(writes()[0].request_id).toMatch(/^web-[0-9a-f]{32}$/);
    fireEvent.click(screen.getByRole("button", { name: "저장" }));
    await waitFor(() => expect(saved).toHaveBeenCalledOnce());
    expect(writes()).toHaveLength(2);
    expect(writes()[1]).toEqual(writes()[0]);
    expect(getRandomValues).toHaveBeenCalledOnce();
    expect(getRandomValues.mock.calls[0][0]).toHaveLength(16);
  });

  it("철회는 교체 record 없이 이전 참조와 새 근거만 전송한다", async () => {
    const saved = vi.fn();
    render(
      <MemoryEditor
        item={item}
        action="retract"
        onClose={() => {}}
        onSaved={saved}
      />,
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "철회 기록 저장" }),
      ).not.toBeDisabled(),
    );
    source();
    fireEvent.click(screen.getByRole("button", { name: "철회 기록 저장" }));
    await waitFor(() => expect(saved).toHaveBeenCalledOnce());
    expect(writes()[0]).toEqual({
      request_id: expect.any(String),
      action: "retract",
      created_by: "user",
      old_record_ref: item.record_ref,
      expected_updated_at: item.updated_at,
      source: {
        source_type: "manual_entry",
        actor: "나",
        excerpt: "직접 확인한 정정 근거",
        occurred_at: null,
      },
    });
    expect(screen.queryByLabelText("기억 내용")).not.toBeInTheDocument();
  });

  it("맥락을 다른 인물로 옮길 때 대상만 바꾸며 역할·확신도·시간을 그대로 유지한다", async () => {
    const saved = vi.fn();
    render(
      <MemoryEditor
        item={item}
        action="reattribute"
        onClose={() => {}}
        onSaved={saved}
      />,
    );
    await ready();
    await screen.findByRole("option", { name: /지호/ });
    source();
    fireEvent.change(screen.getByLabelText("기억의 대상"), {
      target: { value: "person-c" },
    });
    fireEvent.click(screen.getByRole("button", { name: "저장" }));
    await waitFor(() => expect(saved).toHaveBeenCalledOnce());
    expect(writes()[0].action).toBe("reattribute");
    expect(writes()[0].record).toEqual({
      record_type: "observations",
      payload: { ...item.payload, subject_entity_id: "person-c" },
    });
    expect(writes()[0].old_record_ref).toBe(item.record_ref);
    expect(writes()[0].expected_updated_at).toBe(item.updated_at);
    expect(screen.queryByLabelText("기억 내용")).not.toBeInTheDocument();
  });

  it("관계를 옮길 때 두 끝점·방향과 속성을 보존한다", async () => {
    const edge: MemoryItem = {
      ...item,
      record_type: "entity_edges",
      record_ref: "entity_edges:edge-a",
      id: "edge-a",
      content: "민지가 서준에게 보고한다",
      payload: {
        from_entity_id: "person-a",
        to_entity_id: "person-b",
        relation_type: "reports_to",
        directed: true,
        claim_text: "민지가 서준에게 보고한다",
        properties: { team: "연구팀" },
        claim_basis: "reported",
        confidence: 0.9,
        valid_from: item.valid_from,
        valid_to: item.valid_to,
      },
    };
    const saved = vi.fn();
    render(
      <MemoryEditor
        item={edge}
        action="reattribute"
        onClose={() => {}}
        onSaved={saved}
      />,
    );
    await ready();
    source();
    fireEvent.change(screen.getByLabelText("관계 시작 인물"), {
      target: { value: "person-c" },
    });
    fireEvent.click(screen.getByRole("button", { name: "저장" }));
    await waitFor(() => expect(saved).toHaveBeenCalledOnce());
    expect(writes()[0].record).toEqual({
      record_type: "entity_edges",
      payload: { ...edge.payload, from_entity_id: "person-c" },
    });
    expect(writes()[0].old_record_ref).toBe("entity_edges:edge-a");
  });

  it("월만 알려진 생일은 연도와 일을 만들어 넣지 않는다", async () => {
    const saved = vi.fn();
    render(
      <MemoryEditor personId="person-a" onClose={() => {}} onSaved={saved} />,
    );
    await ready();
    source();
    fireEvent.change(screen.getByLabelText("기억 구분"), {
      target: { value: "entity_facts" },
    });
    fireEvent.change(screen.getByLabelText("종류"), {
      target: { value: "birthday" },
    });
    fireEvent.change(screen.getByLabelText("월"), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "저장" }));
    await waitFor(() => expect(saved).toHaveBeenCalledOnce());
    expect(writes()[0].record).toEqual({
      record_type: "entity_facts",
      payload: {
        entity_id: "person-a",
        fact_type: "birthday",
        content: "--05",
        value: { year: null, month: 5, day: null, precision: "month" },
        claim_basis: "reported",
        confidence: 1,
        valid_from: null,
        valid_to: null,
      },
    });
    expect(writes()[0]).not.toHaveProperty("old_record_ref");
    expect(writes()[0]).not.toHaveProperty("expected_updated_at");
  });

  it("내용만 정정하면 원본 사건·유효 시점의 마이크로초 정밀도를 유지한다", async () => {
    const precise: MemoryItem = {
      ...item,
      valid_from: "2026-09-01T01:02:03.456789Z",
      valid_to: "2026-10-31T03:04:05.678901Z",
      payload: {
        ...item.payload,
        valid_from: "2026-09-01T01:02:03.456789Z",
        valid_to: "2026-10-31T03:04:05.678901Z",
        occurred_at: "2026-09-30T10:20:30.123456Z",
      },
    };
    const saved = vi.fn();
    render(
      <MemoryEditor
        item={precise}
        action="correct"
        onClose={() => {}}
        onSaved={saved}
      />,
    );
    await ready();
    source();
    fireEvent.change(screen.getByLabelText("기억 내용"), {
      target: { value: "시점은 그대로 두고 내용만 정정" },
    });
    fireEvent.click(screen.getByRole("button", { name: "저장" }));
    await waitFor(() => expect(saved).toHaveBeenCalledOnce());
    expect(writes()[0].record?.payload).toMatchObject({
      valid_from: precise.valid_from,
      valid_to: precise.valid_to,
      occurred_at: precise.payload.occurred_at,
    });
  });

  it("관계 정정은 두 끝점을 유지하는 범위로 제한한다", async () => {
    const edge: MemoryItem = {
      ...item,
      record_type: "entity_edges",
      record_ref: "entity_edges:edge-a",
      id: "edge-a",
      content: "보고 관계",
      payload: {
        from_entity_id: "person-a",
        to_entity_id: "person-b",
        relation_type: "reports_to",
        directed: true,
        claim_text: "보고 관계",
        properties: {},
        claim_basis: "reported",
        confidence: 0.8,
        valid_from: null,
        valid_to: null,
      },
    };
    render(
      <MemoryEditor
        item={edge}
        action="correct"
        onClose={() => {}}
        onSaved={() => {}}
      />,
    );
    await ready();
    expect(screen.getByLabelText("기억 구분")).toBeDisabled();
    expect(screen.getByLabelText("관계 시작 인물")).toBeDisabled();
    expect(screen.getByLabelText("관계 대상 인물")).toBeDisabled();
  });
});
