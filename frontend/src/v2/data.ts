import { useEffect, useState } from "react";
import { ApiError, request } from "../api/client";

export { request as api };
export type Page<T> = {
  items: T[];
  total: number;
  limit: number;
  offset: number;
};
export type Basis = "reported" | "inferred" | "unknown";
export type RecordType = "entity_facts" | "entity_edges" | "observations";
export type Person = {
  id: string;
  display_name: string;
  canonical_name: string | null;
  status: string;
  system_role: string | null;
  is_system: boolean;
  created_at: string;
  updated_at: string;
  last_referenced_at: string | null;
  properties: Record<string, unknown>;
};
export type Fact = {
  id: string;
  entity_id: string;
  fact_type: string;
  content: string;
  value: Record<string, unknown> | null;
  claim_basis: Basis;
  confidence: number;
  status: string;
  valid_from: string | null;
  valid_to: string | null;
  created_at: string;
  updated_at: string;
};
export type PersonSummary = Person & {
  aliases: string[];
  relations: {
    relation_type: string;
    directed: boolean;
    from_entity_id: string;
    to_entity_id: string;
  }[];
  profile_facts: Fact[];
  memory_count: number;
};
export type Participant = {
  entity_id: string;
  role: string;
  confidence?: number | null;
};
export type MemoryPayload = {
  claim_basis: Basis;
  confidence: number;
  valid_from: string | null;
  valid_to: string | null;
  entity_id?: string;
  fact_type?: string;
  content?: string;
  value?: Record<string, unknown> | null;
  from_entity_id?: string;
  to_entity_id?: string;
  relation_type?: string;
  directed?: boolean;
  claim_text?: string;
  properties?: Record<string, unknown>;
  subject_entity_id?: string;
  observation_type?: string;
  occurred_at?: string | null;
  related_entities?: Participant[];
};
export type Source = {
  episode_id: string | null;
  source_type: string | null;
  source_ref: string | null;
  actor: string | null;
  excerpt: string | null;
  occurred_at: string | null;
  missing?: boolean;
};
export type MemoryItem = {
  record_ref: string;
  record_type: RecordType;
  id: string;
  content: string;
  claim_basis: Basis;
  confidence: number;
  status: string;
  is_current: boolean;
  created_at: string;
  updated_at: string;
  valid_from: string | null;
  valid_to: string | null;
  payload: MemoryPayload;
  entities: { id: string; display_name: string; role: string }[];
  sources: Source[];
};
export type MemoryChange = {
  id: string;
  request_id: string;
  change_kind: string;
  old_record_ref: string | null;
  new_record_ref: string | null;
  source_episode_id: string | null;
  actor: string;
  reason: string | null;
  created_at: string;
};
export type Episode = {
  id: string;
  source_type: string;
  source_ref: string | null;
  source_description: string | null;
  body_excerpt: string;
  body_hash: string;
  actor: string;
  occurred_at: string | null;
  ingested_at: string;
  created_at: string;
};
export type Ontology = {
  fact_types: {
    value: string;
    label: string;
    support_level: string;
    is_active: boolean;
  }[];
  claim_bases: { value: Basis; label: string }[];
  participant_roles: { value: string; label: string; support_level: string }[];
  edge_types: {
    relation_type: string;
    directed_default: boolean;
    inverse_relation_type: string | null;
    active: boolean;
    description: string | null;
  }[];
  observation_types: {
    observation_type: string;
    active: boolean;
    description: string | null;
  }[];
};
export type Receipt = {
  change_id: string;
  action: string;
  old_record_ref: string | null;
  new_record_ref: string | null;
  source_episode_id: string;
};
export type MemoryWrite = {
  request_id: string;
  action: "create" | "correct" | "retract" | "reattribute";
  old_record_ref?: string;
  expected_updated_at?: string;
  record?: { record_type: RecordType; payload: MemoryPayload };
  source: {
    source_type: "manual_entry";
    actor: string;
    excerpt: string;
    occurred_at: string | null;
    source_ref?: string;
  };
  reason?: string;
  created_by: "user";
};

