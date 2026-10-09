import { useState, type FormEvent } from "react";
import {
  api,
  basisLabels,
  dateTime,
  errorText,
  factText,
  label,
  memoryUrl,
  query,
  relationLabel,
  useResource,
  type MemoryItem,
  type Ontology,
  type Page,
  type Person as PersonRecord,
  type Receipt,
  type RecordType,
} from "./data";
import { Empty, ErrorState, Loading, MemoryCard, Modal, Pager } from "./common";
import { MemoryEditor } from "./MemoryEditor";
import { RelationshipProfile } from "./RelationshipProfile";
import { PersonMerge } from "./PersonMerge";
import { PersonDelete } from "./PersonDelete";
import { ChangeRows, SourceEvidence } from "./Memories";

type Alias = { id: string; alias: string; status: string };
export function Person({
  id,
  onNavigate,
}: {
  id: string;
  onNavigate: (path: string) => void;
}) {
  const ontology = useResource<Ontology>("/api/ontology");
  const [tab, setTab] = useState("overview"),
    [offset, setOffset] = useState(0),
    [factsOffset, setFactsOffset] = useState(0),
    [status, setStatus] = useState("active"),
    [version, setVersion] = useState(0),
    [adding, setAdding] = useState<RecordType | null>(null),
    [editing, setEditing] = useState(false),
    [merging, setMerging] = useState(false),
    [deleting, setDeleting] = useState(false),
    [notice, setNotice] = useState("");
  const entity = useResource<PersonRecord>(
    `/api/entities/${encodeURIComponent(id)}`,
    version,
  );
  const aliases = useResource<Page<Alias>>(
    `/api/entities/${encodeURIComponent(id)}/aliases`,
    version,
  );
  const records = useResource<Page<MemoryItem>>(
    `/api/memories?${query({ entity_id: id, record_type: tab === "profile" ? "entity_facts" : tab === "relations" ? "entity_edges" : tab === "overview" ? "observations" : "", status: tab === "sources" ? "all" : tab === "all" ? status : "active", limit: 20, offset })}`,
    version,
  );
  const facts = useResource<Page<MemoryItem>>(
    `/api/memories?${query({ entity_id: id, record_type: "entity_facts", status: "active", limit: 20 })}`,
    version,
  );
  const laterFacts = useResource<Page<MemoryItem>>(
    factsOffset
      ? `/api/memories?${query({ entity_id: id, record_type: "entity_facts", status: "active", limit: 20, offset: factsOffset })}`
      : null,
    version,
  );
  const overviewFacts = factsOffset ? laterFacts : facts;
  const relationship = useResource<Page<MemoryItem>>(
    `/api/memories?${query({ entity_id: id, record_type: "entity_edges", status: "active", limit: 5 })}`,
    version,
  );
  function saved(receipt: Receipt) {
    setAdding(null);
    setNotice("정보를 저장했어요.");
    setVersion((v) => v + 1);
    onNavigate(memoryUrl(receipt.new_record_ref!));
  }
  if (entity.loading) return <Loading />;
  if (entity.error)
    return <ErrorState error={entity.error} retry={entity.reload} />;
  if (!entity.data) return <Empty>인물을 찾을 수 없어요.</Empty>;
  const p = entity.data,
    activeAliases =
      aliases.data?.items.filter((a) => a.status === "active") || [];
  if (p.status === "merged")
    return (
      <div className="panel content-panel stack">
        <h1>{p.display_name}</h1>
        <p>다른 인물 기록으로 합쳐졌어요.</p>
        {typeof p.properties.merged_entity_ref === "string" && (
          <a
            className="button primary"
            href={`/people/${p.properties.merged_entity_ref.split(":")[1]}`}
          >
            합쳐진 인물로 이동
          </a>
        )}
        <a className="text-link" href={`/changes?person=${p.id}`}>
          이전 변경 이력
        </a>
        <PersonProperties properties={p.properties} />
      </div>
    );
  return (
    <>
      <section className="person-hero">
        <div className="avatar large xlarge">{p.display_name.slice(-2)}</div>
        <div>
          <div className="hero-name">
            <h1>{p.display_name}</h1>
            {p.system_role === "self" && <span className="pill">나</span>}
            {p.status !== "active" && <span className="pill">{p.status === "deleted" ? "삭제된 인물" : p.status}</span>}
          </div>
          <p className="hero-description">
            {facts.data?.items
              .filter((item) =>
                ["organization", "role", "job"].includes(item.payload.fact_type || ""),
              )
              .map(
                (item) =>
                  `${item.content}${item.claim_basis !== "reported" ? ` (${basisLabels[item.claim_basis]})` : ""}`,
              )
              .join(" · ")}
          </p>
          <p className="small muted">
            {activeAliases.map((a) => a.alias).join(" · ") ||
              "등록된 별칭 없음"}
          </p>
        </div>
        <div className="hero-actions wrap">
          <a className="button ghost" href={`/graph?focal=${p.id}`}>
            관계 보기
          </a>
          <button className="button" disabled={p.status !== "active"} onClick={() => setEditing(true)}>
            이름·별칭 편집
          </button>
          {p.status === "active" && !p.is_system && !p.system_role && (
            <>
              <button className="button" onClick={() => setMerging(true)}>인물 병합</button>
              <button className="button danger" onClick={() => setDeleting(true)}>인물 삭제</button>
            </>
          )}
          <button
            className="button"
            onClick={() => setAdding("entity_facts")}
            disabled={p.status !== "active"}
          >
            프로필 추가
          </button>
          <button
            className="button"
            onClick={() => setAdding("entity_edges")}
            disabled={p.status !== "active"}
          >
            관계 추가
          </button>
          <button
            className="button primary"
            onClick={() => setAdding("observations")}
            disabled={p.status !== "active"}
          >
            기억 추가
          </button>
        </div>
      </section>
      {p.status === "deleted" && <p className="notice" role="status">사람 목록에서 삭제된 인물입니다. 연결된 기억·프로필·관계와 원본은 보존되어 계속 조회할 수 있어요.</p>}
      {notice && (
        <p className="notice" role="status">
          {notice}
        </p>
      )}
      <div className="filter-tabs" aria-label="인물 상세 보기">
        {[
          ["overview", "개요"],
          ["all", "전체 정보"],
          ["profile", "프로필"],
          ["relations", "관계"],
          ["sources", "출처"],
          ["changes", "변경 이력"],
        ].map(([value, name]) => (
          <button
            key={value}
            className={`filter-tab ${tab === value ? "active" : ""}`}
            aria-pressed={tab === value}
            onClick={() => {
              setTab(value);
              setOffset(0);
              setFactsOffset(0);
            }}
          >
            {name}
          </button>
        ))}
      </div>
      <div className="detail-layout">
        <div className="stack">
          {tab === "overview" && (
            <section className="panel content-panel stack" aria-label="기본 정보">
              <div className="section-heading">
                <h2>기본 정보</h2>
                <button
                  className="text-link"
                  onClick={() => {
                    setTab("profile");
                    setOffset(0);
                  }}
                >
                  프로필 전체 보기
                </button>
              </div>
              <p className="small muted">현재 프로필 정보를 유형 제한 없이 보여드려요.</p>
              {overviewFacts.loading ? (
                <Loading />
              ) : overviewFacts.error ? (
                <ErrorState error={overviewFacts.error} retry={overviewFacts.reload} />
              ) : (
                <>
                  <div className="fact-grid">
                    {overviewFacts.data?.items.map((item) => (
                      <div className="fact" key={item.record_ref}>
                        <span className="eyebrow">
                          {label(item.payload.fact_type || "")}
                        </span>
                        <a href={memoryUrl(item.record_ref)}>
                          <p>
                            {factText({
                              fact_type: item.payload.fact_type || "",
                              value: item.payload.value || null,
                              content: item.content,
                            }) || (item.payload.value ? JSON.stringify(item.payload.value) : "내용 없음")}
                          </p>
                        </a>
                        <span className="small muted">
                          {basisLabels[item.claim_basis]}
                        </span>
                      </div>
                    ))}
                  </div>
                  {overviewFacts.data && <Pager page={overviewFacts.data} onPage={setFactsOffset} />}
                </>
              )}
              {!overviewFacts.loading && !overviewFacts.data?.total && !overviewFacts.error && (
                <p className="muted">등록된 프로필 정보가 없어요.</p>
              )}
            </section>
          )}
          {["overview", "relations"].includes(tab) && p.status === "active" && p.system_role !== "self" && (
            <RelationshipProfile personId={p.id} ontology={ontology.data} version={version}
              editable={p.status === "active"} onChanged={() => setVersion((v) => v + 1)} />
          )}
          {tab === "changes" ? (
            <section className="panel content-panel">
              <h2>이 사람의 변경 이력</h2>
              <ChangeRows entityId={id} />
            </section>
          ) : (
            <section className="panel content-panel stack">
              <div className="section-heading">
                <h2>
                  {tab === "overview"
                    ? "기억하고 있는 맥락"
                    : tab === "profile"
                      ? "프로필 정보"
                      : tab === "relations"
                        ? "연결된 관계"
                        : tab === "all"
                          ? "전체 정보"
                          : "기억별 출처"}
                </h2>
                <a className="text-link" href={`/memories?person=${id}`}>
                  기억 전체 보기
                </a>
              </div>
              {tab === "all" && (
                <>
                  <p className="small muted">프로필·관계·맥락을 모두 보여드려요. 이전·삭제된 정보는 상태를 바꾸어 확인할 수 있어요.</p>
                  <div className="field-inline">
                    <label htmlFor="person-record-status">정보 상태</label>
                    <select id="person-record-status" className="select" value={status} onChange={(event) => {
                      setStatus(event.target.value);
                      setOffset(0);
                    }}>
                      <option value="active">현재 정보</option>
                      <option value="history">이전·삭제된 정보</option>
                      <option value="all">모든 상태</option>
                    </select>
                  </div>
                </>
              )}
              {tab === "sources" && (
                <p className="small muted">
                  이전·삭제된 기억의 출처도 포함해 기억별로 보여드려요.
                </p>
              )}
              {records.loading ? (
                <Loading />
              ) : records.error ? (
                <ErrorState error={records.error} retry={records.reload} />
              ) : (
                records.data && (
                  <>
                    {records.data.items.map((item) => (
                      <div key={item.record_ref} className="stack">
                        <MemoryCard item={item} ontology={ontology.data} />
                        {tab === "sources" && <SourceEvidence item={item} />}
                      </div>
                    ))}
                    {!records.data.total && (
                      <Empty>해당 조건에 저장된 정보가 없어요.</Empty>
                    )}
                    <Pager page={records.data} onPage={setOffset} />
                  </>
                )
              )}
            </section>
          )}
          {["overview", "profile", "all"].includes(tab) && (
            <PersonProperties properties={p.properties} />
          )}
        </div>
        <aside className="stack detail-rail">
          <section className="panel content-panel stack">
            <h2>기억을 읽는 기준</h2>
            <p className="small muted">
              전해 들은 내용과 추론을 구분하고, 각 기억의 출처와 유효 시점을
              함께 살펴보세요.
            </p>
            <div className="row wrap">
              {Object.values(basisLabels).map((name) => (
                <span className="pill" key={name}>
                  {name}
                </span>
              ))}
            </div>
          </section>
          <section className="panel content-panel stack">
            <h2>연결된 관계</h2>
            {relationship.error ? (
              <ErrorState
                error={relationship.error}
                retry={relationship.reload}
              />
            ) : (
              relationship.data?.items.map((item) => (
                <a
                  className="relationship-item"
                  key={item.record_ref}
                  href={memoryUrl(item.record_ref)}
                >
                  <span>
                    {item.entities
                      .filter((e) => e.id !== id)
                      .map((e) => e.display_name)
                      .join(" · ")}
                  </span>
                  <span className="small muted">
                    {relationLabel(item.payload.relation_type || "", ontology.data, Boolean(item.payload.directed) && item.payload.from_entity_id === id)}
                  </span>
                </a>
              ))
            )}
            <a className="text-link" href={`/graph?focal=${id}`}>
              그래프에서 살펴보기
            </a>
          </section>
          <p className="rail-footnote">
            최근 참조 · {dateTime(p.last_referenced_at)}
          </p>
        </aside>
      </div>
      {adding && (
        <MemoryEditor
          personId={id}
          initialKind={adding}
          onClose={() => setAdding(null)}
          onSaved={saved}
        />
      )}{" "}
      {merging && <PersonMerge person={p} onClose={() => setMerging(false)} onMerged={(targetId) => {
        setMerging(false);
        setNotice("인물을 병합했어요. 기존 기록과 출처는 함께 보존됩니다.");
        setVersion((v) => v + 1);
        onNavigate(`/people/${encodeURIComponent(targetId)}`);
      }} />}
      {deleting && <PersonDelete person={p} onClose={() => setDeleting(false)} onDeleted={() => {
        setDeleting(false);
        setVersion((v) => v + 1);
        onNavigate("/people");
      }} />}
      {editing && (
        <IdentityEditor
          person={p}
          aliases={activeAliases}
          onClose={() => {
            setEditing(false);
            setVersion((v) => v + 1);
          }}
          onChanged={() => {
            setNotice("이름·별칭 변경이 저장됐어요.");
          }}
        />
      )}
    </>
  );
}

