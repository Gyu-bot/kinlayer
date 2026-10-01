import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";

import {
  ApiError,
  apiUrl,
  clearLocalApiToken,
  exportAgentOperations,
  isLocalApiTokenConfigured,
  request,
  setLocalApiToken,
} from "../api/client";
import type {
  AgentOperationFilters,
  AgentWriteOperation,
} from "../types/agentOperations";
import type { Candidate } from "../types/candidates";
import type {
  EmbeddingStatus,
  SystemConfig,
  SystemHealth,
} from "../types/entities";
import { apiDate, basisLabels, label } from "./data";

type Navigation = { onNavigate?: (path: string) => void };
type Page<T> = { items: T[]; total: number; limit: number; offset: number };
type PersonOption = { id: string; display_name: string };
type Basis = "reported" | "inferred" | "unknown";
type Fact = {
  id: string;
  fact_type: string;
  content: string;
  claim_basis: Basis;
  confidence: number;
  value?: {
    year?: number | null;
    month?: number | null;
    day?: number | null;
    precision?: string;
  } | null;
  valid_from?: string | null;
  valid_to?: string | null;
};
type Observation = {
  observation_id: string;
  subject_entity_id: string;
  observation_type: string;
  content: string;
  claim_basis: Basis;
  confidence: number;
  status: string;
  score: number;
  valid_from?: string | null;
  valid_to?: string | null;
  occurred_at?: string | null;
  related_entities: { entity_id: string; role: string }[];
};
type Match = {
  entity_id: string;
  display_name: string;
  score: number;
  confidence_band: string;
  match_reasons: string[];
  profile_facts: Fact[];
  observations: Observation[];
};
type Provenance = {
  record_type: string;
  record_id: string;
  episode_id?: string | null;
  source_type?: string | null;
  source_ref?: string | null;
  excerpt?: string | null;
  source_occurred_at?: string | null;
};
type Retrieve = {
  matched_entities: Match[];
  observations: Observation[];
  provenance: Provenance[];
  ambiguity_detected: boolean;
  debug: Record<string, unknown>;
  score_breakdown: Record<string, unknown>;
};
type Pack = {
  context_pack: {
    matched_entities: Match[];
    recent_context: Observation[];
    stable_context: Observation[];
    cautions: Observation[];
    provenance: Provenance[];
    ambiguity_detected: boolean;
    confidence: string;
  };
  debug: Record<string, unknown>;
};

const statusLabels: Record<string, string> = {
  ok: "정상",
  degraded: "일부 연결 오류",
  ready: "준비됨",
  configured: "설정됨",
  disabled: "사용 안 함",
  misconfigured: "설정 확인 필요",
  unsupported: "지원하지 않음",
  pending: "대기",
  accepted: "반영됨",
  rejected: "거절됨",
  archived: "보관됨",
  needs_clarification: "추가 확인",
  success: "성공",
  active: "활성",
  edited_accepted: "수정 후 반영됨",
  superseded: "후속 기록으로 대체됨",
};
const operationLabels: Record<string, string> = {
  candidate_submit: "과거 후보 제출",
  candidate_accept: "과거 후보 반영",
  candidate_edit_accept: "과거 후보 수정·반영",
  correction_apply: "정정 반영",
  edge_create: "관계 생성",
  edge_update: "관계 수정",
};
const candidateLabels: Record<string, string> = {
  new_entity: "인물",
  alias: "별칭",
  profile_field: "프로필",
  relationship_edge: "관계",
  observation: "맥락",
  merge: "인물 병합",
  conflict: "상충 정보",
  supersede: "기존 기록 대체",
};

function errorMessage(error: unknown) {
  if (
    error instanceof ApiError &&
    (error.status === 401 || error.status === 403)
  ) {
    return "연결 인증을 확인해 주세요. 설정에서 API 토큰을 저장하거나 갱신할 수 있습니다.";
  }
  return error instanceof Error
    ? error.message
    : "요청을 완료하지 못했습니다. 연결 상태를 확인하고 다시 시도해 주세요.";
}

function Notice({
  children,
  error = false,
}: {
  children: ReactNode;
  error?: boolean;
}) {
  return (
    <p
      className={error ? "notice error" : "notice"}
      role={error ? "alert" : "status"}
    >
      {children}
    </p>
  );
}

function Link({
  path,
  onNavigate,
  children,
}: Navigation & { path: string; children: ReactNode }) {
  return (
    <a
      className="text-link"
      href={path}
      onClick={
        onNavigate
          ? (event) => {
              if (
                event.button !== 0 ||
                event.metaKey ||
                event.ctrlKey ||
                event.shiftKey ||
                event.altKey
              )
                return;
              event.preventDefault();
              onNavigate(path);
            }
          : undefined
      }
    >
      {children}
    </a>
  );
}

function recordRef(type: string, id: string) {
  const prefixes: Record<string, string> = {
    fact: "entity_facts",
    entity_fact: "entity_facts",
    edge: "entity_edges",
    entity_edge: "entity_edges",
    observation: "observations",
  };
  return `${prefixes[type] ?? type}:${id}`;
}

