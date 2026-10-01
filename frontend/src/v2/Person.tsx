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
  useResource,
  type MemoryItem,
  type Page,
  type Person as PersonRecord,
  type Receipt,
} from "./data";
import { Empty, ErrorState, Loading, MemoryCard, Modal, Pager } from "./common";
import { MemoryEditor } from "./MemoryEditor";
import { ChangeRows, SourceEvidence } from "./Memories";

type Alias = { id: string; alias: string; status: string };
export function Person({
  id,
  onNavigate,
}: {
  id: string;
  onNavigate: (path: string) => void;
}) {
  const [tab, setTab] = useState("overview"),
    [offset, setOffset] = useState(0),
    [version, setVersion] = useState(0),
    [adding, setAdding] = useState(false),
    [editing, setEditing] = useState(false),
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
    `/api/memories?${query({ entity_id: id, record_type: tab === "profile" ? "entity_facts" : tab === "relations" ? "entity_edges" : tab === "overview" ? "observations" : "", status: tab === "sources" ? "all" : "active", limit: 20, offset })}`,
    version,
  );
  const facts = useResource<Page<MemoryItem>>(
    `/api/memories?${query({ entity_id: id, record_type: "entity_facts", status: "active", limit: 20 })}`,
    version,
  );
  const relationship = useResource<Page<MemoryItem>>(
    `/api/memories?${query({ entity_id: id, record_type: "entity_edges", status: "active", limit: 5 })}`,
    version,
  );
  function saved(receipt: Receipt) {
    setAdding(false);
    setNotice("기억을 저장했어요.");
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
            {p.status !== "active" && <span className="pill">{p.status}</span>}
          </div>
          <p className="hero-description">
            {facts.data?.items
              .filter((item) =>
                ["organization", "role"].includes(item.payload.fact_type || ""),
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
        <div className="hero-actions">
          <a className="button ghost" href={`/graph?focal=${p.id}`}>
            관계 보기
          </a>
          <button className="button" onClick={() => setEditing(true)}>
            이름·별칭 편집
          </button>
          <button
            className="button primary"
            onClick={() => setAdding(true)}
            disabled={p.status !== "active"}
          >
            기억 추가
          </button>
        </div>
      </section>
      {notice && (
        <p className="notice" role="status">
          {notice}
        </p>
      )}
      <div className="filter-tabs" aria-label="인물 상세 보기">
        {[
          ["overview", "개요"],
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
            }}
          >
            {name}
          </button>
        ))}
      </div>
      <div className="detail-layout">
        <div className="stack">
          {tab === "overview" && (
            <section className="panel content-panel stack">
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
              {facts.loading ? (
                <Loading />
              ) : facts.error ? (
                <ErrorState error={facts.error} retry={facts.reload} />
              ) : (
                <div className="fact-grid">
                  {facts.data?.items.slice(0, 6).map((item) => (
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
                          })}
                        </p>
                      </a>
                      <span className="small muted">
                        {basisLabels[item.claim_basis]}
                      </span>
                    </div>
                  ))}
                </div>
              )}
              {!facts.loading && !facts.data?.total && !facts.error && (
                <p className="muted">등록된 프로필 정보가 없어요.</p>
              )}
            </section>
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
                        : "기억별 출처"}
                </h2>
                <a className="text-link" href={`/memories?person=${id}`}>
                  기억 전체 보기
                </a>
              </div>
              {tab === "sources" && (
                <p className="small muted">
                  이전·철회된 기억의 출처도 포함해 기억별로 보여드려요.
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
                        <MemoryCard item={item} />
                        {tab === "sources" && <SourceEvidence item={item} />}
                      </div>
                    ))}
                    {!records.data.total && (
                      <Empty>아직 이곳에 저장된 기억이 없어요.</Empty>
                    )}
                    <Pager page={records.data} onPage={setOffset} />
                  </>
                )
              )}
            </section>
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
                    {item.payload.directed ? "방향 있음 · " : ""}
                    {label(item.payload.relation_type || "")}
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
          onClose={() => setAdding(false)}
          onSaved={saved}
        />
      )}{" "}
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
