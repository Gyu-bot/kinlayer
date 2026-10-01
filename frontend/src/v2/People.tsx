import { type FormEvent, useEffect, useRef, useState } from "react";
import { request as api } from "../api/client";
import type { Entity } from "../types/entities";
import {
  apiDate,
  errorText,
  factText,
  label,
  type Ontology,
  type Page,
  type PersonSummary,
} from "./data";
import { Icon } from "./Icons";

export function relationLabel(value: string, ontology?: Ontology | null) {
  const translated = label(value);
  return translated !== value
    ? translated
    : ontology?.edge_types.find((item) => item.relation_type === value)
        ?.description || value;
}
function referenceDate(value: string | null) {
  if (!value) return "참조 기록 없음";
  const date = apiDate(value);
  return Number.isNaN(date.getTime())
    ? "시점 확인 필요"
    : new Intl.DateTimeFormat("ko-KR", {
        year: "numeric",
        month: "short",
        day: "numeric",
      }).format(date);
}
function Avatar({ name, large = false }: { name: string; large?: boolean }) {
  return (
    <span className={`avatar ${large ? "large" : ""}`} aria-hidden="true">
      {Array.from(name).slice(-2).join("")}
    </span>
  );
}
function FactLines({
  person,
  full = false,
}: {
  person: PersonSummary;
  full?: boolean;
}) {
  const facts = full ? person.profile_facts : person.profile_facts.slice(0, 2);
  return facts.length ? (
    <>
      {facts.map((fact) => (
        <div key={fact.id} className="person-fact-line">
          <span className="small muted">{label(fact.fact_type)} · </span>
          {factText(fact)}
          {fact.claim_basis === "inferred" && (
            <span className="pill warning">추론</span>
          )}
          {fact.claim_basis === "unknown" && (
            <span className="small muted"> · 근거 구분 미상</span>
          )}
        </div>
      ))}
    </>
  ) : (
    <span className="muted">프로필 기억 없음</span>
  );
}