function MemoryLink({
  reference,
  ownerId,
  onNavigate,
}: Navigation & { reference: string; ownerId?: string | null }) {
  const match =
    /^(entity_facts|entity_edges|observations|entities|entity_aliases):([^:\s]+)$/.exec(
      reference,
    );
  if (
    match &&
    ["entity_facts", "entity_edges", "observations"].includes(match[1])
  ) {
    return (
      <Link
        path={`/memories?record=${encodeURIComponent(reference)}`}
        onNavigate={onNavigate}
      >
        기억 보기
      </Link>
    );
  }
  if (match?.[1] === "entities") {
    return (
      <Link
        path={`/people/${encodeURIComponent(match[2])}`}
        onNavigate={onNavigate}
      >
        인물 보기
      </Link>
    );
  }
  if (match?.[1] === "entity_aliases" && ownerId) {
    return (
      <Link
        path={`/people/${encodeURIComponent(ownerId)}`}
        onNavigate={onNavigate}
      >
        별칭의 인물 보기
      </Link>
    );
  }
  return (
    <details className="diagnostic-details">
      <summary>과거 기록 식별자</summary>
      <code>{reference}</code>
    </details>
  );
}

function dateText(value?: string | null) {
  if (!value) return "기록 없음";
  const date = apiDate(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString("ko-KR");
}

function safeDiagnostics(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(safeDiagnostics);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value)
        .filter(
          ([key]) =>
            ![
              "ai_use_policy",
              "confirmation_status",
              "sensitivity",
              "effective_sensitivity",
              "surface_bucket",
              "buckets",
              "suggested_response_policy",
            ].includes(key),
        )
        .map(([key, item]) => [key, safeDiagnostics(item)]),
    );
  }
  return value;
}

function JsonDetails({ title, value }: { title: string; value: unknown }) {
  return (
    <details className="diagnostic-details">
      <summary>{title}</summary>
      <pre>{JSON.stringify(safeDiagnostics(value), null, 2)}</pre>
    </details>
  );
}

function Pagination({
  offset,
  limit,
  total,
  busy,
  onChange,
}: {
  offset: number;
  limit: number;
  total: number;
  busy: boolean;
  onChange: (offset: number) => void;
}) {
  return (
    <div className="toolbar pagination" aria-label="페이지 이동">
      <span className="muted small">
        {total
          ? `${offset + 1}–${Math.min(offset + limit, total)} / ${total}건`
          : "0건"}
      </span>
      <button
        className="button small-button"
        type="button"
        disabled={busy || offset === 0}
        onClick={() => onChange(Math.max(0, offset - limit))}
      >
        이전
      </button>
      <button
        className="button small-button"
        type="button"
        disabled={busy || offset + limit >= total}
        onClick={() => onChange(offset + limit)}
      >
        다음
      </button>
    </div>
  );
}

