import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RelationshipProfile } from "./RelationshipProfile";
import { MemoryCard } from "./common";
import { relationshipProfileFixture } from "./relationshipProfileFixtures";
import type { MemoryItem, MemoryWrite, Ontology, RelationshipProfileRead } from "./data";

const ontology: Ontology = {
  relationship_profile: relationshipProfileFixture,
  fact_types: [], edge_types: [], participant_roles: [],
  observation_types: [{ observation_type: "relationship_assessment", active: true, description: "나와의 관계" }],
  claim_bases: [{ value: "reported", label: "전해 들은 내용" }],
};
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { "Content-Type": "application/json" },
});
const fetchMock = vi.fn();
let profile: RelationshipProfileRead;
function currentRecord(axis: string, value: string): MemoryItem {
  return {
    id: axis, record_ref: `observations:${axis}`, record_type: "observations",
    content: "내가 직접 설명한 관계", claim_basis: "reported", confidence: 1,
    status: "active", is_current: true, created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-01T00:00:00.123456Z", valid_from: null, valid_to: null,
    payload: { subject_entity_id: "other", observation_type: "relationship_assessment",
      perspective_entity_id: "self", relationship_axis: axis, relationship_value: value,
      content: "내가 직접 설명한 관계", claim_basis: "reported", confidence: 1,
      valid_from: null, valid_to: null, occurred_at: null, related_entities: [] },
    entities: [{ id: "other", display_name: "예시 인물", role: "subject" }],
    sources: [{ episode_id: "source", actor: "나", source_type: "manual_entry", source_ref: null,
      excerpt: "직접 말한 내용", occurred_at: null }],
  };
}
beforeEach(() => {
  profile = { version: "relationship-profile-v1", entity_id: "other", perspective_entity_id: "self",
    axes: Object.fromEntries(Object.keys(relationshipProfileFixture.axes).map((axis) => [axis, { value: null, label: null, record: null }])) };
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  HTMLDialogElement.prototype.close = function () { this.open = false; };
  fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
    const path = new URL(url).pathname;
    if (path.endsWith("/relationship-profile")) return response(profile);
    if (path === "/api/ontology") return response(ontology);
    if (path === "/api/entities") return response({ items: [{ id: "other", display_name: "예시 인물" }], total: 1, limit: 30, offset: 0 });
    if (path === "/api/system/config") return response({ memory_write: { endpoint: "/api/memories", contract_version: "2", review_required: false } });
    if (path === "/api/memories" && init?.method === "POST") {
      const body: MemoryWrite = JSON.parse(init.body as string);
      const axis = body.record?.payload.relationship_axis || body.old_record_ref!.split(":")[1];
      const value = body.record?.payload.relationship_value;
      profile.axes[axis] = body.action === "retract" ? { value: null, label: null, record: null }
        : { value: value!, label: null, record: currentRecord(axis, value!) };
      return response({ change_id: "changed", action: body.action, old_record_ref: body.old_record_ref || null,
        new_record_ref: body.action === "retract" ? null : `observations:${axis}`, source_episode_id: "new-source" });
    }
    throw new Error(`Unexpected ${path}`);
  });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
function source() {
  fireEvent.change(screen.getByLabelText("말한 사람"), { target: { value: "나" } });
  fireEvent.change(screen.getByLabelText("근거가 되는 발언·직접 입력"), { target: { value: "내가 지금 직접 정한 관계 상태" } });
}
function writes(): MemoryWrite[] {
  return fetchMock.mock.calls.filter(([, init]) => init?.method === "POST").map(([, init]) => JSON.parse(init.body));
}

