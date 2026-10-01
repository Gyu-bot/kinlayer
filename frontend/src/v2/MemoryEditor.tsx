import { useRef, useState, type FormEvent } from "react";
import {
  api,
  basisLabels,
  errorText,
  label,
  relationLabel,
  newRequestId,
  useResource,
  type MemoryItem,
  type MemoryPayload,
  type MemoryWrite,
  type Ontology,
  type Participant,
  type Receipt,
  type RecordType,
} from "./data";
import { ErrorState, Loading, Modal, PersonPicker } from "./common";

type Action = MemoryWrite["action"];
const edgePropertyFields = [
  ["context", "관계 배경 (학교·회사·모임)"],
  ["relationship_detail", "세부 관계 (예: 사촌·이모)"],
  ["origin", "알게 된 경위"],
] as const;
function knownEdgeProperty(key: string) {
  return edgePropertyFields.some(([name]) => name === key);
}
function localTime(value: string | null | undefined) {
  if (!value) return "";
  const d = new Date(value);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, -1);
}
function iso(value: string) {
  return value ? new Date(value).toISOString() : null;
}
function editedTime(value: string, original: string | null | undefined) {
  return value === localTime(original) ? (original ?? null) : iso(value);
}
export function dateValue(year: string, month: string, day: string) {
  const value = {
    year: year ? Number(year) : null,
    month: month ? Number(month) : null,
    day: day ? Number(day) : null,
    precision: day ? "day" : month ? "month" : "year",
  };
  const content = [
    year ? year.padStart(4, "0") : "",
    month ? month.padStart(2, "0") : "",
    day ? day.padStart(2, "0") : "",
  ]
    .filter(Boolean)
    .join("-");
  return { value, content: year ? content : `--${content}` };
}

