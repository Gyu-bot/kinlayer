import { useState } from "react";
import {
  api,
  actionLabels,
  actorLabel,
  sourceLabels,
  basisLabels,
  dateTime,
  kindLabels,
  label,
  memoryPath,
  memoryText,
  memoryUrl,
  query,
  useResource,
  type Episode,
  type MemoryChange,
  type MemoryItem,
  type MemoryWrite,
  type Page,
  type Receipt,
} from "./data";
import {
  Empty,
  ErrorState,
  Loading,
  MemoryCard,
  Pager,
  PersonPicker,
} from "./common";
import { MemoryEditor } from "./MemoryEditor";

function historyReference(reference: string) {
  const match = /^([^:]+):([^:\s]+)$/.exec(reference);
  if (match && ["entity_facts", "entity_edges", "observations"].includes(match[1])) {
    return { kind: "memory", href: memoryUrl(reference) } as const;
  }
  if (match?.[1] === "entities") {
    return { kind: "person", href: `/people/${encodeURIComponent(match[2])}` } as const;
  }
  return { kind: "other" } as const;
}

function HistoryReferenceLink({
  reference,
  memoryLabel,
  personLabel = "현재 인물 보기",
}: {
  reference: string;
  memoryLabel: string;
  personLabel?: string;
}) {
  const target = historyReference(reference);
  return target.kind === "other" ? (
    <details className="diagnostic-details">
      <summary>당시 값 없음 · 기술 참조</summary>
      <code>{reference}</code>
    </details>
  ) : (
    <a className="text-link" href={target.href}>
      {target.kind === "memory" ? memoryLabel : personLabel}
    </a>
  );
}

function historyMemoryPath(reference?: string | null) {
  return reference && historyReference(reference).kind === "memory"
    ? memoryPath(reference)
    : null;
}

