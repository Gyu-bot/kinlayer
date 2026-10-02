import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { PersonMerge } from "./PersonMerge";
import type { Person } from "./data";

const fetchMock = vi.fn();
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { "Content-Type": "application/json" },
});
const failure = (code: string, message: string, details = {}) => response({ error: { code, message, details } }, 409);
const person = (id: string, display_name: string, extra: Partial<Person> = {}): Person => ({
  id, display_name, canonical_name: null, status: "active", system_role: null,
  is_system: false, properties: {}, created_at: "2026-10-02T00:00:00Z",
  updated_at: "2026-10-02T00:00:00Z", last_referenced_at: null, ...extra,
});
const target = person("person-a", "김민지");
const duplicate = person("person-b", "민지 중복");
const third = person("person-c", "박서준");
const self = person("person-self", "보호된 본인", { system_role: "self", is_system: true });
const people = [target, duplicate, third, self];
type Candidate = {
  id: string; candidate_type: string; created_by: string; status: string;
  canonical_record_ref: string | null;
  payload: { source_entity_id: string; target_entity_id: string; reason: string;
    fields_to_merge: string[]; merge_plan: { web_intent_id: string } };
};
let candidate: Candidate | undefined;
let intercept: (url: URL, init: RequestInit) => Response | Promise<Response> | undefined;
let loseCreate: boolean;
let loseAccept: boolean;
let acceptFailure: Response | undefined;