export function MemoryEditor({
  item,
  personId = "",
  action = "create",
  onClose,
  onSaved,
}: {
  item?: MemoryItem;
  personId?: string;
  action?: Action;
  onClose: () => void;
  onSaved: (receipt: Receipt) => void;
}) {
  const o = useResource<Ontology>("/api/ontology");
  const config = useResource<{
    memory_write?: {
      endpoint: string;
      contract_version: string;
      review_required: boolean;
    };
  }>("/api/system/config");
  const writable =
    config.data?.memory_write?.endpoint === "/api/memories" &&
    config.data.memory_write.contract_version === "2" &&
    config.data.memory_write.review_required === false;
  const p = item?.payload;
  const [kind, setKind] = useState<RecordType>(
    item?.record_type || "observations",
  );
  const [type, setType] = useState(
    p?.fact_type ||
      p?.relation_type ||
      p?.observation_type ||
      "recent_interaction",
  );
  const [target, setTarget] = useState(
    p?.entity_id || p?.subject_entity_id || p?.from_entity_id || personId,
  );
  const [other, setOther] = useState(p?.to_entity_id || "");
  const [edgeProperties, setEdgeProperties] = useState<Record<string, unknown>>(p?.properties || {});
  const [content, setContent] = useState(item?.content || "");
  const [basis, setBasis] = useState<MemoryPayload["claim_basis"]>(
    item?.claim_basis || "reported",
  );
  const [confidence, setConfidence] = useState(String(item?.confidence ?? 1));
  const [from, setFrom] = useState(localTime(item?.valid_from)),
    [to, setTo] = useState(localTime(item?.valid_to));
  const [occurred, setOccurred] = useState(localTime(p?.occurred_at));
  const [participants, setParticipants] = useState<Participant[]>(
    p?.related_entities || [],
  );
  const [year, setYear] = useState(String(p?.value?.year ?? "")),
    [month, setMonth] = useState(String(p?.value?.month ?? "")),
    [day, setDay] = useState(String(p?.value?.day ?? ""));
  const [actor, setActor] = useState(""),
    [excerpt, setExcerpt] = useState(""),
    [sourceTime, setSourceTime] = useState(""),
    [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false),
    [error, setError] = useState<unknown>();
  const pending = useRef<{ signature: string; id: string } | null>(null);
  const isDate =
    kind === "entity_facts" && ["birthday", "birth_date"].includes(type);
  const retract = action === "retract",
    move = action === "reattribute";
  const title = {
    create: "기억 추가",
    correct: "기억 정정",
    retract: "기억 철회",
    reattribute: "다른 인물로 옮기기",
  }[action];
  const choices =
    kind === "entity_facts"
      ? o.data?.fact_types
          .filter((t) => t.support_level === "supported" && t.is_active)
          .map((t) => t.value)
      : kind === "entity_edges"
        ? o.data?.edge_types
            .filter((t) => t.active && t.write_supported === true)
            .map((t) => t.relation_type)
        : o.data?.observation_types
            .filter((t) => t.active)
            .map((t) => t.observation_type);
  const edgeDefinition = o.data?.edge_types.find((t) => t.relation_type === type);
  const legacyEdge =
    kind === "entity_edges" && edgeDefinition?.write_supported === false;
  const sameEdgeType = kind === "entity_edges" && type === p?.relation_type;
  const effectiveDirection = sameEdgeType ? p?.directed : edgeDefinition?.directed_default;
  const historicalDirection = sameEdgeType && edgeDefinition &&
    p?.directed !== edgeDefinition.directed_default;
  const supported = choices?.includes(type) || (
    kind === "entity_edges" && Boolean(item) &&
    type === p?.relation_type && edgeDefinition?.active
  );
  const typeLabel = (value: string) =>
    kind === "entity_edges" ? relationLabel(value, o.data) : label(value);
  const unknownProperties = Object.entries(edgeProperties).filter(
    ([key]) => !knownEdgeProperty(key),
  );
  function changeKind(next: RecordType) {
    setKind(next);
    setType(
      next === "entity_facts"
        ? "organization"
        : next === "entity_edges"
          ? o.data?.edge_types.find((t) => t.active && t.write_supported === true)?.relation_type || ""
          : "recent_interaction",
    );
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (saving) return;
    setError(undefined);
    try {
      if (!writable)
        throw new Error(
          "연결된 서버가 현재 기억 저장 방식을 지원하는지 확인해 주세요.",
        );
      let payload: MemoryPayload | undefined;
      if (!retract) {
        if (move && legacyEdge)
          throw new Error("이전 관계 유형은 먼저 기억 정정에서 현재 유형으로 바꾼 뒤 인물을 옮겨 주세요.");
        if (!supported)
          throw new Error(
            "현재 지원하는 기억 종류를 선택해 주세요. 이전 메모는 맥락으로 정정할 수 있어요.",
          );
        if (move && item) {
          payload = { ...item.payload };
          if (kind === "entity_facts") payload.entity_id = target;
          else if (kind === "observations") payload.subject_entity_id = target;
          else {
            payload.from_entity_id = target;
            payload.to_entity_id = other;
          }
        } else {
          payload = {
            claim_basis: basis,
            confidence: Number(confidence),
            valid_from: editedTime(from, item?.valid_from),
            valid_to: editedTime(to, item?.valid_to),
          };
          if (kind === "entity_facts")
            Object.assign(payload, {
              entity_id: target,
              fact_type: type,
              ...(isDate
                ? dateValue(year, month, day)
                : { content: content.trim(), value: { text: content.trim() } }),
            });
          else if (kind === "entity_edges")
            Object.assign(payload, {
              from_entity_id: target,
              to_entity_id: other,
              relation_type: type,
              directed: effectiveDirection,
              claim_text: content.trim(),
              properties: legacyEdge ? p?.properties || {} : Object.fromEntries(
                Object.entries(edgeProperties).map(([key, value]) => [
                  key,
                  knownEdgeProperty(key) && typeof value === "string" && value !== p?.properties?.[key]
                    ? value.trim() : value,
                ]),
              ),
            });
          else
            Object.assign(payload, {
              subject_entity_id: target,
              observation_type: type,
              content: content.trim(),
              occurred_at: editedTime(occurred, p?.occurred_at),
              related_entities: participants,
            });
        }
      }
      const body: Omit<MemoryWrite, "request_id"> = {
        action,
        created_by: "user",
        source: {
          source_type: "manual_entry",
          actor: actor.trim(),
          excerpt: excerpt.trim(),
          occurred_at: iso(sourceTime),
        },
        ...(reason.trim() ? { reason: reason.trim() } : {}),
        ...(item
          ? {
              old_record_ref: item.record_ref,
              expected_updated_at: item.updated_at,
            }
          : {}),
        ...(payload ? { record: { record_type: kind, payload } } : {}),
      };
      const signature = JSON.stringify(body);
      if (pending.current?.signature !== signature)
        pending.current = { signature, id: newRequestId() };
      setSaving(true);
      const receipt = await api<Receipt>("/api/memories", {
        method: "POST",
        body: JSON.stringify({ ...body, request_id: pending.current.id }),
      });
      onSaved(receipt);
    } catch (err) {
      setError(err);
    } finally {
      setSaving(false);
    }
  }
  return (
    <Modal
      title={title}
      onClose={() => {
        if (!saving) onClose();
      }}
    >
      <form onSubmit={submit}>
        <div className="modal-body stack">
          {item && (
            <section className="evidence-card">
              <span className="eyebrow">변경할 기억</span>
              <p>{item.content}</p>
              <p className="small muted">
                {basisLabels[item.claim_basis]} ·{" "}
                {item.sources.find((s) => s.actor)?.actor || "출처 미상"}
              </p>
            </section>
          )}
          {o.loading ? (
            <Loading />
          ) : o.error ? (
            <ErrorState error={o.error} retry={o.reload} />
          ) : null}
          {config.error ? (
            <ErrorState error={config.error} retry={config.reload} />
          ) : !config.loading && !writable ? (
            <p className="error-state" role="alert">
              연결된 서버가 현재 기억 저장 방식을 지원하지 않아요. 서버와 웹을
              함께 업데이트해 주세요.
            </p>
          ) : null}
          {retract ? (
            <p>
              이 기억을 현재 참조 대상에서 제외합니다. 원래 내용과 출처는 변경
              이력에 남습니다.
            </p>
          ) : (
            <>
              {!move && (
                <div className="field-grid">
                  <div className="field">
                    <label htmlFor="memory-kind">기억 구분</label>
                    <select
                      id="memory-kind"
                      disabled={item?.record_type === "entity_edges"}
                      value={kind}
                      onChange={(e) => changeKind(e.target.value as RecordType)}
                    >
                      <option value="entity_facts">프로필 정보</option>
                      <option value="observations">맥락·선호·감정</option>
                      <option
                        value="entity_edges"
                        disabled={
                          Boolean(item) && item?.record_type !== "entity_edges"
                        }
                      >
                        관계
                      </option>
                    </select>
                  </div>
                  <div className="field">
                    <label htmlFor="memory-type">종류</label>
                    <select
                      id="memory-type"
                      value={type}
                      onChange={(e) => setType(e.target.value)}
                    >
                      {(!choices?.includes(type) || legacyEdge) && (
                        <option value={type}>{typeLabel(type)} · 이전 종류</option>
                      )}
                      {choices?.map((v) => (
                        <option key={v} value={v}>
                          {typeLabel(v)}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
              )}
              <PersonPicker
                title={
                  kind === "entity_edges" ? "관계 시작 인물" : "기억의 대상"
                }
                value={target}
                onChange={setTarget}
                initialName={
                  item?.entities.find((e) => e.id === target)?.display_name
                }
                disabled={action === "correct"}
              />
              {kind === "entity_edges" && (
                <>
                  <PersonPicker
                    title="관계 대상 인물"
                    value={other}
                    onChange={setOther}
                    initialName={
                      item?.entities.find((e) => e.id === other)?.display_name
                    }
                    disabled={action === "correct"}
                  />
                  <p className="small muted">
                    {edgeDefinition?.description}
                  </p>
                  <p className="small muted">
                    {historicalDirection
                      ? `기존 기록의 ${effectiveDirection ? "방향 (시작 인물 → 대상 인물)" : "양방향"}을 유지합니다. 현재 유형 정의와 다르지만 문장 정정만으로 바꾸지 않습니다.`
                      : effectiveDirection
                        ? `시작 인물은 대상 인물의 ${relationLabel(type, o.data)} · 대상 인물은 시작 인물의 ${relationLabel(type, o.data, true)}`
                        : "두 사람 사이의 양방향 관계입니다."}
                  </p>
                  {legacyEdge && (
                    <p className="small warning">
                      {move && "인물을 옮기려면 먼저 기억 정정에서 현재 관계 유형으로 바꿔 주세요. "}
                      이전에 저장한 관계 유형입니다. 그대로 보존하거나, 근거를 확인한 뒤 새 유형을 직접 선택해 정정하세요.
                      {edgeDefinition?.replacement_type && ` 권장 유형: ${relationLabel(edgeDefinition.replacement_type, o.data)}.`}
                    </p>
                  )}
                  {!move && (
                    <>
                      {edgePropertyFields.map(([key, title]) => (
                        <div className="field" key={key}>
                          <label htmlFor={`edge-${key}`}>{title}</label>
                          <input
                            id={`edge-${key}`}
                            disabled={legacyEdge}
                            value={typeof edgeProperties[key] === 'string' ? edgeProperties[key] as string : ''}
                            maxLength={edgeDefinition?.allowed_properties_schema?.properties?.[key]?.maxLength || 300}
                            onChange={(event) => setEdgeProperties((current) => {
                              const next = { ...current };
                              if (event.target.value) next[key] = event.target.value;
                              else delete next[key];
                              return next;
                            })}
                          />
                        </div>
                      ))}
                      {unknownProperties.length > 0 && (
                        <details><summary>보존되는 기존 속성</summary>
                          <p className="small muted">새 유형으로 바꾸려면 기존 속성의 의미를 위 항목에 옮긴 후, 해당 속성을 직접 제거해 주세요. 원본은 변경 이력에 남습니다.</p>
                          {unknownProperties.map(([key, value]) => (
                            <div key={key} className="stack">
                              <p>{key}: {JSON.stringify(value)}</p>
                              <button type="button" className="text-link" disabled={legacyEdge}
                                onClick={() => setEdgeProperties((current) => {
                                  const next = { ...current };
                                  delete next[key];
                                  return next;
                                })}
                              >{key} 속성 제거</button>
                            </div>
                          ))}
                        </details>
                      )}
                    </>
                  )}
                </>
              )}
              {!move && (
                <>
                  {isDate ? (
                    <fieldset className="field-grid">
                      <legend>알고 있는 날짜만 입력하세요</legend>
                      <div className="field">
                        <label htmlFor="fact-year">연도</label>
                        <input
                          id="fact-year"
                          type="number"
                          min="1"
                          max="9999"
                          value={year}
                          onChange={(e) => setYear(e.target.value)}
                        />
                      </div>
                      <div className="field">
                        <label htmlFor="fact-month">월</label>
                        <input
                          id="fact-month"
                          type="number"
                          min="1"
                          max="12"
                          value={month}
                          onChange={(e) => setMonth(e.target.value)}
                        />
                      </div>
                      <div className="field">
                        <label htmlFor="fact-day">일</label>
                        <input
                          id="fact-day"
                          type="number"
                          min="1"
                          max="31"
                          value={day}
                          onChange={(e) => setDay(e.target.value)}
                        />
                      </div>
                    </fieldset>
                  ) : (
                    <div className="field">
                      <label htmlFor="memory-content">기억 내용</label>
                      <textarea
                        id="memory-content"
                        value={content}
                        onChange={(e) => setContent(e.target.value)}
                        required
                        maxLength={4000}
                        rows={3}
                      />
                    </div>
                  )}
                  <div className="field-grid">
                    <div className="field">
                      <label htmlFor="memory-basis">근거 구분</label>
                      <select
                        id="memory-basis"
                        value={basis}
                        onChange={(e) =>
                          setBasis(
                            e.target.value as MemoryPayload["claim_basis"],
                          )
                        }
                      >
                        {o.data?.claim_bases.map((b) => (
                          <option key={b.value} value={b.value}>
                            {basisLabels[b.value]}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div className="field">
                      <label htmlFor="memory-confidence">
                        출처에 대한 확신도 (0–1)
                      </label>
                      <input
                        id="memory-confidence"
                        type="number"
                        min="0"
                        max="1"
                        step="any"
                        value={confidence}
                        onChange={(e) => setConfidence(e.target.value)}
                        required
                      />
                    </div>
                  </div>
                  <p className="small muted">
                    전해 들었다는 표시는 사실 검증을 뜻하지 않아요. 미래 계획과
                    불확실한 표현을 내용에 그대로 남겨 주세요.
                  </p>
                  <details>
                    <summary>시점과 관련 인물</summary>
                    <div className="stack">
                      <div className="field-grid">
                        <div className="field">
                          <label htmlFor="valid-from">유효 시작 시점</label>
                          <input
                            id="valid-from"
                            type="datetime-local"
                            step="0.001"
                            value={from}
                            onChange={(e) => setFrom(e.target.value)}
                          />
                        </div>
                        <div className="field">
                          <label htmlFor="valid-to">유효 종료 시점</label>
                          <input
                            id="valid-to"
                            type="datetime-local"
                            step="0.001"
                            value={to}
                            onChange={(e) => setTo(e.target.value)}
                          />
                        </div>
                      </div>
                      <p className="small muted">
                        시간은 이 기기의 현지 시간이에요. 모르는 시점은 비워
                        두세요.
                      </p>
                      {kind === "observations" && (
                        <>
                          <div className="field">
                            <label htmlFor="event-time">
                              내용 속 사건 시점
                            </label>
                            <input
                              id="event-time"
                              type="datetime-local"
                              step="0.001"
                              value={occurred}
                              onChange={(e) => setOccurred(e.target.value)}
                            />
                          </div>
                          {participants.map((part, i) => (
                            <div className="panel content-panel stack" key={i}>
                              <PersonPicker
                                title={`관련 인물 ${i + 1}`}
                                value={part.entity_id}
                                initialName={
                                  item?.entities.find(
                                    (e) => e.id === part.entity_id,
                                  )?.display_name
                                }
                                onChange={(value) =>
                                  setParticipants((current) =>
                                    current.map((p, index) =>
                                      index === i
                                        ? { ...p, entity_id: value }
                                        : p,
                                    ),
                                  )
                                }
                              />
                              <label className="field">
                                역할
                                <select
                                  value={part.role}
                                  onChange={(e) =>
                                    setParticipants((current) =>
                                      current.map((p, index) =>
                                        index === i
                                          ? { ...p, role: e.target.value }
                                          : p,
                                      ),
                                    )
                                  }
                                >
                                  {o.data?.participant_roles.map((role) => (
                                    <option key={role.value} value={role.value}>
                                      {label(role.value)}
                                    </option>
                                  ))}
                                </select>
                              </label>
                              <button
                                type="button"
                                className="text-link"
                                onClick={() =>
                                  setParticipants((p) =>
                                    p.filter((_, index) => index !== i),
                                  )
                                }
                              >
                                관련 인물 제거
                              </button>
                            </div>
                          ))}
                          <button
                            type="button"
                            className="button"
                            disabled={participants.length >= 20}
                            onClick={() =>
                              setParticipants((p) => [
                                ...p,
                                { entity_id: "", role: "about" },
                              ])
                            }
                          >
                            관련 인물 추가
                          </button>
                        </>
                      )}
                    </div>
                  </details>
                </>
              )}
            </>
          )}
          <section className="stack">
            <h3>이번 입력의 출처</h3>
            <div className="field">
              <label htmlFor="source-actor">말한 사람</label>
              <input
                id="source-actor"
                value={actor}
                onChange={(e) => setActor(e.target.value)}
                placeholder="예: 나, 김민지"
                required
                maxLength={80}
              />
            </div>
            <div className="field">
              <label htmlFor="source-excerpt">근거가 되는 발언·직접 입력</label>
              <textarea
                id="source-excerpt"
                value={excerpt}
                onChange={(e) => setExcerpt(e.target.value)}
                required
                maxLength={4000}
                rows={3}
                placeholder="기억을 남기거나 바꾸는 근거를 적어 주세요."
              />
            </div>
            <div className="field">
              <label htmlFor="source-time">출처의 발화 시점 (선택)</label>
              <input
                id="source-time"
                type="datetime-local"
                step="0.001"
                value={sourceTime}
                onChange={(e) => setSourceTime(e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="change-reason">변경 이유 (선택)</label>
              <input
                id="change-reason"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                maxLength={1000}
              />
            </div>
          </section>
          {error ? (
            <div role="alert" className="error-state">
              <p>{errorText(error)}</p>
              {item && (
                <a
                  className="text-link"
                  href={`/changes?record=${encodeURIComponent(item.record_ref)}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  변경 이력을 새 창에서 확인
                </a>
              )}
            </div>
          ) : null}
        </div>
        <footer className="modal-footer">
          <button
            type="button"
            className="button"
            disabled={saving}
            onClick={onClose}
          >
            취소
          </button>
          <button
            className="button primary"
            type="submit"
            disabled={saving || o.loading || Boolean(o.error) || !writable}
          >
            {saving ? "저장 중…" : retract ? "철회 기록 저장" : "저장"}
          </button>
        </footer>
      </form>
    </Modal>
  );
}