export function SourceEvidence({ item }: { item: MemoryItem }) {
  return (
    <div className="stack">
      {item.sources.map((source, i) => (
        <section className="evidence-card" key={`${source.episode_id}:${i}`}>
          <div className="row between">
            <h3>{source.actor || "말한 사람 미상"}</h3>
            <span className="small muted">
              {source.source_type === "manual_entry"
                ? "직접 입력"
                : source.source_type === "correction"
                  ? "정정 발언"
                  : source.source_type || "출처 미상"}
            </span>
          </div>
          {source.missing && (
            <p className="small muted">
              원래 출처 문서를 찾을 수 없어요. 남아 있는 발췌만 표시합니다.
            </p>
          )}
          <blockquote>
            {source.excerpt ||
              "보존된 원문 발췌가 없어요. 출처를 새로 추정하지 않습니다."}
          </blockquote>
          <p className="small muted">
            발화 시점 · {dateTime(source.occurred_at)}
          </p>
          {source.source_ref && (
            <p className="small source-ref">위치 · {source.source_ref}</p>
          )}
          {source.episode_id && !source.missing && (
            <a className="text-link" href={`/sources/${source.episode_id}`}>
              출처와 연결된 기억 보기
            </a>
          )}
        </section>
      ))}
    </div>
  );
}
export function ChangeRows({
  recordRef,
  entityId,
}: {
  recordRef?: string;
  entityId?: string;
}) {
  const [offset, setOffset] = useState(0);
  const r = useResource<Page<MemoryChange>>(
    `/api/memory-changes?${query({ record_ref: recordRef, entity_id: entityId, limit: 10, offset })}`,
  );
  return (
    <>
      {r.loading ? (
        <Loading />
      ) : r.error ? (
        <ErrorState error={r.error} retry={r.reload} />
      ) : (
        r.data && (
          <>
            <div className="stack">
              {r.data.items.map((change) => (
                <article className="change-row" key={change.id}>
                  <div className="row between">
                    <a
                      className="text-link"
                      href={`/changes?change=${change.id}`}
                    >
                      {actionLabels[change.change_kind] || change.change_kind}
                    </a>
                    <time className="small muted">
                      {dateTime(change.created_at)}
                    </time>
                  </div>
                  <p>{change.reason || `${actorLabel(change.actor)}의 기록`}</p>
                  <div className="context-meta">
                    {change.old_record_ref && (
                      <HistoryReferenceLink
                        reference={change.old_record_ref}
                        memoryLabel="이전 기억"
                        personLabel="이전 참조의 현재 인물 보기"
                      />
                    )}
                    {change.new_record_ref && (
                      <HistoryReferenceLink
                        reference={change.new_record_ref}
                        memoryLabel="이후 기억"
                        personLabel="이후 참조의 현재 인물 보기"
                      />
                    )}
                    {change.source_episode_id && (
                      <a href={`/sources/${change.source_episode_id}`}>
                        변경 근거
                      </a>
                    )}
                  </div>
                </article>
              ))}
            </div>
            {!r.data.total && <Empty>남아 있는 변경 기록이 없어요.</Empty>}
            <Pager page={r.data} onPage={setOffset} />
          </>
        )
      )}
    </>
  );
}
export function MemoryDetail({
  recordRef,
  onNavigate,
  onChanged,
}: {
  recordRef: string;
  onNavigate: (path: string) => void;
  onChanged?: () => void;
}) {
  const r = useResource<MemoryItem>(memoryPath(recordRef));
  const [action, setAction] = useState<MemoryWrite["action"]>();
  const [notice, setNotice] = useState("");
  function saved(receipt: Receipt) {
    setAction(undefined);
    setNotice("변경이 저장됐어요.");
    onChanged?.();
    if (receipt.new_record_ref) onNavigate(memoryUrl(receipt.new_record_ref));
    else r.reload();
  }
  return (
    <>
      {r.loading ? (
        <Loading />
      ) : r.error ? (
        <ErrorState error={r.error} retry={r.reload} />
      ) : (
        r.data && (
          <div className="detail-layout">
            <section className="stack">
              <div className="panel content-panel stack">
                <div className="row between">
                  <span className="eyebrow">
                    {kindLabels[r.data.record_type]} ·{" "}
                    {label(
                      r.data.payload.fact_type ||
                        r.data.payload.relation_type ||
                        r.data.payload.observation_type ||
                        "",
                    )}
                  </span>
                  <span
                    className={`pill ${r.data.claim_basis === "inferred" ? "warning" : ""}`}
                  >
                    {basisLabels[r.data.claim_basis]}
                  </span>
                </div>
                <h2 className="memory-detail-content">{memoryText(r.data)}</h2>
                <div className="context-meta">
                  {r.data.entities.map((p) => (
                    <a key={`${p.id}:${p.role}`} href={`/people/${p.id}`}>
                      {p.display_name} · {label(p.role)}
                    </a>
                  ))}
                </div>
                <p className="small muted">
                  {r.data.is_current
                    ? "현재 참조할 수 있는 기억"
                    : r.data.status === "active"
                      ? "유효 기간 밖의 기억"
                      : r.data.status === "superseded"
                        ? "새 기록으로 정정된 이전 기억"
                        : ["deleted", "retracted"].includes(r.data.status)
                          ? "철회된 기억"
                          : r.data.status}
                </p>
                <dl className="mini-facts">
                  <div>
                    <dt>내용 속 사건</dt>
                    <dd>{dateTime(r.data.payload.occurred_at)}</dd>
                  </div>
                  <div>
                    <dt>유효 시작</dt>
                    <dd>{dateTime(r.data.valid_from)}</dd>
                  </div>
                  <div>
                    <dt>유효 종료</dt>
                    <dd>{dateTime(r.data.valid_to)}</dd>
                  </div>
                  <div>
                    <dt>저장 시점</dt>
                    <dd>{dateTime(r.data.created_at)}</dd>
                  </div>
                </dl>
                {["active", "disputed"].includes(r.data.status) && (
                  <div className="row wrap">
                    <button
                      className="button primary"
                      onClick={() => setAction("correct")}
                    >
                      이 기억 정정
                    </button>
                    <button
                      className="button"
                      onClick={() => setAction("reattribute")}
                    >
                      다른 인물로 옮기기
                    </button>
                    <button
                      className="button ghost"
                      onClick={() => setAction("retract")}
                    >
                      철회
                    </button>
                  </div>
                )}
                <details>
                  <summary>기록 식별자와 진단 정보</summary>
                  <p className="small source-ref">{r.data.record_ref}</p>
                  <p className="small">
                    확신도 {r.data.confidence} · 변경 시점{" "}
                    {dateTime(r.data.updated_at)}
                  </p>
                </details>
              </div>
              <section className="stack">
                <h2>이 기억의 출처</h2>
                <SourceEvidence item={r.data} />
              </section>
            </section>
            <aside className="panel content-panel stack">
              <h2>변경 이력</h2>
              <ChangeRows key={r.data.updated_at} recordRef={recordRef} />
            </aside>
            {action && (
              <MemoryEditor
                item={r.data}
                action={action}
                onClose={() => setAction(undefined)}
                onSaved={saved}
              />
            )}
          </div>
        )
      )}
      {notice && (
        <p className="notice" role="status">
          {notice}
        </p>
      )}
    </>
  );
}
export function Memories({
  onNavigate,
}: {
  onNavigate: (path: string) => void;
}) {
  const params = new URLSearchParams(window.location.search),
    record = params.get("record");
  const [q, setQ] = useState(""),
    [kind, setKind] = useState(""),
    [basis, setBasis] = useState(""),
    [status, setStatus] = useState("active"),
    [person, setPerson] = useState(params.get("person") || ""),
    [offset, setOffset] = useState(0),
    [adding, setAdding] = useState(false);
  const r = useResource<Page<MemoryItem>>(
    record
      ? null
      : `/api/memories?${query({ q, record_type: kind, claim_basis: basis, status, entity_id: person, offset, limit: 20 })}`,
  );
  function filter(set: (value: string) => void, value: string) {
    set(value);
    setOffset(0);
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>{record ? "기억 상세" : "기억"}</h1>
          <p>한 번의 발언, 하나의 기억. 출처와 변화를 함께 살펴보세요.</p>
        </div>
        {record ? (
          <a className="button ghost" href="/memories">
            모든 기억
          </a>
        ) : (
          <button className="button primary" onClick={() => setAdding(true)}>
            기억 추가
          </button>
        )}
      </div>
      {record ? (
        <MemoryDetail key={record} recordRef={record} onNavigate={onNavigate} />
      ) : (
        <>
          <section className="panel content-panel memory-filters">
            <div className="field">
              <label htmlFor="memory-search">기억 검색</label>
              <input
                id="memory-search"
                value={q}
                placeholder="기억 속 문구"
                onChange={(e) => filter(setQ, e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="filter-kind">구분</label>
              <select
                id="filter-kind"
                value={kind}
                onChange={(e) => filter(setKind, e.target.value)}
              >
                <option value="">모든 종류</option>
                {Object.entries(kindLabels).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="filter-basis">근거</label>
              <select
                id="filter-basis"
                value={basis}
                onChange={(e) => filter(setBasis, e.target.value)}
              >
                <option value="">모든 근거</option>
                {Object.entries(basisLabels).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="filter-status">상태</label>
              <select
                id="filter-status"
                value={status}
                onChange={(e) => filter(setStatus, e.target.value)}
              >
                <option value="active">현재 기억</option>
                <option value="history">과거·철회·예정</option>
                <option value="all">모든 기록</option>
              </select>
            </div>
            <details>
              <summary>인물로 좁히기{person ? " · 선택됨" : ""}</summary>
              <PersonPicker
                value={person}
                onChange={(v) => filter(setPerson, v)}
              />
              {person && (
                <button
                  className="text-link"
                  onClick={() => filter(setPerson, "")}
                >
                  인물 필터 해제
                </button>
              )}
            </details>
          </section>
          {r.loading ? (
            <Loading />
          ) : r.error ? (
            <ErrorState error={r.error} retry={r.reload} />
          ) : (
            r.data && (
              <section className="panel content-panel">
                <div className="memory-grid">
                  {r.data.items.map((item) => (
                    <MemoryCard key={item.record_ref} item={item} />
                  ))}
                </div>
                {!r.data.total && <Empty>조건에 맞는 기억이 없어요.</Empty>}
                <Pager page={r.data} onPage={setOffset} />
              </section>
            )
          )}
        </>
      )}
      {adding && (
        <MemoryEditor
          personId={person}
          onClose={() => setAdding(false)}
          onSaved={(receipt) => {
            setAdding(false);
            onNavigate(memoryUrl(receipt.new_record_ref!));
          }}
        />
      )}
    </>
  );
}
export function SourcePage({ id }: { id: string }) {
  const [offset, setOffset] = useState(0);
  const source = useResource<Episode>(
      `/api/episodes/${encodeURIComponent(id)}`,
    ),
    r = useResource<Page<MemoryItem>>(
      `/api/memories?${query({ source_episode_id: id, status: "all", limit: 20, offset })}`,
    );
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>출처</h1>
          <p>보존된 발췌와 이 출처에 연결된 기억이에요.</p>
        </div>
      </div>
      {source.loading ? (
        <Loading />
      ) : source.error ? (
        <ErrorState error={source.error} retry={source.reload} />
      ) : (
        source.data && (
          <section className="panel content-panel stack">
            <div className="row between">
              <h2>{source.data.actor}</h2>
              <span className="pill">
                {sourceLabels[source.data.source_type] ||
                  source.data.source_type}
              </span>
            </div>
            <blockquote>
              {source.data.body_excerpt || "남아 있는 원문 발췌가 없어요."}
            </blockquote>
            <dl className="mini-facts">
              <div>
                <dt>발화 시점</dt>
                <dd>{dateTime(source.data.occurred_at)}</dd>
              </div>
              <div>
                <dt>수집 시점</dt>
                <dd>{dateTime(source.data.ingested_at)}</dd>
              </div>
              {source.data.source_ref && (
                <div>
                  <dt>출처 위치</dt>
                  <dd className="source-ref">{source.data.source_ref}</dd>
                </div>
              )}
            </dl>
          </section>
        )
      )}
      <section className="panel content-panel stack">
        <h2>연결된 기억</h2>
        {r.loading ? (
          <Loading />
        ) : r.error ? (
          <ErrorState error={r.error} retry={r.reload} />
        ) : (
          r.data && (
            <>
              <div className="memory-grid">
                {r.data.items.map((item) => (
                  <MemoryCard key={item.record_ref} item={item} />
                ))}
              </div>
              {!r.data.total && <Empty>연결된 기억이 없어요.</Empty>}
              <Pager page={r.data} onPage={setOffset} />
            </>
          )
        )}
      </section>
    </>
  );
}
export function Changes() {
  const params = new URLSearchParams(window.location.search),
    explicit = params.get("change"),
    record = params.get("record");
  const [person, setPerson] = useState(params.get("person") || ""),
    [offset, setOffset] = useState(0),
    [selected, setSelected] = useState<string | null>(explicit);
  const r = useResource<Page<MemoryChange>>(
    `/api/memory-changes?${query({ record_ref: record, entity_id: person, limit: 20, offset })}`,
  );
  const id = selected || r.data?.items[0]?.id;
  const detail = useResource<MemoryChange>(
    id ? `/api/memory-changes/${id}` : null,
  );
  const old = useResource<MemoryItem>(
    historyMemoryPath(detail.data?.old_record_ref),
  );
  const next = useResource<MemoryItem>(
    historyMemoryPath(detail.data?.new_record_ref),
  );
  const source = useResource<Episode>(
    detail.data?.source_episode_id
      ? `/api/episodes/${detail.data.source_episode_id}`
      : null,
  );
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>변경 이력</h1>
          <p>기억이 어떻게 쌓이고 달라졌는지, 이유와 출처를 따라가 보세요.</p>
        </div>
      </div>
      {record ? (
        <div className="panel content-panel">
          <HistoryReferenceLink
            reference={record}
            memoryLabel="선택한 기억 보기"
            personLabel="선택한 참조의 현재 인물 보기"
          />{" "}
          ·{" "}
          <a className="text-link" href="/changes">
            전체 이력 보기
          </a>
        </div>
      ) : (
        <details className="panel content-panel">
          <summary>인물로 좁히기</summary>
          <PersonPicker
            value={person}
            onChange={(v) => {
              setPerson(v);
              setOffset(0);
              setSelected(null);
            }}
          />
          {person && (
            <button
              className="text-link"
              onClick={() => {
                setPerson("");
                setOffset(0);
                setSelected(null);
              }}
            >
              필터 해제
            </button>
          )}
        </details>
      )}
      <div className="review-layout">
        <section className="panel review-queue">
          {r.loading ? (
            <Loading />
          ) : r.error ? (
            <ErrorState error={r.error} retry={r.reload} />
          ) : (
            r.data && (
              <>
                <div className="queue-heading">
                  <h2>기억의 변화</h2>
                  <span className="pill">{r.data.total}개</span>
                </div>
                {r.data.items.map((change) => (
                  <button
                    className={`review-item ${id === change.id ? "selected" : ""}`}
                    key={change.id}
                    onClick={() => setSelected(change.id)}
                  >
                    <span className="pill">
                      {actionLabels[change.change_kind] || change.change_kind}
                    </span>
                    <strong>
                      {change.reason || `${actorLabel(change.actor)}의 기록`}
                    </strong>
                    <span className="small muted">
                      {dateTime(change.created_at)}
                    </span>
                  </button>
                ))}
                {!r.data.total && <Empty>아직 변경 이력이 없어요.</Empty>}
                <Pager
                  page={r.data}
                  onPage={(v) => {
                    setOffset(v);
                    setSelected(null);
                  }}
                />
              </>
            )
          )}
        </section>
        <section className="panel review-detail">
          {detail.loading ? (
            <Loading />
          ) : detail.error ? (
            <ErrorState error={detail.error} retry={detail.reload} />
          ) : detail.data ? (
            <div className="stack">
              <div className="row between">
                <span className="pill">
                  {actionLabels[detail.data.change_kind] ||
                    detail.data.change_kind}
                </span>
                <time className="small muted">
                  {dateTime(detail.data.created_at)}
                </time>
              </div>
              <h2>
                {detail.data.reason ||
                  `${actorLabel(detail.data.actor)}의 기록`}
              </h2>
              {[detail.data.old_record_ref, detail.data.new_record_ref].some(
                (reference) => reference && historyReference(reference).kind === "person",
              ) && (
                <p className="small muted">
                  인물 이관·변경 기록이에요. 아래 링크는 현재 인물 정보로 연결됩니다.
                </p>
              )}
              <div className="compare-grid">
                {[
                  {
                    name: "이전",
                    resource: old,
                    ref: detail.data.old_record_ref,
                  },
                  {
                    name: "이후",
                    resource: next,
                    ref: detail.data.new_record_ref,
                  },
                ].map((side) => (
                  <div className="compare-card" key={side.name}>
                    <span className="eyebrow">
                      {side.name}{" "}
                      {!side.ref || historyReference(side.ref).kind === "memory"
                        ? "기억"
                        : historyReference(side.ref).kind === "person"
                          ? "인물 기록"
                          : "기록"}
                    </span>
                    {side.ref && historyReference(side.ref).kind !== "memory" ? (
                      <div className="stack">
                        <p>
                          {historyReference(side.ref).kind === "person"
                            ? "당시 인물 상태는 보관되어 있지 않아 전후 값을 비교할 수 없어요."
                            : "당시 값은 보관되어 있지 않아 전후 값을 비교할 수 없어요."}
                        </p>
                        <HistoryReferenceLink
                          reference={side.ref}
                          memoryLabel={`${side.name} 기억`}
                        />
                      </div>
                    ) : side.resource.loading ? (
                      <Loading />
                    ) : side.resource.error ? (
                      <ErrorState
                        error={side.resource.error}
                        retry={side.resource.reload}
                      />
                    ) : side.resource.data ? (
                      <MemoryCard item={side.resource.data} />
                    ) : (
                      <p>
                        {side.ref
                          ? "기록을 불러올 수 없어요."
                          : side.name === "이후"
                            ? "현재 참조에서 제외됨"
                            : "새로 저장된 기억"}
                      </p>
                    )}
                  </div>
                ))}
              </div>
              <h3>변경의 근거</h3>
              {source.loading ? (
                <Loading />
              ) : source.error ? (
                <ErrorState error={source.error} retry={source.reload} />
              ) : source.data ? (
                <div className="evidence-card">
                  <p className="small muted">
                    {source.data.actor} · {dateTime(source.data.occurred_at)}
                  </p>
                  <blockquote>{source.data.body_excerpt}</blockquote>
                  <a className="text-link" href={`/sources/${source.data.id}`}>
                    출처 자세히 보기
                  </a>
                </div>
              ) : (
                <p className="muted">이전 기록에 출처가 남아 있지 않아요.</p>
              )}
            </div>
          ) : (
            <Empty>왼쪽에서 변경 기록을 선택하세요.</Empty>
          )}
        </section>
      </div>
    </>
  );
}