export function People({ onNavigate }: { onNavigate: (path: string) => void }) {
  const [query, setQuery] = useState("");
  const [relation, setRelation] = useState("");
  const [sort, setSort] = useState("recent_reference");
  const [offset, setOffset] = useState(0);
  const [view, setView] = useState("list");
  const [page, setPage] = useState<Page<PersonSummary> | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [ontology, setOntology] = useState<Ontology | null>(null);
  const [ontologyError, setOntologyError] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  const [adding, setAdding] = useState(false);
  const search = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    api<Ontology>("/api/ontology", { signal: controller.signal })
      .then((result) => {
        if (active) {
          setOntology(result);
          setOntologyError(false);
        }
      })
      .catch(() => {
        if (active) setOntologyError(true);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [retry]);
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError(null);
    setPage(null);
    const params = new URLSearchParams({
      q: query.trim(),
      sort,
      limit: "25",
      offset: String(offset),
    });
    if (relation) params.set("relation_type", relation);
    api<Page<PersonSummary>>(`/api/people?${params}`, {
      signal: controller.signal,
    })
      .then((result) => {
        if (!active) return;
        setPage(result);
        setSelected((current) =>
          result.items.some((person) => person.id === current)
            ? current
            : result.items[0]?.id || null,
        );
      })
      .catch((reason) => {
        if (active) setError(errorText(reason));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [query, relation, sort, offset, retry]);
  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      if (
        event.key === "/" &&
        !(event.target as Element)?.closest(
          "input,textarea,select,dialog,[contenteditable=true]",
        )
      ) {
        event.preventDefault();
        search.current?.focus();
      }
    };
    document.addEventListener("keydown", shortcut);
    return () => document.removeEventListener("keydown", shortcut);
  }, []);
  const person = page?.items.find((item) => item.id === selected);
  const relations =
    ontology?.edge_types.filter((item) => item.active !== false) || [];
  function changeFilter(value: string) {
    setRelation(value);
    setOffset(0);
  }
  function openPerson(id: string) {
    onNavigate(`/people/${encodeURIComponent(id)}`);
  }
  function selectPerson(id: string) {
    if (window.matchMedia?.("(max-width:1030px)").matches) openPerson(id);
    else setSelected(id);
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="title-with-count">
            <h1>사람</h1>
            {page && <span>{page.total}</span>}
          </div>
          <p>소중한 사람들, 그리고 함께 쌓아온 맥락.</p>
        </div>
        <button className="button primary" onClick={() => setAdding(true)}>
          <Icon name="plus" />
          사람 추가
        </button>
      </div>
      <div className="people-layout">
        <section className="people-primary" aria-label="사람 목록">
          <div className="people-filters">
            <div className="filter-tabs" aria-label="자주 사용하는 관계 필터">
              <button
                className={`filter-tab ${!relation ? "active" : ""}`}
                aria-pressed={!relation}
                onClick={() => changeFilter("")}
              >
                모든 사람
              </button>
              {["coworker", "friend", "family"]
                .filter((value) =>
                  relations.some((item) => item.relation_type === value),
                )
                .map((value) => (
                  <button
                    key={value}
                    className={`filter-tab ${relation === value ? "active" : ""}`}
                    aria-pressed={relation === value}
                    onClick={() => changeFilter(value)}
                  >
                    {relationLabel(value, ontology)}
                  </button>
                ))}
            </div>
            <label className="screen-reader-only" htmlFor="people-relation">
              모든 관계 유형
            </label>
            <select
              id="people-relation"
              className="select relationship-select"
              value={relation}
              disabled={!ontology}
              onChange={(event) => changeFilter(event.target.value)}
            >
              <option value="">모든 관계 유형</option>
              {relations.map((item) => (
                <option key={item.relation_type} value={item.relation_type}>
                  {relationLabel(item.relation_type, ontology)}
                </option>
              ))}
            </select>
          </div>
          {ontologyError && (
            <p className="status-line" role="status">
              관계 유형을 불러오지 못했어요.{" "}
              <button
                className="text-link"
                onClick={() => setRetry((value) => value + 1)}
              >
                다시 시도
              </button>
            </p>
          )}
          <div className="list-toolbar">
            <label className="search-field">
              <Icon name="search" />
              <input
                ref={search}
                type="search"
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value);
                  setOffset(0);
                }}
                aria-label="이름이나 별칭으로 사람 검색"
                placeholder="이름이나 별칭으로 검색"
              />
              <kbd aria-hidden="true">/</kbd>
            </label>
            <div className="toolbar-end">
              <select
                className="select"
                aria-label="사람 정렬"
                value={sort}
                onChange={(event) => {
                  setSort(event.target.value);
                  setOffset(0);
                }}
              >
                <option value="recent_reference">최근 참조순</option>
                <option value="name">이름순</option>
              </select>
              <div className="view-toggle" aria-label="목록 보기 방식">
                <button
                  className={`icon-button ${view === "list" ? "active" : ""}`}
                  aria-label="목록 보기"
                  aria-pressed={view === "list"}
                  onClick={() => setView("list")}
                >
                  <Icon name="list" />
                </button>
                <button
                  className={`icon-button ${view === "cards" ? "active" : ""}`}
                  aria-label="카드 보기"
                  aria-pressed={view === "cards"}
                  onClick={() => setView("cards")}
                >
                  <Icon name="grid" />
                </button>
              </div>
            </div>
          </div>
          <div aria-live="polite" aria-busy={loading}>
            {loading ? (
              <div className="panel empty-state" role="status">
                사람을 불러오는 중이에요.
              </div>
            ) : error ? (
              <div className="panel empty-state" role="alert">
                <h2>사람 목록을 불러오지 못했어요</h2>
                <p>{error}</p>
                <button
                  className="button"
                  onClick={() => setRetry((value) => value + 1)}
                >
                  다시 시도
                </button>
              </div>
            ) : (
              <>
                <div
                  className={`people-table ${view === "cards" ? "cards" : ""}`}
                  role="list"
                  aria-label="등록된 사람"
                >
                  <div className="table-head" aria-hidden="true">
                    <span>이름 · 별칭</span>
                    <span>나와의 관계</span>
                    <span>프로필 기억</span>
                    <span>최근 참조</span>
                    <span />
                  </div>
                  {page?.items.length ? (
                    page.items.map((item) => (
                      <article
                        key={item.id}
                        className={`person-row ${item.id === selected ? "selected" : ""}`}
                        role="listitem"
                        tabIndex={0}
                        aria-label={`${item.display_name} 선택`}
                        onClick={(event) => {
                          if (!(event.target as Element).closest("a"))
                            selectPerson(item.id);
                        }}
                        onKeyDown={(event) => {
                          if (
                            event.target === event.currentTarget &&
                            ["Enter", " "].includes(event.key)
                          ) {
                            event.preventDefault();
                            selectPerson(item.id);
                          }
                        }}
                      >
                        <div className="person-identity">
                          <Avatar name={item.display_name} />
                          <div>
                            <a
                              className="person-name"
                              href={`/people/${encodeURIComponent(item.id)}`}
                              onClick={(event) => {
                                if (
                                  !event.ctrlKey &&
                                  !event.metaKey &&
                                  !event.shiftKey
                                ) {
                                  event.preventDefault();
                                  openPerson(item.id);
                                }
                              }}
                            >
                              {item.display_name}
                            </a>
                            <div className="person-alias">
                              {item.aliases.join(" · ") || "등록된 별칭 없음"}
                            </div>
                          </div>
                        </div>
                        <div className="relation-tags">
                          {item.relations.length ? (
                            item.relations.map((edge, index) => (
                              <span
                                className="relation-label"
                                key={`${edge.relation_type}-${index}`}
                                title={
                                  edge.directed
                                    ? `${edge.from_entity_id === item.id ? item.display_name : "나"} → ${edge.to_entity_id === item.id ? item.display_name : "나"}`
                                    : "방향 없는 관계"
                                }
                              >
                                {relationLabel(edge.relation_type, ontology)}
                                {edge.directed
                                  ? edge.to_entity_id === item.id
                                    ? " →"
                                    : " ←"
                                  : ""}
                              </span>
                            ))
                          ) : (
                            <span className="muted small">연결 없음</span>
                          )}
                        </div>
                        <div className="person-org">
                          <FactLines person={item} />
                        </div>
                        <time
                          className="referenced"
                          dateTime={item.last_referenced_at || undefined}
                        >
                          {referenceDate(item.last_referenced_at)}
                        </time>
                        <a
                          href={`/people/${encodeURIComponent(item.id)}`}
                          className="row-open"
                          aria-label={`${item.display_name} 상세 보기`}
                          onClick={(event) => {
                            event.preventDefault();
                            openPerson(item.id);
                          }}
                        >
                          <Icon name="chevron" />
                        </a>
                      </article>
                    ))
                  ) : (
                    <div className="empty-state">
                      <Icon name="search" />
                      <h3>
                        {query || relation
                          ? "일치하는 사람이 없어요"
                          : "아직 등록된 사람이 없어요"}
                      </h3>
                      <p>
                        {query || relation
                          ? "다른 이름이나 별칭, 관계로 찾아보세요."
                          : "기억하고 싶은 사람을 추가해 보세요."}
                      </p>
                      {(query || relation) && (
                        <button
                          className="text-link"
                          onClick={() => {
                            setQuery("");
                            changeFilter("");
                          }}
                        >
                          검색과 필터 초기화
                        </button>
                      )}
                    </div>
                  )}
                </div>
                {page && (
                  <div className="table-footer">
                    <span>
                      {page.total}명 중{" "}
                      {page.items.length
                        ? `${offset + 1}–${offset + page.items.length}`
                        : "0"}
                      명 표시
                    </span>
                    <span>
                      <Icon name="clock" />
                      실제 기록된 참조 시점
                    </span>
                  </div>
                )}
                {page && page.total > page.limit && (
                  <nav className="pagination" aria-label="사람 목록 페이지">
                    <button
                      className="button"
                      disabled={offset === 0}
                      onClick={() =>
                        setOffset((value) => Math.max(0, value - page.limit))
                      }
                    >
                      이전
                    </button>
                    <span>
                      {Math.floor(offset / page.limit) + 1} /{" "}
                      {Math.ceil(page.total / page.limit)}
                    </span>
                    <button
                      className="button"
                      disabled={offset + page.limit >= page.total}
                      onClick={() => setOffset((value) => value + page.limit)}
                    >
                      다음
                    </button>
                  </nav>
                )}
              </>
            )}
          </div>
        </section>
        <aside className="people-rail" aria-label="선택한 인물 미리보기">
          {person && !loading ? (
            <section className="panel preview-panel">
              <div className="panel-kicker">
                <span>인물 미리보기</span>
                <Icon name="people" />
              </div>
              <div className="preview-body">
                <Avatar name={person.display_name} large />
                <div className="preview-name">
                  <h2>{person.display_name}</h2>
                </div>
                <p className="preview-subtitle">
                  {person.relations
                    .map((item) => relationLabel(item.relation_type, ontology))
                    .join(" · ") || "아직 등록된 관계 없음"}
                </p>
                <dl className="mini-facts">
                  <div>
                    <dt>별칭</dt>
                    <dd>{person.aliases.join(", ") || "등록되지 않음"}</dd>
                  </div>
                  <div>
                    <dt>최근 참조</dt>
                    <dd>{referenceDate(person.last_referenced_at)}</dd>
                  </div>
                </dl>
                <div className="preview-section">
                  <span className="eyebrow">프로필 기억</span>
                  <FactLines person={person} full />
                  <div className="source-caption">
                    <Icon name="source" />
                    {person.memory_count}개의 기억
                  </div>
                </div>
              </div>
              <div className="preview-actions">
                <button
                  className="button"
                  onClick={() => openPerson(person.id)}
                >
                  프로필 보기
                  <Icon name="arrow" />
                </button>
                <button
                  className="button ghost"
                  onClick={() =>
                    onNavigate(`/graph?focal=${encodeURIComponent(person.id)}`)
                  }
                >
                  관계 그래프로 보기
                  <Icon name="external" />
                </button>
              </div>
            </section>
          ) : (
            <section className="panel empty-state">
              <p>
                {loading
                  ? "사람을 불러오는 중이에요."
                  : "목록에서 인물을 선택하면 저장된 맥락을 확인할 수 있어요."}
              </p>
            </section>
          )}
          <p className="rail-footnote">
            <Icon name="info" />
            기억의 내용과 출처는 인물 상세에서
            <br />
            확인하고 바로잡을 수 있어요.
          </p>
        </aside>
      </div>
      {adding && (
        <NewPersonDialog
          onClose={() => setAdding(false)}
          onCreated={(entity) =>
            onNavigate(`/people/${encodeURIComponent(entity.id)}`)
          }
        />
      )}
    </>
  );
}

