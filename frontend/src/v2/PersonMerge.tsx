import { useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError } from "../api/client";
import { api, errorText, label, memoryText, memoryUrl, newRequestId, query, type MemoryItem, type Page, type Person } from "./data";
import { Loading, Modal, PersonPicker } from "./common";

type Alias = { alias: string; status: string };
type Preview = { entity: Person; aliases: Alias[]; facts: MemoryItem[]; total: number };
type MergeCandidate = {
  id: string;
  candidate_type: string;
  created_by: string;
  status: string;
  canonical_record_ref: string | null;
  payload: { source_entity_id: string; target_entity_id: string; merge_plan?: { web_intent_id?: string } };
};
type Intent = { id: string; source: string; target: string; note: string; candidateId?: string; createSent: boolean };

async function allPages<T>(path: string, signal?: AbortSignal): Promise<T[]> {
  const items: T[] = [];
  for (let offset = 0; ; ) {
    const page = await api<Page<T>>(`${path}&limit=200&offset=${offset}`, { signal });
    items.push(...page.items);
    offset += page.items.length;
    if (offset >= page.total) return items;
    if (!page.items.length) throw new Error("목록이 변경됐어요. 최신 정보를 다시 불러와 주세요.");
  }
}

async function previewPerson(id: string, signal: AbortSignal): Promise<Preview> {
  const [entity, aliases, facts, memories] = await Promise.all([
    api<Person>(`/api/entities/${encodeURIComponent(id)}`, { signal }),
    api<Page<Alias>>(`/api/entities/${encodeURIComponent(id)}/aliases`, { signal }),
    allPages<MemoryItem>(`/api/memories?${query({ entity_id: id, record_type: "entity_facts", status: "active" })}`, signal),
    api<Page<MemoryItem>>(`/api/memories?${query({ entity_id: id, status: "active", limit: 1 })}`, { signal }),
  ]);
  if (entity.status !== "active" || entity.is_system || entity.system_role) {
    throw new Error("현재 등록된 일반 인물끼리만 병합할 수 있어요. 나 또는 이미 병합된 인물은 선택할 수 없습니다.");
  }
  return { entity, aliases: aliases.items.filter((a) => a.status === "active"), facts, total: memories.total };
}

function matches(candidate: MergeCandidate, intent: Intent) {
  return candidate.candidate_type === "merge" && candidate.created_by === "user" &&
    candidate.payload.source_entity_id === intent.source && candidate.payload.target_entity_id === intent.target &&
    candidate.payload.merge_plan?.web_intent_id === intent.id;
}

function Comparison({ person, title }: { person: Preview; title: string }) {
  return <section className="merge-person stack" aria-label={title}>
    <div><span className="eyebrow">{title}</span><h3>{person.entity.display_name}</h3>
      <span className="small muted">{person.entity.id.slice(0, 6)}</span></div>
    <p className="small">별칭: {person.aliases.map((a) => a.alias).join(" · ") || "없음"}</p>
    <p className="small">현재 정보 {person.total}개 · 프로필 {person.facts.length}개</p>
    <details><summary>프로필 비교</summary><div className="stack">
      {person.facts.map((fact) => <a key={fact.record_ref} className="text-link" href={memoryUrl(fact.record_ref)} target="_blank" rel="noreferrer">{label(fact.payload.fact_type || "프로필")} · {memoryText(fact)}</a>)}
      {!person.facts.length && <p className="small muted">등록된 프로필 정보가 없어요.</p>}
    </div></details>
    <a className="text-link" href={`/people/${person.entity.id}`} target="_blank" rel="noreferrer">인물 정보 새 탭에서 보기</a>
  </section>;
}