function PersonProperties({ properties }: { properties: PersonRecord["properties"] }) {
  const entries = Object.entries(properties).filter(([key]) => key !== "merged_entity_ref");
  if (!entries.length) return null;
  return (
    <details className="panel content-panel diagnostic-details">
      <summary>추가 저장 정보 ({entries.length}개)</summary>
      <p className="small muted">인물 속성에 보존된 정보예요. 프로필 기록과 별도로 저장된 값을 그대로 보여드려요.</p>
      <dl className="stack">
        {entries.map(([key, value]) => (
          <div className="fact" key={key}>
            <dt>{label(key)}</dt>
            <dd>{value === null ? "미설정" : typeof value === "object"
              ? <pre>{JSON.stringify(value, null, 2)}</pre>
              : String(value)}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}

function IdentityEditor({
  person,
  aliases,
  onClose,
  onChanged,
}: {
  person: PersonRecord;
  aliases: Alias[];
  onClose: () => void;
  onChanged: () => void;
}) {
  const [currentAliases, setCurrentAliases] = useState(aliases),
    [savedName, setSavedName] = useState(person.display_name);
  const [name, setName] = useState(person.display_name),
    [alias, setAlias] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(),
    [notice, setNotice] = useState("");
  async function mutate(path: string, method: string, body?: unknown) {
    setBusy(true);
    setError(undefined);
    try {
      await api(path, {
        method,
        ...(body ? { body: JSON.stringify(body) } : {}),
      });
      setNotice("저장했어요.");
      onChanged();
      api<Page<Alias>>(`/api/entities/${person.id}/aliases`)
        .then((result) =>
          setCurrentAliases(result.items.filter((a) => a.status === "active")),
        )
        .catch(() =>
          setNotice("저장했어요. 창을 닫으면 최신 별칭을 다시 불러옵니다."),
        );
      return true;
    } catch (err) {
      setError(err);
      return false;
    } finally {
      setBusy(false);
    }
  }
  async function saveName(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    if (
      await mutate(`/api/entities/${person.id}`, "PATCH", {
        display_name: name.trim(),
      })
    )
      setSavedName(name.trim());
  }
  async function addAlias(e: FormEvent) {
    e.preventDefault();
    if (!alias.trim()) return;
    if (
      await mutate(`/api/entities/${person.id}/aliases`, "POST", {
        alias: alias.trim(),
        created_by: "user",
      })
    )
      setAlias("");
  }
  return (
    <Modal
      title="이름·별칭 편집"
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <div className="modal-body stack">
        <form className="stack" onSubmit={saveName}>
          <div className="field">
            <label htmlFor="person-name">이름</label>
            <input
              id="person-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={200}
              required
            />
          </div>
          <button
            className="button primary"
            disabled={busy || name.trim() === savedName}
          >
            이름 저장
          </button>
        </form>
        <section className="stack">
          <h3>별칭</h3>
          {currentAliases.map((a) => (
            <div className="row between" key={a.id}>
              <span>{a.alias}</span>
              <button
                className="text-link"
                disabled={busy}
                onClick={() => mutate(`/api/aliases/${a.id}`, "DELETE")}
              >
                별칭 제거
              </button>
            </div>
          ))}
          <form className="stack" onSubmit={addAlias}>
            <div className="field">
              <label htmlFor="new-alias">새 별칭</label>
              <input
                id="new-alias"
                value={alias}
                onChange={(e) => setAlias(e.target.value)}
                required
                maxLength={200}
              />
            </div>
            <button className="button" disabled={busy}>
              별칭 추가
            </button>
          </form>
        </section>
        <p className="small muted">
          각 항목은 개별적으로 저장돼요. 소속·역할·맥락은 해당 기억에서 정정할
          수 있어요.
        </p>
        {notice && <p role="status">{notice}</p>}
        {error ? (
          <p className="error-state" role="alert">
            {errorText(error)}
          </p>
        ) : null}
      </div>
      <footer className="modal-footer">
        <button className="button" disabled={busy} onClick={onClose}>
          닫기
        </button>
      </footer>
    </Modal>
  );
}