function NewPersonDialog({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (person: Entity) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    const previous = document.activeElement as HTMLElement | null;
    dialog.current?.showModal();
    input.current?.focus();
    return () => {
      mounted.current = false;
      previous?.focus();
    };
  }, []);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    if (!name.trim()) {
      setError("이름을 입력해 주세요.");
      input.current?.focus();
      return;
    }
    setBusy(true);
    setError("");
    try {
      const result = await api<Entity>("/api/entities", {
        method: "POST",
        body: JSON.stringify({
          entity_type: "person",
          display_name: name.trim(),
          created_by: "user",
        }),
      });
      if (mounted.current) onCreated(result);
    } catch (reason) {
      if (mounted.current) setError(errorText(reason));
    } finally {
      if (mounted.current) setBusy(false);
    }
  }
  return (
    <dialog
      ref={dialog}
      className="modal"
      aria-labelledby="new-person-title"
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) onClose();
      }}
    >
      <div className="modal-header">
        <h2 id="new-person-title">새로운 사람 추가</h2>
        <button
          className="icon-button"
          aria-label="창 닫기"
          disabled={busy}
          onClick={onClose}
        >
          <Icon name="close" />
        </button>
      </div>
      <form onSubmit={submit} noValidate>
        <div className="modal-body">
          <p className="modal-intro">
            이름으로 사람을 등록해요. 별칭과 프로필 기억은 인물 화면에서 이어서
            추가할 수 있어요.
          </p>
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          <div className="field">
            <label htmlFor="new-person-name">
              이름 <span aria-hidden="true">*</span>
            </label>
            <input
              ref={input}
              id="new-person-name"
              required
              maxLength={120}
              autoComplete="off"
              value={name}
              onChange={(event) => setName(event.target.value)}
              disabled={busy}
            />
          </div>
        </div>
        <div className="modal-footer">
          <button
            type="button"
            className="button ghost"
            disabled={busy}
            onClick={onClose}
          >
            취소
          </button>
          <button className="button primary" type="submit" disabled={busy}>
            {busy ? "저장 중…" : "사람 추가"}
          </button>
        </div>
      </form>
    </dialog>
  );
}