export function PersonMerge({ person, onClose, onMerged }: {
  person: Person; onClose: () => void; onMerged: (targetId: string) => void;
}) {
  const [otherId, setOtherId] = useState("");
  const [reversed, setReversed] = useState(false);
  const [preview, setPreview] = useState<{ source: Preview; target: Preview }>();
  const [loading, setLoading] = useState(false);
  const [version, setVersion] = useState(0);
  const [confirmed, setConfirmed] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [locked, setLocked] = useState(false);
  const [error, setError] = useState<unknown>();
  const intent = useRef<Intent | undefined>(undefined);
  const submitting = useRef(false);
  const sourceId = reversed ? person.id : otherId;
  const targetId = reversed ? otherId : person.id;

  useEffect(() => {
    setPreview(undefined);
    setConfirmed(false);
    setError(undefined);
    if (!otherId) { setLoading(false); return; }
    const controller = new AbortController();
    setLoading(true);
    Promise.all([previewPerson(sourceId, controller.signal), previewPerson(targetId, controller.signal)])
      .then(([source, target]) => { if (!controller.signal.aborted) setPreview({ source, target }); })
      .catch((err) => { if (!controller.signal.aborted) setError(err); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [otherId, sourceId, targetId, version]);

  const ready = preview?.source.entity.id === sourceId && preview?.target.entity.id === targetId && sourceId !== targetId;
  async function merge(event: FormEvent) {
    event.preventDefault();
    if (submitting.current || !ready || !confirmed || !preview) return;
    submitting.current = true;
    setBusy(true);
    setError(undefined);
    setLocked(true);
    const current = intent.current ||= {
      id: newRequestId(), source: sourceId, target: targetId, createSent: false,
      note: `${preview.source.entity.display_name} (${sourceId})와 ${preview.target.entity.display_name} (${targetId})가 같은 사람임을 확인하고, ${preview.target.entity.display_name}에 병합합니다.${reason.trim() ? ` 이유: ${reason.trim()}` : ""}`,
    };
    try {
      let candidate: MergeCandidate;
      if (current.candidateId) {
        candidate = await api<MergeCandidate>(`/api/candidates/${encodeURIComponent(current.candidateId)}`);
      } else if (current.createSent) {
        // Candidate creation has no idempotency key. Recover this exact intent;
        // an unknown response must never trigger another create request.
        const candidates = await allPages<MergeCandidate>(`/api/candidates?${query({ candidate_type: "merge", target_entity_id: current.target })}`);
        const recovered = candidates.filter((item) => matches(item, current));
        if (recovered.length !== 1) throw new Error("병합 준비 요청의 결과를 아직 확인할 수 없어요. 잠시 후 결과를 다시 확인해 주세요. 확인되지 않은 병합은 실행하지 않습니다.");
        candidate = recovered[0];
        current.candidateId = candidate.id;
      } else {
        current.createSent = true;
        candidate = await api<MergeCandidate>("/api/candidates", {
          method: "POST", body: JSON.stringify({
            candidate_type: "merge", target_entity_id: current.target, created_by: "user", confidence: 1,
            payload: { source_entity_id: current.source, target_entity_id: current.target, reason: current.note,
              fields_to_merge: ["aliases", "profile_facts", "edges", "observations"],
              merge_plan: { web_intent_id: current.id } },
          }),
        }).catch((err: unknown) => {
          // Only a definitive rejection of this POST allows a new intent.
          if (err instanceof ApiError && err.status >= 400 && err.status < 500) {
            intent.current = undefined;
            setLocked(false);
          }
          throw err;
        });
        current.candidateId = candidate.id;
      }
      if (!matches(candidate, current)) throw new Error("병합 요청의 대상이 달라졌어요. 창을 닫고 다시 확인해 주세요.");
      if (candidate.status === "pending" || candidate.status === "needs_clarification") {
        try {
          candidate = await api<MergeCandidate>(`/api/candidates/${encodeURIComponent(candidate.id)}/accept`, {
            method: "POST", body: JSON.stringify({ resolved_by: "user", resolution_note: current.note }),
          });
        } catch (err) {
          // The response can be lost after commit. Read the same candidate before
          // reporting failure or offering a retry of its atomic accept operation.
          const readback = await api<MergeCandidate>(`/api/candidates/${encodeURIComponent(candidate.id)}`).catch(() => null);
          if (readback?.status === "accepted" && matches(readback, current) && readback.canonical_record_ref === `entities:${current.target}`) candidate = readback;
          else throw err;
        }
      }
      if (!matches(candidate, current) || candidate.status !== "accepted" || candidate.canonical_record_ref !== `entities:${current.target}`) {
        throw new Error("병합 완료를 확인하지 못했어요. 요청 상태를 다시 확인해 주세요.");
      }
      onMerged(current.target);
    } catch (err) {
      setError(err);
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  }

  const profileConflict = error instanceof ApiError && error.code === "relationship_profile_merge_conflict";
  return <Modal title="인물 병합" onClose={() => { if (!submitting.current) onClose(); }}>
    <form onSubmit={merge}>
      <div className="modal-body stack">
        <p className="small muted">같은 사람으로 중복 등록된 두 기록을 하나로 모읍니다. 유지할 인물의 이름과 기본 설정이 남아요.</p>
        <PersonPicker title={reversed ? "유지할 인물" : "합칠 인물"} value={otherId} onChange={setOtherId}
          excludeIds={[person.id]} excludeSystem disabled={locked || busy}
          initialName={preview ? (reversed ? preview.target.entity.display_name : preview.source.entity.display_name) : undefined} />
        {loading && <Loading />}
        {ready && preview && <>
          <div className="merge-comparison"><Comparison person={preview.source} title="합쳐질 인물" /><Comparison person={preview.target} title="유지할 인물" /></div>
          <button className="button" type="button" disabled={locked || busy} onClick={() => setReversed((value) => !value)}>병합 방향 바꾸기</button>
          <div className="notice stack">
            <p><strong>{preview.source.entity.display_name} → {preview.target.entity.display_name}</strong></p>
            <p className="small">별칭·프로필·관계·기억을 모으고 기존 출처와 이력을 보존합니다. 서로 다른 프로필 값은 덮어쓰지 않고 함께 조회할 수 있어요. 중복 항목과 두 기록 사이의 관계는 이전 기록으로 남습니다.</p>
            <p className="small">합쳐질 인물의 원래 이름과 별도 저장 속성은 원본에 남고, 이름은 별칭으로 자동 추가되지 않아요. 병합 후 원래 인물은 목록에서 숨겨지며 자동으로 되돌리는 기능은 없습니다.</p>
          </div>
          <div className="field"><label htmlFor="merge-reason">병합 이유 (선택)</label><textarea id="merge-reason" value={reason} maxLength={500} disabled={locked || busy} onChange={(e) => setReason(e.target.value)} /></div>
          <label className="row"><input type="checkbox" checked={confirmed} disabled={locked || busy} onChange={(e) => setConfirmed(e.target.checked)} />두 기록이 같은 사람이며, 위 방향으로 병합할 것을 확인했어요.</label>
        </>}
        {!!error && <div className="error-state" role="alert">
          <p>{profileConflict ? "두 인물의 같은 관계 평가 항목이 겹쳐 병합하지 못했어요. 각 인물에서 해당 평가를 확인하고 하나를 정정하거나 철회한 뒤 다시 시도해 주세요." : errorText(error)}</p>
          {profileConflict && ["source_record_ref", "target_record_ref"].map((key, index) => {
            const ref = error.details[key];
            return typeof ref === "string" ? <a className="text-link" key={key} href={memoryUrl(ref)} target="_blank" rel="noreferrer">{index ? "유지할 인물" : "합쳐질 인물"}의 관계 평가 확인</a> : null;
          })}
          {!locked && <button type="button" className="button" onClick={() => setVersion((value) => value + 1)}>정보 다시 불러오기</button>}
        </div>}
      </div>
      <footer className="modal-footer">
        <button className="button" type="button" disabled={busy} onClick={onClose}>닫기</button>
        <button className="button primary" disabled={busy || !ready || !confirmed}>{busy ? "병합 확인 중…" : locked ? "결과 확인하고 재시도" : "확인한 인물 병합"}</button>
      </footer>
    </form>
  </Modal>;
}