export function Settings({ onNavigate }: Navigation) {
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [config, setConfig] = useState<SystemConfig | null>(null);
  const [embedding, setEmbedding] = useState<EmbeddingStatus | null>(null);
  const [token, setToken] = useState("");
  const [hasToken, setHasToken] = useState(isLocalApiTokenConfigured);
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const [message, setMessage] = useState("");
  const generation = useRef(0);

  async function refresh() {
    const current = ++generation.current;
    setBusy(true);
    setErrors([]);
    setHealth(null);
    setConfig(null);
    setEmbedding(null);
    const results = await Promise.allSettled([
      request<SystemHealth>("/api/system/health"),
      request<SystemConfig>("/api/system/config"),
      request<EmbeddingStatus>("/api/embeddings/status"),
    ]);
    if (current !== generation.current) return;
    const [healthResult, configResult, embeddingResult] = results;
    if (healthResult.status === "fulfilled") setHealth(healthResult.value);
    if (configResult.status === "fulfilled") setConfig(configResult.value);
    if (embeddingResult.status === "fulfilled")
      setEmbedding(embeddingResult.value);
    setErrors([
      ...new Set(
        results.flatMap((result) =>
          result.status === "rejected" ? [errorMessage(result.reason)] : [],
        ),
      ),
    ]);
    setBusy(false);
  }
  useEffect(() => {
    void refresh();
    return () => {
      generation.current++;
    };
  }, []);

  function saveToken(event: FormEvent) {
    event.preventDefault();
    if (!token.trim()) {
      setMessage("저장할 토큰을 입력해 주세요.");
      return;
    }
    try {
      setLocalApiToken(token);
      setToken("");
      setHasToken(isLocalApiTokenConfigured());
      setMessage("이 브라우저에 토큰을 저장했습니다. 연결을 다시 확인합니다.");
      void refresh();
    } catch {
      setMessage(
        "브라우저 저장소에 접근하지 못했습니다. 저장소 권한을 확인해 주세요.",
      );
    }
  }
  function removeToken() {
    try {
      clearLocalApiToken();
      setToken("");
      setHasToken(false);
      setMessage(
        "이 브라우저의 토큰을 삭제했습니다. 서버 토큰은 변경되지 않습니다.",
      );
      void refresh();
    } catch {
      setMessage(
        "토큰을 삭제하지 못했습니다. 브라우저 저장소 권한을 확인해 주세요.",
      );
    }
  }
  const embeddingConfig = config?.embedding ?? embedding;
  return (
    <section className="support-page stack" aria-labelledby="settings-title">
      <header className="page-heading">
        <div>
          <h1 id="settings-title">설정</h1>
          <p>연결과 검색 준비 상태를 확인합니다.</p>
        </div>
        <button
          className="button"
          onClick={() => void refresh()}
          disabled={busy}
        >
          {busy ? "확인 중…" : "연결 다시 확인"}
        </button>
      </header>
      {errors.map((error) => (
        <Notice error key={error}>
          {error}
        </Notice>
      ))}
      {message && <Notice>{message}</Notice>}
      <div className="support-grid">
        <section
          className="panel content-panel stack"
          aria-labelledby="connection-title"
        >
          <h2 id="connection-title">API 연결</h2>
          <dl className="support-facts">
            <div>
              <dt>서버 주소</dt>
              <dd>{apiUrl}</dd>
            </div>
            <div>
              <dt>서비스</dt>
              <dd>
                {health
                  ? (statusLabels[health.status] ?? health.status)
                  : busy
                    ? "확인 중"
                    : "확인하지 못함"}
              </dd>
            </div>
            <div>
              <dt>데이터베이스</dt>
              <dd>
                {health
                  ? (statusLabels[health.database] ?? health.database)
                  : "확인하지 못함"}
              </dd>
            </div>
            <div>
              <dt>서버 인증</dt>
              <dd>
                {config
                  ? config.auth_token_configured
                    ? "토큰 필요"
                    : "토큰 불필요"
                  : "확인하지 못함"}
              </dd>
            </div>
            <div>
              <dt>브라우저 토큰</dt>
              <dd>{hasToken ? "저장됨" : "저장된 토큰 없음"}</dd>
            </div>
          </dl>
          <form className="stack" onSubmit={saveToken}>
            <label className="field">
              <span>API 토큰</span>
              <input
                type="password"
                value={token}
                onChange={(event) => setToken(event.target.value)}
                autoComplete="off"
                spellCheck={false}
                placeholder="새 토큰 입력"
              />
            </label>
            <p className="muted small">
              입력한 토큰은 이 브라우저에만 저장하며 저장된 값을 다시 표시하지
              않습니다.
            </p>
            <div className="toolbar">
              <button
                className="button primary"
                type="submit"
                disabled={!token.trim() || busy}
              >
                토큰 저장
              </button>
              <button
                className="button"
                type="button"
                disabled={!hasToken || busy}
                onClick={removeToken}
              >
                토큰 삭제
              </button>
            </div>
          </form>
          <details className="diagnostic-details">
            <summary>서버 주소 설정 방법</summary>
            <p className="muted small">
              서버 주소는 배포 시 VITE_KINLAYER_API_URL 설정으로 지정됩니다.
              설정이 없으면 현재 브라우저 호스트의 8765 포트를 사용합니다.
            </p>
          </details>
        </section>
        <section
          className="panel content-panel stack"
          aria-labelledby="embedding-title"
        >
          <h2 id="embedding-title">의미 검색 준비 상태</h2>
          <p className="muted">
            서버의 연결 설정과 실제 생성된 검색 데이터는 별도로 확인합니다.
          </p>
          <dl className="support-facts">
            <div>
              <dt>제공 방식</dt>
              <dd>
                {embeddingConfig?.provider === "disabled"
                  ? "사용 안 함"
                  : (embeddingConfig?.provider ?? "확인하지 못함")}
              </dd>
            </div>
            <div>
              <dt>모델</dt>
              <dd>
                {embeddingConfig
                  ? (embeddingConfig.model ?? "설정 없음")
                  : "확인하지 못함"}
              </dd>
            </div>
            <div>
              <dt>차원</dt>
              <dd>
                {embeddingConfig
                  ? (embeddingConfig.dim ?? "설정 없음")
                  : "확인하지 못함"}
              </dd>
            </div>
            <div>
              <dt>서버 설정 상태</dt>
              <dd>
                {embeddingConfig
                  ? (statusLabels[embeddingConfig.status] ??
                    embeddingConfig.status)
                  : "확인하지 못함"}
              </dd>
            </div>
            <div>
              <dt>검색 API 주소</dt>
              <dd>
                {embeddingConfig
                  ? embeddingConfig.api_url_configured
                    ? "설정됨"
                    : "설정 없음"
                  : "확인하지 못함"}
              </dd>
            </div>
            <div>
              <dt>검색 API 키</dt>
              <dd>
                {embeddingConfig
                  ? embeddingConfig.api_key_configured
                    ? "설정됨"
                    : "설정 없음"
                  : "확인하지 못함"}
              </dd>
            </div>
          </dl>
          <h3>관찰 데이터 처리 현황</h3>
          {embedding ? (
            <>
              <dl className="support-facts">
                <div>
                  <dt>전체</dt>
                  <dd>{embedding.observations.total}건</dd>
                </div>
                <div>
                  <dt>검색 준비됨</dt>
                  <dd>{embedding.observations.ready}건</dd>
                </div>
                <div>
                  <dt>대기</dt>
                  <dd>{embedding.observations.pending}건</dd>
                </div>
                <div>
                  <dt>실패</dt>
                  <dd>{embedding.observations.failed}건</dd>
                </div>
                <div>
                  <dt>갱신 필요</dt>
                  <dd>{embedding.observations.stale}건</dd>
                </div>
              </dl>
              <p className="muted small">
                설정 상태가 준비됨이어도 실제 검색 데이터가 준비되었다는 뜻은
                아닙니다.
              </p>
            </>
          ) : (
            <p className="muted">처리 현황을 확인하지 못했습니다.</p>
          )}
          <Link path="/search" onNavigate={onNavigate}>
            검색 결과 확인
          </Link>
        </section>
      </div>
    </section>
  );
}