export function query(
  values: Record<string, string | number | undefined | null>,
) {
  return new URLSearchParams(
    Object.entries(values)
      .filter(([, v]) => v !== undefined && v !== null && v !== "")
      .map(([k, v]) => [k, String(v)]),
  ).toString();
}
export function memoryPath(ref: string) {
  const [kind, id] = ref.split(":");
  return `/api/memories/${encodeURIComponent(kind)}/${encodeURIComponent(id || "")}`;
}
export function memoryUrl(ref: string) {
  return `/memories?record=${encodeURIComponent(ref)}`;
}
// LAN HTTP is supported; randomUUID is unavailable outside secure contexts.
export function newRequestId() {
  return `web-${Array.from(crypto.getRandomValues(new Uint8Array(16)), (byte) => byte.toString(16).padStart(2, "0")).join("")}`;
}
export function useResource<T>(path: string | null, version = 0) {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<unknown>();
  const [loading, setLoading] = useState(Boolean(path));
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    if (!path) {
      setData(undefined);
      setError(undefined);
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError(undefined);
    setData(undefined);
    request<T>(path, { signal: controller.signal })
      .then((value) => {
        if (!controller.signal.aborted) setData(value);
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(err);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [path, version, revision]);
  return { data, error, loading, reload: () => setRevision((v) => v + 1) };
}
export function errorText(error: unknown) {
  if (error instanceof ApiError) {
    const hints: Record<number, string> = {
      401: "연결 토큰을 확인해 주세요. 설정에서 다시 연결할 수 있어요.",
      403: "이 작업을 수행할 권한이 없어요.",
      404: "기록을 찾을 수 없어요. 삭제되거나 다른 인물로 합쳐졌을 수 있어요.",
      409: "다른 변경이 먼저 저장됐거나 같은 요청이 처리 중이에요. 초안은 유지됩니다. 현재 기록과 변경 이력을 확인해 주세요.",
      422: "입력한 내용과 날짜·출처를 확인해 주세요.",
    };
    return `${hints[error.status] || "요청을 처리하지 못했어요."} ${error.message}`;
  }
  return error instanceof Error
    ? `연결을 확인해 주세요. ${error.message}`
    : "요청을 처리하지 못했어요.";
}
export const basisLabels: Record<Basis, string> = {
  reported: "전해 들은 내용",
  inferred: "추론한 내용",
  unknown: "근거 구분 없음",
};
export const kindLabels: Record<RecordType, string> = {
  entity_facts: "프로필",
  entity_edges: "관계",
  observations: "맥락",
};
export const actionLabels: Record<string, string> = {
  create: "새 기억",
  correct: "정정",
  retract: "철회",
  reattribute: "인물 변경",
  migration: "이전 기록 변환",
  migrate: "이전 기록 변환",
};
export const sourceLabels: Record<string, string> = {
  manual_entry: "직접 입력",
  agent_conversation: "대화",
  correction: "정정 발언",
  import: "가져온 자료",
  imported_material: "가져온 자료",
};
export function actorLabel(value: string) {
  return (
    (
      {
        user: "사용자",
        ai_agent: "에이전트",
        system: "시스템",
        connector: "연결 서비스",
        import: "가져오기",
      } as Record<string, string>
    )[value] || value
  );
}
export const typeLabels: Record<string, string> = {
  legal_name: "본명",
  birth_date: "생년월일",
  birthday: "생일",
  phone: "전화번호",
  email: "이메일",
  address: "주소",
  organization: "소속",
  role: "역할",
  job: "직업",
  external_handle: "외부 계정",
  location_hint: "주요 지역",
  memo: "이전 메모",
  stable_fact: "지속적인 맥락",
  preference: "취향·선호",
  communication_preference: "소통 방식",
  relationship_pattern: "관계 패턴",
  recent_context: "최근 맥락",
  recent_interaction: "최근 상호작용",
  user_feeling: "감정",
  follow_up_context: "후속 맥락",
  care_point: "챙길 점",
  caution: "주의할 맥락",
  feeling: "감정",
  follow_up: "후속 맥락",
  subject: "주된 인물",
  about: "내용의 대상",
  speaker: "말한 사람",
  experiencer: "느낀 사람",
  related: "관련 인물",
  mentioned: "언급된 인물",
  target: "대상",
  from: "관계 시작",
  to: "관계 대상",
  knows: "아는 사이",
  friend: "친구",
  family: "가족",
  acquaintance: "지인",
  coworker: "동료",
  former_coworker: "이전 동료",
  client_contact: "고객 측 연락처",
  vendor_contact: "거래처 연락처",
  reports_to: "보고하는 관계",
  manager_of: "관리하는 관계",
  introduced_by: "소개받음",
  referred_by: "추천받음",
  collaborated_with: "협업 관계",
  dating_interest: "호감",
  dating: "교제 중",
  former_dating: "이전 교제",
  romantic_partner: "연인",
  former_partner: "이전 연인",
  introduced_for_dating: "소개팅",
  matched_on_app: "앱에서 만남",
};
export function label(value: string) {
  return typeLabels[value] || value;
}
// SQLite compatibility responses omit the zone; backend storage timestamps are UTC.
export function apiDate(value: string) {
  return new Date(
    /^\d{4}-\d\d-\d\dT/.test(value) && !/(Z|[+-]\d\d:\d\d)$/i.test(value)
      ? `${value}Z`
      : value,
  );
}
export function dateTime(value: string | null | undefined) {
  if (!value) return "알 수 없음";
  const d = apiDate(value);
  return Number.isNaN(d.getTime())
    ? value
    : d.toLocaleString("ko-KR", {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
}
export function factText(fact: Pick<Fact, "fact_type" | "value" | "content">) {
  if (["birth_date", "birthday"].includes(fact.fact_type) && fact.value) {
    const v = fact.value;
    return (
      `${v.year ? `${v.year}년 ` : ""}${v.month ? `${v.month}월 ` : ""}${v.day ? `${v.day}일` : ""}`.trim() ||
      fact.content
    );
  }
  return fact.content;
}
export function memoryText(item: MemoryItem) {
  return item.record_type === "entity_facts"
    ? factText({
        fact_type: item.payload.fact_type || "",
        value: item.payload.value || null,
        content: item.content,
      })
    : item.content;
}