beforeAll(() => {
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value: function (this: HTMLDialogElement) { this.open = true; } });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value: function (this: HTMLDialogElement) { this.open = false; } });
});
beforeEach(() => {
  candidate = undefined;
  intercept = () => undefined;
  loseCreate = false;
  loseAccept = false;
  acceptFailure = undefined;
  fetchMock.mockReset();
  window.localStorage.clear();
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockImplementation(async (input: string, init: RequestInit = {}) => {
    const url = new URL(input);
    const intercepted = intercept(url, init);
    if (intercepted) return intercepted;
    if (url.pathname === "/api/entities") return response({ items: people, total: people.length, limit: 30, offset: 0 });
    const entity = people.find((item) => url.pathname === `/api/entities/${item.id}`);
    if (entity) return response(entity);
    if (url.pathname.endsWith("/aliases")) return response({ items: [], total: 0, limit: 50, offset: 0 });
    if (url.pathname === "/api/memories") return response({ items: [], total: 0, limit: Number(url.searchParams.get("limit")), offset: 0 });
    if (url.pathname === "/api/candidates" && init.method === "POST") {
      const body = JSON.parse(String(init.body));
      candidate = { ...body, id: "candidate-merge", status: "pending", canonical_record_ref: null };
      if (loseCreate) throw new TypeError("병합 준비 응답 연결이 끊어졌어요.");
      return response(candidate, 201);
    }
    if (url.pathname === "/api/candidates") return response({ items: candidate ? [candidate] : [], total: candidate ? 1 : 0, limit: 200, offset: 0 });
    if (url.pathname === "/api/candidates/candidate-merge/accept" && candidate) {
      if (acceptFailure) return acceptFailure.clone();
      candidate = { ...candidate, status: "accepted", canonical_record_ref: `entities:${candidate.payload.target_entity_id}` };
      if (loseAccept) throw new TypeError("병합 완료 응답 연결이 끊어졌어요.");
      return response(candidate);
    }
    if (url.pathname === "/api/candidates/candidate-merge" && candidate) return response(candidate);
    throw new Error(`Unexpected request: ${init.method || "GET"} ${url.pathname}`);
  });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function writes(path?: string) {
  return fetchMock.mock.calls.filter(([url, init]) => init?.method === "POST" && (!path || new URL(url).pathname === path));
}
function show() {
  const onClose = vi.fn(), onMerged = vi.fn();
  render(<PersonMerge person={target} onClose={onClose} onMerged={onMerged} />);
  return { onClose, onMerged };
}
async function choose(id = duplicate.id) {
  const picker = screen.getByRole("combobox", { name: "합칠 인물" });
  await waitFor(() => expect(picker).toBeEnabled());
  fireEvent.change(picker, { target: { value: id } });
  await screen.findByRole("region", { name: "합쳐질 인물" });
}
function confirm() { fireEvent.click(screen.getByRole("checkbox")); }
function submit() { fireEvent.click(screen.getByRole("button", { name: "확인한 인물 병합" })); }

describe("인물 병합", () => {
  it("현재 인물·보호된 본인을 후보에서 빼고 선택·미리보기·취소에서는 쓰지 않는다", async () => {
    const { onClose, onMerged } = show();
    await choose();
    const picker = screen.getByRole("combobox", { name: "합칠 인물" });
    expect(within(picker).queryByRole("option", { name: /김민지|보호된 본인/ })).not.toBeInTheDocument();
    expect(within(picker).getByRole("option", { name: /민지 중복/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "확인한 인물 병합" })).toBeDisabled();
    fireEvent.click(screen.getAllByRole("button", { name: "닫기" }).at(-1)!);
    expect(onClose).toHaveBeenCalledOnce();
    expect(onMerged).not.toHaveBeenCalled();
    expect(writes()).toHaveLength(0);
  });

  it("동일인·방향 확인 뒤 user 병합 후보를 만들고 같은 후보를 승인한다", async () => {
    const { onMerged } = show();
    await choose();
    fireEvent.change(screen.getByLabelText("병합 이유 (선택)"), { target: { value: "이름만 다르게 등록했어요." } });
    submit();
    expect(writes()).toHaveLength(0);
    confirm();
    submit();
    await waitFor(() => expect(onMerged).toHaveBeenCalledWith(target.id));
    expect(writes()).toHaveLength(2);
    const creation = JSON.parse(String(writes("/api/candidates")[0][1].body));
    expect(creation).toMatchObject({ candidate_type: "merge", created_by: "user", target_entity_id: target.id,
      payload: { source_entity_id: duplicate.id, target_entity_id: target.id,
        fields_to_merge: ["aliases", "profile_facts", "edges", "observations"],
        merge_plan: { web_intent_id: expect.any(String) } } });
    expect(creation.payload.reason).toContain("이름만 다르게 등록했어요.");
    const approval = JSON.parse(String(writes("/api/candidates/candidate-merge/accept")[0][1].body));
    expect(approval).toEqual({ resolved_by: "user", resolution_note: creation.payload.reason });
  });

  it("병합을 확인한 상태에서도 인물 목록의 다음 페이지는 저장을 실행하지 않는다", async () => {
    intercept = (url) => {
      if (url.pathname !== "/api/entities") return undefined;
      const offset = Number(url.searchParams.get("offset") || 0);
      return response({ items: offset ? [third] : people, total: 31, limit: 30, offset });
    };
    const { onMerged } = show();
    await choose();
    confirm();
    expect(screen.getByRole("button", { name: "확인한 인물 병합" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "다음" })).toBeDisabled());
    expect(fetchMock.mock.calls.some(([url]) => new URL(url).pathname === "/api/entities" && new URL(url).searchParams.get("offset") === "30")).toBe(true);
    expect(screen.getByRole("combobox", { name: "합칠 인물" })).toHaveValue(duplicate.id);
    expect(screen.getByRole("checkbox")).toBeChecked();
    expect(writes()).toHaveLength(0);
    expect(onMerged).not.toHaveBeenCalled();
  });

  it("확인 후 다른 인물을 검색하며 Enter를 눌러도 병합 폼을 제출하지 않는다", async () => {
    const { onMerged } = show();
    await choose();
    confirm();
    const search = screen.getByRole("textbox", { name: "합칠 인물 검색" });
    fireEvent.change(search, { target: { value: "서준" } });
    await waitFor(() => expect(screen.getByRole("combobox", { name: "합칠 인물" })).toBeEnabled());
    // jsdom does not perform native implicit submission; cancellation proves
    // the browser cannot turn a search Enter into the destructive form action.
    expect(fireEvent.keyDown(search, { key: "Enter", code: "Enter" })).toBe(false);
    expect(screen.getByRole("combobox", { name: "합칠 인물" })).toHaveValue(duplicate.id);
    expect(writes()).toHaveLength(0);
    expect(onMerged).not.toHaveBeenCalled();
  });

  it("방향을 바꾸면 확인을 초기화하고 다시 확인한 source와 target만 보낸다", async () => {
    const { onMerged } = show();
    await choose();
    confirm();
    fireEvent.click(screen.getByRole("button", { name: "병합 방향 바꾸기" }));
    const sourcePanel = await screen.findByRole("region", { name: "합쳐질 인물" });
    expect(within(sourcePanel).getByRole("heading", { name: target.display_name })).toBeInTheDocument();
    expect(screen.getByRole("checkbox")).not.toBeChecked();
    expect(screen.getByRole("button", { name: "확인한 인물 병합" })).toBeDisabled();
    expect(writes()).toHaveLength(0);
    confirm();
    submit();
    await waitFor(() => expect(onMerged).toHaveBeenCalledWith(duplicate.id));
    expect(candidate?.payload).toMatchObject({ source_entity_id: target.id, target_entity_id: duplicate.id });
  });

  it("미리보기 실패 중에는 병합을 막고 다시 불러온 정보로 확인하게 한다", async () => {
    intercept = (url) => url.pathname === `/api/entities/${duplicate.id}` ? response({ error: { code: "unavailable", message: "인물 정보를 가져오지 못했어요." } }, 503) : undefined;
    show();
    const picker = screen.getByRole("combobox", { name: "합칠 인물" });
    await waitFor(() => expect(picker).toBeEnabled());
    fireEvent.change(picker, { target: { value: duplicate.id } });
    await screen.findByRole("alert");
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "확인한 인물 병합" })).toBeDisabled();
    intercept = () => undefined;
    fireEvent.click(screen.getByRole("button", { name: "정보 다시 불러오기" }));
    await screen.findByRole("region", { name: "합쳐질 인물" });
    expect(screen.getByRole("checkbox")).not.toBeChecked();
    expect(writes()).toHaveLength(0);
  });

  it("이전 선택의 늦은 응답이 현재 선택 미리보기와 병합 대상을 바꾸지 않는다", async () => {
    let resolveOld!: (value: Response) => void;
    const oldPreview = new Promise<Response>((resolve) => { resolveOld = resolve; });
    intercept = (url) => url.pathname === `/api/entities/${duplicate.id}` ? oldPreview : undefined;
    const { onMerged } = show();
    const picker = screen.getByRole("combobox", { name: "합칠 인물" });
    await waitFor(() => expect(picker).toBeEnabled());
    fireEvent.change(picker, { target: { value: duplicate.id } });
    fireEvent.change(picker, { target: { value: third.id } });
    await screen.findByRole("region", { name: "합쳐질 인물" });
    await act(async () => { resolveOld(response(duplicate)); await oldPreview; });
    expect(within(screen.getByRole("region", { name: "합쳐질 인물" })).getByRole("heading", { name: third.display_name })).toBeInTheDocument();
    confirm();
    submit();
    await waitFor(() => expect(onMerged).toHaveBeenCalledWith(target.id));
    expect(candidate?.payload.source_entity_id).toBe(third.id);
  });

  it("후보 생성 응답을 잃으면 intent가 같은 후보를 찾아 재생성 없이 승인한다", async () => {
    loseCreate = true;
    const { onMerged } = show();
    await choose();
    confirm();
    submit();
    await screen.findByRole("alert");
    expect(onMerged).not.toHaveBeenCalled();
    expect(writes()).toHaveLength(1);
    intercept = (url, init) => url.pathname === "/api/candidates" && !init.method
      ? response({ error: { code: "unauthorized", message: "조회 인증을 확인해 주세요." } }, 401) : undefined;
    fireEvent.click(screen.getByRole("button", { name: "결과 확인하고 재시도" }));
    await screen.findByText(/조회 인증을 확인해 주세요.|API 토큰/);
    expect(screen.getByRole("combobox", { name: "합칠 인물" })).toBeDisabled();
    expect(writes("/api/candidates")).toHaveLength(1);
    intercept = (url, init) => url.pathname === "/api/candidates" && !init.method && candidate
      ? response({ items: [{ ...candidate, id: "unrelated", payload: { ...candidate.payload, merge_plan: { web_intent_id: "different-intent" } } }, candidate], total: 2, limit: 200, offset: 0 }) : undefined;
    fireEvent.click(screen.getByRole("button", { name: "결과 확인하고 재시도" }));
    await waitFor(() => expect(onMerged).toHaveBeenCalledWith(target.id));
    expect(writes("/api/candidates")).toHaveLength(1);
    expect(writes("/api/candidates/candidate-merge/accept")).toHaveLength(1);
    expect(fetchMock.mock.calls.some(([url]) => new URL(url).searchParams.get("target_entity_id") === target.id)).toBe(true);
  });

  it("승인 완료 응답을 잃어도 같은 후보의 완료 상태를 읽어 성공으로 처리한다", async () => {
    loseAccept = true;
    const { onMerged } = show();
    await choose();
    confirm();
    submit();
    await waitFor(() => expect(onMerged).toHaveBeenCalledWith(target.id));
    expect(writes("/api/candidates")).toHaveLength(1);
    expect(writes("/api/candidates/candidate-merge/accept")).toHaveLength(1);
    expect(fetchMock.mock.calls.some(([url, init]) => new URL(url).pathname === "/api/candidates/candidate-merge" && !init.method)).toBe(true);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("승인 응답 유실 후 다른 대상의 완료 기록은 성공으로 오인하지 않는다", async () => {
    loseAccept = true;
    intercept = (url) => url.pathname === "/api/candidates/candidate-merge" && candidate
      ? response({ ...candidate, canonical_record_ref: `entities:${third.id}` }) : undefined;
    const { onMerged } = show();
    await choose();
    confirm();
    submit();
    await screen.findByRole("alert");
    expect(onMerged).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "결과 확인하고 재시도" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "결과 확인하고 재시도" })).toBeEnabled());
    expect(onMerged).not.toHaveBeenCalled();
    expect(writes("/api/candidates")).toHaveLength(1);
    expect(writes("/api/candidates/candidate-merge/accept")).toHaveLength(1);
  });

  it("평가 충돌은 입력과 두 기록 링크를 보존하고 같은 후보로 재시도한다", async () => {
    acceptFailure = failure("relationship_profile_merge_conflict", "Resolve assessments first.", {
      relationship_axis: "closeness", source_record_ref: "observations:source-assessment", target_record_ref: "observations:target-assessment",
    });
    const { onMerged } = show();
    await choose();
    fireEvent.change(screen.getByLabelText("병합 이유 (선택)"), { target: { value: "중복 연락처를 확인했어요." } });
    confirm();
    submit();
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText(/같은 관계 평가 항목이 겹쳐/)).toBeInTheDocument();
    expect(within(alert).getByRole("link", { name: "합쳐질 인물의 관계 평가 확인" })).toHaveAttribute("href", "/memories?record=observations%3Asource-assessment");
    expect(within(alert).getByRole("link", { name: "유지할 인물의 관계 평가 확인" })).toHaveAttribute("href", "/memories?record=observations%3Atarget-assessment");
    expect(screen.getByLabelText("병합 이유 (선택)")).toHaveValue("중복 연락처를 확인했어요.");
    expect(screen.getByRole("combobox", { name: "합칠 인물" })).toHaveValue(duplicate.id);
    expect(onMerged).not.toHaveBeenCalled();
    acceptFailure = undefined;
    fireEvent.click(screen.getByRole("button", { name: "결과 확인하고 재시도" }));
    await waitFor(() => expect(onMerged).toHaveBeenCalledWith(target.id));
    expect(writes("/api/candidates")).toHaveLength(1);
    expect(writes("/api/candidates/candidate-merge/accept")).toHaveLength(2);
  });
});