function BasisDetails({ item }: { item: Fact | Observation }) {
  const date = "value" in item ? item.value : null;
  const partialDate = date?.precision
    ? [
        date.year == null ? "연도 미상" : `${date.year}년`,
        date.month == null ? null : `${date.month}월`,
        date.day == null ? null : `${date.day}일`,
      ]
        .filter(Boolean)
        .join(" ")
    : null;
  return (
    <div className="stack compact-stack">
      <div className="toolbar">
        <span
          className={`pill${item.claim_basis === "inferred" ? " warning" : ""}`}
        >
          {basisLabels[item.claim_basis] ?? basisLabels.unknown}
        </span>
        <span className="muted small">
          기록 신뢰도 {Math.round(item.confidence * 100)}% · 사실 확정을 뜻하지
          않음
        </span>
      </div>
      {partialDate && (
        <p className="muted small">
          날짜: {partialDate} ·{" "}
          {date?.precision === "year"
            ? "연도까지만 기록"
            : date?.precision === "month"
              ? "월까지만 기록"
              : "일 단위 기록"}
        </p>
      )}
      {(item.valid_from || item.valid_to) && (
        <p className="muted small">
          유효 기간: {item.valid_from ? dateText(item.valid_from) : "시작 미상"}{" "}
          ~ {item.valid_to ? dateText(item.valid_to) : "종료 미상"}
        </p>
      )}
      {"occurred_at" in item && item.occurred_at && (
        <p className="muted small">사건 시점: {dateText(item.occurred_at)}</p>
      )}
    </div>
  );
}

function Sources({
  reference,
  provenance,
  onNavigate,
}: Navigation & { reference: string; provenance: Provenance[] }) {
  const matching = provenance.filter(
    (source) => recordRef(source.record_type, source.record_id) === reference,
  );
  return (
    <div className="stack compact-stack">
      <MemoryLink reference={reference} onNavigate={onNavigate} />
      {matching.map((source, index) => (
        <div className="source-snippet" key={`${source.episode_id}-${index}`}>
          {source.excerpt && <blockquote>{source.excerpt}</blockquote>}
          <div className="toolbar">
            {source.episode_id ? (
              <Link
                path={`/sources/${encodeURIComponent(source.episode_id)}`}
                onNavigate={onNavigate}
              >
                출처 보기
              </Link>
            ) : (
              <span className="muted small">연결된 출처 없음</span>
            )}
            {source.source_occurred_at && (
              <span className="muted small">
                출처 시점: {dateText(source.source_occurred_at)}
              </span>
            )}
          </div>
        </div>
      ))}
      {!matching.length && (
        <p className="muted small">
          이 검색 응답에 연결된 출처가 없습니다. 기억 상세에서 확인하세요.
        </p>
      )}
    </div>
  );
}

function ObservationResult({
  item,
  provenance,
  onNavigate,
}: Navigation & { item: Observation; provenance: Provenance[] }) {
  return (
    <article className="search-record stack compact-stack">
      <span className="muted small">{label(item.observation_type)}</span>
      <p>{item.content}</p>
      <BasisDetails item={item} />
      {item.related_entities?.length > 0 && (
        <div className="toolbar">
          {item.related_entities.map((participant, index) => (
            <Link
              key={`${participant.entity_id}:${participant.role}:${index}`}
              path={`/people/${encodeURIComponent(participant.entity_id)}`}
              onNavigate={onNavigate}
            >
              {label(participant.role)} 보기
            </Link>
          ))}
        </div>
      )}
      <Sources
        reference={recordRef("observation", item.observation_id)}
        provenance={provenance}
        onNavigate={onNavigate}
      />
    </article>
  );
}