describe("나와의 관계", () => {
  it("일반 기억 카드에도 구조화된 속성과 값을 읽을 수 있게 표시한다", () => {
    const item = currentRecord("interaction_frequency", "none");
    item.entities.push({ id: "self", display_name: "나", role: "perspective" });
    render(<MemoryCard item={item} ontology={ontology} />);
    expect(screen.getByText("나와의 관계 · 교류 빈도: 없음")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "나 · 기록의 관점" })).toBeInTheDocument();
    expect(screen.queryByText(/perspective|relationship_assessment/)).not.toBeInTheDocument();
  });

  it.each(Object.keys(relationshipProfileFixture.axes))("%s의 모든 값은 서버 메타데이터에서 보여주며 다른 축을 건드리지 않고 저장한다", async (axis) => {
    const changed = vi.fn();
    render(<RelationshipProfile personId="other" ontology={ontology} onChanged={changed} />);
    const definition = relationshipProfileFixture.axes[axis];
    const panel = await screen.findByRole("region", { name: definition.label });
    expect(within(panel).getByText("미설정")).toBeInTheDocument();
    fireEvent.click(within(panel).getByRole("button", { name: `${definition.label} 설정` }));
    await screen.findByLabelText("관계 속성값");
    await waitFor(() => expect(screen.getByRole("button", { name: "저장" })).not.toBeDisabled());
    const options = within(screen.getByLabelText("관계 속성값")).getAllByRole("option");
    expect(options.map((option) => option.textContent)).toEqual(["미설정 · 값을 선택하세요", ...definition.values.map((v) => v.label)]);
    expect(screen.getByLabelText("근거 구분")).toBeDisabled();
    expect(screen.getByLabelText("기억의 대상")).toBeDisabled();
    expect(within(screen.getByLabelText("종류")).getByRole("option", { name: "나와의 관계 평가" })).toBeInTheDocument();
    const selected = definition.values.at(-1)!;
    fireEvent.change(screen.getByLabelText("관계 속성값"), { target: { value: selected.value } });
    source();
    fireEvent.click(screen.getByRole("button", { name: "저장" }));
    await waitFor(() => expect(changed).toHaveBeenCalledOnce());
    expect(writes()).toHaveLength(1);
    expect(writes()[0]).toMatchObject({ action: "create", source: { actor: "나", excerpt: "내가 지금 직접 정한 관계 상태" }, record: {
      record_type: "observations", payload: { observation_type: "relationship_assessment", subject_entity_id: "other",
        perspective_entity_id: "self", relationship_axis: axis, relationship_value: selected.value, claim_basis: "reported", related_entities: [] },
    } });
    expect(writes()[0]).not.toHaveProperty("old_record_ref");
    for (const [otherAxis, current] of Object.entries(profile.axes)) {
      if (otherAxis !== axis) expect(current.value).toBeNull();
    }
  });

  it("미설정은 철회이며 현재 참조와 원본 갱신 시각을 보내고 다른 축은 유지한다", async () => {
    const original = currentRecord("closeness", "close");
    profile.axes.closeness = { value: "close", label: null, record: original };
    profile.axes.importance = { value: "important", label: null, record: currentRecord("importance", "important") };
    const changed = vi.fn();
    render(<RelationshipProfile personId="other" ontology={ontology} onChanged={changed} />);
    const panel = await screen.findByRole("region", { name: "친밀도" });
    expect(within(panel).getByRole("link", { name: "기억과 출처 보기" })).toHaveAttribute("href", "/memories?record=observations%3Acloseness");
    expect(within(panel).getByRole("link", { name: "이 값의 변경 이력" })).toHaveAttribute("href", "/changes?record=observations%3Acloseness");
    fireEvent.click(within(panel).getByRole("button", { name: "친밀도 미설정으로 변경" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "철회 기록 저장" })).not.toBeDisabled());
    source();
    fireEvent.click(screen.getByRole("button", { name: "철회 기록 저장" }));
    await waitFor(() => expect(changed).toHaveBeenCalledOnce());
    expect(writes()[0]).toMatchObject({ action: "retract", old_record_ref: original.record_ref, expected_updated_at: original.updated_at });
    expect(writes()[0]).not.toHaveProperty("record");
    expect(profile.axes.closeness.value).toBeNull();
    expect(profile.axes.importance.value).toBe("important");
  });
});