export function Search({ onNavigate }: Navigation) {
  const [query, setQuery] = useState("");
  const [situation, setSituation] = useState("");
  const [personQuery, setPersonQuery] = useState("");
  const [personFilter, setPersonFilter] = useState("");
  const [offset, setOffset] = useState(0);
  const [people, setPeople] = useState<Page<PersonOption> | null>(null);
  const [person, setPerson] = useState<PersonOption | null>(null);
  const [peopleBusy, setPeopleBusy] = useState(false);
  const [peopleError, setPeopleError] = useState("");
  const [errors, setErrors] = useState<string[]>([]);
  const [result, setResult] = useState<Retrieve | null>(null);
  const [pack, setPack] = useState<Pack | null>(null);
  const [busy, setBusy] = useState(false);
  const generation = useRef(0);

  useEffect(() => {
    const controller = new AbortController();
    setPeopleBusy(true);
    setPeopleError("");
    const params = new URLSearchParams({
      entity_type: "person",
      status: "active",
      limit: "20",
      offset: String(offset),
    });
    if (personFilter.trim()) params.set("q", personFilter.trim());
    request<Page<PersonOption>>(`/api/entities?${params}`, {
      signal: controller.signal,
    })
      .then((value) => {
        if (!controller.signal.aborted) setPeople(value);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setPeople(null);
          setPeopleError(errorMessage(error));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setPeopleBusy(false);
      });
    return () => controller.abort();
  }, [personFilter, offset]);
  useEffect(
    () => () => {
      generation.current++;
    },
    [],
  );

  async function run(event: FormEvent) {
    event.preventDefault();
    if (!query.trim()) {
      setErrors(["찾을 내용을 입력해 주세요."]);
      return;
    }
    const current = ++generation.current;
    setBusy(true);
    setErrors([]);
    setResult(null);
    setPack(null);
    const payload = {
      query: query.trim(),
      entity_hints: [],
      ...(person ? { focal_entity_id: person.id } : {}),
      include_debug: true,
      limit: 10,
    };
    const responses = await Promise.allSettled([
      request<Retrieve>("/api/context/retrieve", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
      request<Pack>("/api/context/pack", {
        method: "POST",
        body: JSON.stringify({
          ...payload,
          ...(situation.trim() ? { situation: situation.trim() } : {}),
        }),
      }),
    ]);
    if (current !== generation.current) return;
    if (responses[0].status === "fulfilled") setResult(responses[0].value);
    if (responses[1].status === "fulfilled") setPack(responses[1].value);
    setErrors(
      responses.flatMap((response, index) =>
        response.status === "rejected"
          ? [
              `${index ? "상황별 맥락" : "기억 검색"}: ${errorMessage(response.reason)}`,
            ]
          : [],
      ),
    );
    setBusy(false);
  }
  const provenance = [
    ...new Map(
      [
        ...(result?.provenance ?? []),
        ...(pack?.context_pack.provenance ?? []),
      ].map((source) => [
        `${source.record_type}:${source.record_id}:${source.episode_id}:${source.excerpt}`,
        source,
      ]),
    ).values(),
  ];
  const matchedObservations = new Set(
    result?.matched_entities.flatMap((match) =>
      match.observations.map((item) => item.observation_id),
    ) ?? [],
  );
  return (
    <section className="support-page stack" aria-labelledby="search-title">
      <header className="page-heading">
        <div>
          <h1 id="search-title">검색</h1>
          <p>사람과 상황에 맞는 기억을 찾고, 근거와 원래 기록을 확인합니다.</p>
        </div>
      </header>
      <section className="panel content-panel stack" aria-label="검색 조건">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            setOffset(0);
            setPersonFilter(personQuery.trim());
          }}
          className="toolbar person-search-form"
        >
          <label className="field">
            <span>관련 인물 찾기</span>
            <input
              value={personQuery}
              onChange={(event) => setPersonQuery(event.target.value)}
              placeholder="이름 또는 별칭"
            />
          </label>
          <button className="button" type="submit">
            인물 검색
          </button>
        </form>
        {peopleError && <Notice error>{peopleError}</Notice>}
        <label className="field">
          <span>중심 인물 (선택)</span>
          <select
            value={person?.id ?? ""}
            disabled={peopleBusy}
            onChange={(event) =>
              setPerson(
                people?.items.find((item) => item.id === event.target.value) ??
                  null,
              )
            }
          >
            <option value="">지정하지 않음</option>
            {person && !people?.items.some((item) => item.id === person.id) && (
              <option value={person.id}>{person.display_name} · 선택됨</option>
            )}
            {people?.items.map((item) => (
              <option key={item.id} value={item.id}>
                {item.display_name}
              </option>
            ))}
          </select>
        </label>
        {people && (
          <Pagination
            offset={offset}
            limit={20}
            total={people.total}
            busy={peopleBusy}
            onChange={setOffset}
          />
        )}
        <form className="stack" onSubmit={(event) => void run(event)}>
          <label className="field">
            <span>찾을 내용</span>
            <textarea
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              rows={3}
              placeholder="예: 다음 만남 전에 알아둘 내용"
              required
            />
          </label>
          <label className="field">
            <span>현재 상황 (선택)</span>
            <input
              value={situation}
              onChange={(event) => setSituation(event.target.value)}
              placeholder="예: 함께 진행할 프로젝트를 논의하려고 해요"
            />
          </label>
          <div>
            <button type="submit" className="button primary" disabled={busy}>
              {busy ? "검색 중…" : "기억 검색"}
            </button>
          </div>
        </form>
      </section>
      {errors.map((error) => (
        <Notice error key={error}>
          {error}
        </Notice>
      ))}
      {(result?.ambiguity_detected ||
        pack?.context_pack.ambiguity_detected) && (
        <Notice>
          여러 인물이나 해석이 겹칩니다. 인물과 출처를 확인한 뒤 내용을
          사용하세요.
        </Notice>
      )}
      {result && (
        <section
          className="panel content-panel stack"
          aria-labelledby="matches-title"
        >
          <h2 id="matches-title">검색된 사람과 기억</h2>
          {!result.matched_entities.length && !result.observations.length && (
            <p className="empty-state">
              조건에 맞는 기억이 없습니다. 이름이나 찾을 내용을 바꿔보세요.
            </p>
          )}
          {result.matched_entities.map((match) => (
            <article className="search-match stack" key={match.entity_id}>
              <div className="toolbar">
                <h3>{match.display_name}</h3>
                <Link
                  path={`/people/${encodeURIComponent(match.entity_id)}`}
                  onNavigate={onNavigate}
                >
                  인물 보기
                </Link>
                <span className="muted small">
                  검색 일치도 {match.score.toFixed(2)}
                </span>
              </div>
              {match.profile_facts.map((fact) => (
                <article
                  key={fact.id}
                  className="search-record stack compact-stack"
                >
                  <span className="muted small">{label(fact.fact_type)}</span>
                  <p>{fact.content}</p>
                  <BasisDetails item={fact} />
                  <Sources
                    reference={recordRef("fact", fact.id)}
                    provenance={provenance}
                    onNavigate={onNavigate}
                  />
                </article>
              ))}
              {match.observations.map((item) => (
                <ObservationResult
                  key={item.observation_id}
                  item={item}
                  provenance={provenance}
                  onNavigate={onNavigate}
                />
              ))}
              {!match.profile_facts.length && !match.observations.length && (
                <p className="muted">이 인물에 연결된 검색 결과가 없습니다.</p>
              )}
            </article>
          ))}
          {result.observations
            .filter((item) => !matchedObservations.has(item.observation_id))
            .map((item) => (
              <ObservationResult
                key={item.observation_id}
                item={item}
                provenance={provenance}
                onNavigate={onNavigate}
              />
            ))}
        </section>
      )}
      {pack && (
        <section
          className="panel content-panel stack"
          aria-labelledby="pack-title"
        >
          <h2 id="pack-title">상황에 맞춘 맥락</h2>
          <p className="muted small">
            현재 상황을 반영한 검색 결과입니다. 각 기록의 근거와 유효 기간은
            그대로 유지됩니다.
          </p>
          {(
            [
              ["recent_context", "최근 맥락"],
              ["stable_context", "지속되는 맥락"],
              ["cautions", "유의할 맥락"],
            ] as const
          ).map(([key, label]) => (
            <section className="stack compact-stack" key={key}>
              <h3>{label}</h3>
              {pack.context_pack[key].length ? (
                pack.context_pack[key].map((item) => (
                  <ObservationResult
                    key={item.observation_id}
                    item={item}
                    provenance={provenance}
                    onNavigate={onNavigate}
                  />
                ))
              ) : (
                <p className="muted small">해당하는 기억이 없습니다.</p>
              )}
            </section>
          ))}
        </section>
      )}
      {(result || pack) && (
        <section className="panel content-panel">
          <JsonDetails
            title="검색 진단 정보"
            value={{
              retrieval: result?.debug,
              score_breakdown: result?.score_breakdown,
              context: pack?.debug,
            }}
          />
        </section>
      )}
    </section>
  );
}

const initialOperationFilters: AgentOperationFilters = {
  actor: "",
  source_path: "",
  operation_type: "all",
  result_status: "all",
  has_error: "all",
  created_from: "",
  created_to: "",
};
function operationParams(filters: AgentOperationFilters, offset: number) {
  const params = new URLSearchParams({ limit: "25", offset: String(offset) });
  for (const [key, value] of Object.entries(filters))
    if (value.trim() && value !== "all") params.set(key, value.trim());
  return params;
}
function normalizedFilters(filters: AgentOperationFilters) {
  return {
    ...filters,
    created_from: filters.created_from
      ? new Date(filters.created_from).toISOString()
      : "",
    created_to: filters.created_to
      ? new Date(filters.created_to).toISOString()
      : "",
  };
}

function download(content: string, filename: string, type: string) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  // Give the browser time to start reading the generated file.
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function operationsCsv(items: AgentWriteOperation[]) {
  const keys = [
    "created_at",
    "operation_type",
    "result_status",
    "actor",
    "source_path",
    "api_error_code",
    "canonical_record_ref",
    "candidate_id",
    "episode_id",
    "bounded_excerpt",
  ] as const;
  const cell = (value: unknown) => {
    let text = value == null ? "" : String(value);
    if (/^[\s]*[=+\-@]/.test(text)) text = `'${text}`;
    return `"${text.replace(/"/g, '""')}"`;
  };
  return `\uFEFF${[keys.map(cell).join(","), ...items.map((item) => keys.map((key) => cell(item[key])).join(","))].join("\r\n")}\r\n`;
}

export function Diagnostics({ onNavigate }: Navigation) {
  const [tab, setTab] = useState<"operations" | "candidates">("operations");
  const [draft, setDraft] = useState(initialOperationFilters);
  const [filters, setFilters] = useState(initialOperationFilters);
  const [candidateStatus, setCandidateStatus] = useState("");
  const [candidateType, setCandidateType] = useState("");
  const [offset, setOffset] = useState(0);
  const [operations, setOperations] =
    useState<Page<AgentWriteOperation> | null>(null);
  const [candidates, setCandidates] = useState<Page<Candidate> | null>(null);
  const [selectedCandidate, setSelectedCandidate] = useState<Candidate | null>(
    null,
  );
  const [busy, setBusy] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const candidateGeneration = useRef(0);
  useEffect(() => {
    const controller = new AbortController();
    setBusy(true);
    setError("");
    const params = new URLSearchParams({ limit: "25", offset: String(offset) });
    if (candidateStatus) params.set("status", candidateStatus);
    if (candidateType) params.set("candidate_type", candidateType);
    const path =
      tab === "operations"
        ? `/api/agent-operations?${operationParams(filters, offset)}`
        : `/api/candidates?${params}`;
    request<Page<AgentWriteOperation> | Page<Candidate>>(path, {
      signal: controller.signal,
    })
      .then((page) => {
        if (controller.signal.aborted) return;
        if (tab === "operations")
          setOperations(page as Page<AgentWriteOperation>);
        else setCandidates(page as Page<Candidate>);
      })
      .catch((err: unknown) => {
        if (!controller.signal.aborted) {
          setError(errorMessage(err));
          setOperations(null);
          setCandidates(null);
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setBusy(false);
      });
    return () => controller.abort();
  }, [tab, filters, candidateStatus, candidateType, offset, refresh]);
  useEffect(
    () => () => {
      candidateGeneration.current++;
    },
    [],
  );

  function switchTab(next: "operations" | "candidates") {
    setTab(next);
    setOffset(0);
    setSelectedCandidate(null);
    candidateGeneration.current++;
  }
  function updateFilter(key: keyof AgentOperationFilters, value: string) {
    setDraft((current) => ({ ...current, [key]: value }));
  }
  async function openCandidate(id: string) {
    const current = ++candidateGeneration.current;
    setError("");
    try {
      const candidate = await request<Candidate>(
        `/api/candidates/${encodeURIComponent(id)}`,
      );
      if (current === candidateGeneration.current) {
        setTab("candidates");
        setOffset(0);
        setSelectedCandidate(candidate);
      }
    } catch (err) {
      if (current === candidateGeneration.current) setError(errorMessage(err));
    }
  }
  async function exportJsonl() {
    setExporting(true);
    setError("");
    try {
      download(
        await exportAgentOperations(filters),
        "kinlayer-agent-write-operations.jsonl",
        "application/x-ndjson",
      );
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setExporting(false);
    }
  }
  const page = tab === "operations" ? operations : candidates;
  return (
    <section className="support-page stack" aria-labelledby="diagnostics-title">
      <header className="page-heading">
        <div>
          <h1 id="diagnostics-title">운영 기록</h1>
          <p>
            에이전트 쓰기 기록과 과거 후보 처리 이력을 읽기 전용으로 확인합니다.
          </p>
        </div>
        <button
          className="button"
          disabled={busy}
          onClick={() => setRefresh((value) => value + 1)}
        >
          새로고침
        </button>
      </header>
      <div className="filter-tabs" aria-label="운영 기록 종류">
        <button
          className={`filter-tab ${tab === "operations" ? "active" : ""}`}
          aria-pressed={tab === "operations"}
          onClick={() => switchTab("operations")}
        >
          에이전트 작업
        </button>
        <button
          className={`filter-tab ${tab === "candidates" ? "active" : ""}`}
          aria-pressed={tab === "candidates"}
          onClick={() => switchTab("candidates")}
        >
          과거 후보 이력
        </button>
      </div>
      {tab === "operations" ? (
        <section className="panel content-panel stack" aria-label="작업 필터">
          <form
            className="stack"
            onSubmit={(event) => {
              event.preventDefault();
              if (
                draft.created_from &&
                draft.created_to &&
                new Date(draft.created_from) > new Date(draft.created_to)
              ) {
                setError("시작 시각은 종료 시각보다 늦을 수 없습니다.");
                return;
              }
              setOffset(0);
              setFilters(normalizedFilters(draft));
            }}
          >
            <div className="support-grid filters-grid">
              <label className="field">
                <span>작성 주체</span>
                <input
                  value={draft.actor}
                  onChange={(event) =>
                    updateFilter("actor", event.target.value)
                  }
                  placeholder="예: ai_agent"
                />
              </label>
              <label className="field">
                <span>요청 경로</span>
                <input
                  value={draft.source_path}
                  onChange={(event) =>
                    updateFilter("source_path", event.target.value)
                  }
                  placeholder="예: /api/candidates"
                />
              </label>
              <label className="field">
                <span>작업 종류</span>
                <select
                  value={draft.operation_type}
                  onChange={(event) =>
                    updateFilter("operation_type", event.target.value)
                  }
                >
                  <option value="all">전체</option>
                  {Object.entries(operationLabels).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>결과</span>
                <select
                  value={draft.result_status}
                  onChange={(event) =>
                    updateFilter("result_status", event.target.value)
                  }
                >
                  <option value="all">전체</option>
                  <option value="success">성공</option>
                  <option value="rejected">거절됨</option>
                </select>
              </label>
              <label className="field">
                <span>오류 여부</span>
                <select
                  value={draft.has_error}
                  onChange={(event) =>
                    updateFilter("has_error", event.target.value)
                  }
                >
                  <option value="all">전체</option>
                  <option value="true">오류 있음</option>
                  <option value="false">오류 없음</option>
                </select>
              </label>
              <label className="field">
                <span>시작 시각</span>
                <input
                  type="datetime-local"
                  value={draft.created_from}
                  onChange={(event) =>
                    updateFilter("created_from", event.target.value)
                  }
                />
              </label>
              <label className="field">
                <span>종료 시각</span>
                <input
                  type="datetime-local"
                  value={draft.created_to}
                  onChange={(event) =>
                    updateFilter("created_to", event.target.value)
                  }
                />
              </label>
            </div>
            <div className="toolbar">
              <button className="button primary" type="submit" disabled={busy}>
                필터 적용
              </button>
              <button
                className="button"
                type="button"
                onClick={() => {
                  setDraft(initialOperationFilters);
                  setFilters(initialOperationFilters);
                  setOffset(0);
                }}
              >
                필터 초기화
              </button>
            </div>
          </form>
          <div className="toolbar">
            <button
              className="button"
              disabled={exporting || busy}
              onClick={() => void exportJsonl()}
            >
              {exporting ? "내보내는 중…" : "JSONL 내보내기 · 최대 200건"}
            </button>
            <button
              className="button"
              disabled={busy || !operations?.items.length}
              onClick={() => {
                if (operations)
                  download(
                    operationsCsv(operations.items),
                    `kinlayer-operations-${offset + 1}-${offset + operations.items.length}.csv`,
                    "text/csv;charset=utf-8",
                  );
              }}
            >
              현재 페이지 CSV
            </button>
          </div>
          <p className="muted small">
            내보내기는 적용된 필터 기준입니다. JSONL은 처음 200건까지, CSV는
            현재 페이지에 표시된 작업만 포함합니다. 이 화면은 기존 에이전트 작업
            로그이며 전체 기억 변경 이력은 기억 상세에서 확인합니다.
          </p>
        </section>
      ) : (
        <section className="panel content-panel stack">
          <p className="muted">
            과거 후보의 제안·처리 결과를 보존한 이력입니다. 현재 기억은 저장
            즉시 반영되며 정정과 철회는 기억 상세에서 진행합니다.
          </p>
          <div className="support-grid filters-grid">
            <label className="field">
              <span>처리 상태</span>
              <select
                value={candidateStatus}
                onChange={(event) => {
                  setCandidateStatus(event.target.value);
                  setOffset(0);
                  setSelectedCandidate(null);
                }}
              >
                <option value="">전체</option>
                {[
                  "pending",
                  "accepted",
                  "edited_accepted",
                  "rejected",
                  "archived",
                  "needs_clarification",
                  "superseded",
                ].map((value) => (
                  <option key={value} value={value}>
                    {statusLabels[value]}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>후보 종류</span>
              <select
                value={candidateType}
                onChange={(event) => {
                  setCandidateType(event.target.value);
                  setOffset(0);
                  setSelectedCandidate(null);
                }}
              >
                <option value="">전체</option>
                {Object.entries(candidateLabels).map(([value, title]) => (
                  <option key={value} value={value}>
                    {title}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </section>
      )}
      {error && <Notice error>{error}</Notice>}
      {busy && <Notice>기록을 불러오는 중…</Notice>}
      {!busy && tab === "operations" && operations && (
        <section className="stack" aria-label="작업 기록 목록">
          {operations.items.map((operation) => (
            <details
              className="panel content-panel operation-record"
              key={operation.id}
            >
              <summary>
                <strong>
                  {operationLabels[operation.operation_type] ??
                    operation.operation_type}
                </strong>
                <span className="pill">
                  {statusLabels[operation.result_status] ??
                    operation.result_status}
                </span>
                <span className="muted small">
                  {dateText(operation.created_at)}
                </span>
              </summary>
              <div className="stack">
                <dl className="support-facts">
                  <div>
                    <dt>작성 주체</dt>
                    <dd>{operation.actor}</dd>
                  </div>
                  <div>
                    <dt>요청 경로</dt>
                    <dd>{operation.source_path}</dd>
                  </div>
                  {operation.api_error_code && (
                    <div>
                      <dt>오류</dt>
                      <dd>{operation.api_error_code}</dd>
                    </div>
                  )}
                </dl>
                {operation.bounded_excerpt && (
                  <blockquote>{operation.bounded_excerpt}</blockquote>
                )}
                <div className="toolbar">
                  {operation.canonical_record_ref && (
                    <MemoryLink
                      reference={operation.canonical_record_ref}
                      onNavigate={onNavigate}
                    />
                  )}{" "}
                  {operation.episode_id && (
                    <Link
                      path={`/sources/${encodeURIComponent(operation.episode_id)}`}
                      onNavigate={onNavigate}
                    >
                      출처 보기
                    </Link>
                  )}
                  {operation.candidate_id && (
                    <button
                      className="text-link"
                      onClick={() =>
                        void openCandidate(operation.candidate_id!)
                      }
                    >
                      관련 후보 이력 보기
                    </button>
                  )}
                </div>
                <JsonDetails
                  title="요청 요약"
                  value={operation.request_summary}
                />
                <JsonDetails title="진단 상세" value={operation.diagnostics} />
                <JsonDetails
                  title="연결된 기록"
                  value={operation.related_refs}
                />
              </div>
            </details>
          ))}
          {!operations.items.length && (
            <p className="empty-state">조건에 맞는 에이전트 작업이 없습니다.</p>
          )}
        </section>
      )}
      {!busy && tab === "candidates" && candidates && (
        <section className="stack" aria-label="과거 후보 목록">
          {selectedCandidate && (
            <div className="panel content-panel stack">
              <div className="toolbar">
                <h2>연결된 후보 이력</h2>
                <button
                  className="button small-button"
                  onClick={() => setSelectedCandidate(null)}
                >
                  닫기
                </button>
              </div>
              <CandidateDetails
                candidate={selectedCandidate}
                onNavigate={onNavigate}
              />
            </div>
          )}
          {candidates.items.map((candidate) => (
            <details
              className="panel content-panel operation-record"
              key={candidate.id}
            >
              <summary>
                <strong>
                  {candidateLabels[candidate.candidate_type] ??
                    candidate.candidate_type}
                </strong>
                <span className="pill">
                  {statusLabels[candidate.status] ?? candidate.status}
                </span>
                <span className="muted small">
                  {dateText(candidate.created_at)}
                </span>
              </summary>
              <CandidateDetails candidate={candidate} onNavigate={onNavigate} />
            </details>
          ))}
          {!candidates.items.length && (
            <p className="empty-state">조건에 맞는 과거 후보가 없습니다.</p>
          )}
        </section>
      )}
      {page && (
        <Pagination
          offset={offset}
          limit={25}
          total={page.total}
          busy={busy}
          onChange={setOffset}
        />
      )}
    </section>
  );
}

function CandidateDetails({
  candidate,
  onNavigate,
}: Navigation & { candidate: Candidate }) {
  const content =
    candidate.payload.content ??
    candidate.payload.claim_text ??
    candidate.payload.display_name;
  return (
    <div className="stack">
      <p>
        {typeof content === "string"
          ? content
          : "제안 내용은 상세 기록에서 확인할 수 있습니다."}
      </p>
      <dl className="support-facts">
        <div>
          <dt>제안 주체</dt>
          <dd>{candidate.created_by}</dd>
        </div>
        <div>
          <dt>처리 시점</dt>
          <dd>{dateText(candidate.resolved_at)}</dd>
        </div>
        <div>
          <dt>처리 주체</dt>
          <dd>{candidate.resolved_by ?? "기록 없음"}</dd>
        </div>
      </dl>
      {candidate.resolution_note && <p>{candidate.resolution_note}</p>}
      <div className="toolbar">
        {candidate.canonical_record_ref && (
          <MemoryLink
            reference={candidate.canonical_record_ref}
            ownerId={candidate.target_entity_id}
            onNavigate={onNavigate}
          />
        )}{" "}
        {candidate.target_entity_id && (
          <Link
            path={`/people/${encodeURIComponent(candidate.target_entity_id)}`}
            onNavigate={onNavigate}
          >
            관련 인물 보기
          </Link>
        )}
      </div>
      {candidate.evidence.map((source) => (
        <div className="source-snippet" key={source.id}>
          {source.excerpt && <blockquote>{source.excerpt}</blockquote>}
          <Link
            path={`/sources/${encodeURIComponent(source.episode_id)}`}
            onNavigate={onNavigate}
          >
            출처 보기
          </Link>
        </div>
      ))}
      <JsonDetails title="과거 제안 상세" value={candidate.payload} />
    </div>
  );
}
