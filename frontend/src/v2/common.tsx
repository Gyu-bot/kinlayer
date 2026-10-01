import {
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  basisLabels,
  dateTime,
  errorText,
  label,
  memoryText,
  memoryUrl,
  query,
  useResource,
  type MemoryItem,
  type Page,
  type Person,
} from "./data";

export function ErrorState({
  error,
  retry,
}: {
  error: unknown;
  retry?: () => void;
}) {
  return (
    <div className="error-state" role="alert">
      <p>{errorText(error)}</p>
      {retry && (
        <button className="button" onClick={retry}>
          다시 시도
        </button>
      )}
      <a className="text-link" href="/settings">
        연결 설정
      </a>
    </div>
  );
}
export function Loading() {
  return (
    <p className="empty-state" role="status">
      불러오는 중이에요…
    </p>
  );
}
export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="empty-state">
      <p>{children}</p>
    </div>
  );
}
export function Pager({
  page,
  onPage,
}: {
  page: Page<unknown>;
  onPage: (offset: number) => void;
}) {
  return (
    <div className="table-footer">
      <span>
        전체 {page.total}개
        {page.total > 0 &&
          ` · ${page.offset + 1}–${Math.min(page.offset + page.items.length, page.total)}`}
      </span>
      <div className="row">
        <button
          className="button ghost"
          disabled={!page.offset}
          onClick={() => onPage(Math.max(0, page.offset - page.limit))}
        >
          이전
        </button>
        <button
          className="button ghost"
          disabled={page.offset + page.limit >= page.total}
          onClick={() => onPage(page.offset + page.limit)}
        >
          다음
        </button>
      </div>
    </div>
  );
}
export function Modal({
  title,
  children,
  onClose,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null),
    heading = useId();
  useLayoutEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const dialog = ref.current;
    dialog?.showModal();
    return () => {
      dialog?.close();
      previous?.focus();
    };
  }, []);
  return (
    <dialog
      className="modal"
      ref={ref}
      aria-labelledby={heading}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
    >
      <header className="modal-header">
        <h2 id={heading}>{title}</h2>
        <button className="button ghost" onClick={onClose} aria-label="닫기">
          닫기
        </button>
      </header>
      {children}
    </dialog>
  );
}
export function PersonPicker({
  value,
  onChange,
  title = "인물",
  initialName,
  disabled = false,
}: {
  value: string;
  onChange: (id: string) => void;
  title?: string;
  initialName?: string;
  disabled?: boolean;
}) {
  const [q, setQ] = useState(""),
    [offset, setOffset] = useState(0),
    id = useId();
  const r = useResource<Page<Person>>(
    `/api/entities?${query({ entity_type: "person", status: "active", q, limit: 30, offset })}`,
  );
  return (
    <div className="field">
      <label htmlFor={`${id}-search`}>{title} 검색</label>
      <input
        id={`${id}-search`}
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setOffset(0);
        }}
        disabled={disabled}
        placeholder="이름 또는 별칭"
      />
      <label htmlFor={id}>{title}</label>
      <select
        id={id}
        value={value}
        required
        disabled={disabled || r.loading}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">인물을 선택하세요</option>
        {value && !r.data?.items.some((p) => p.id === value) && (
          <option value={value}>{initialName || "선택된 인물"}</option>
        )}
        {r.data?.items.map((p) => (
          <option key={p.id} value={p.id}>
            {p.display_name}
            {p.system_role === "self" ? " (나)" : ""} · {p.id.slice(0, 6)}
          </option>
        ))}
      </select>
      {r.error ? <ErrorState error={r.error} retry={r.reload} /> : null}
      {r.data && r.data.total > 30 && (
        <Pager page={r.data} onPage={setOffset} />
      )}
    </div>
  );
}
export function MemoryCard({
  item,
  onOpen,
}: {
  item: MemoryItem;
  onOpen?: (item: MemoryItem) => void;
}) {
  return (
    <article className="memory-card">
      <div className="row between">
        <span className="eyebrow">
          {label(
            item.payload.fact_type ||
              item.payload.observation_type ||
              item.payload.relation_type ||
              item.record_type,
          )}
        </span>
        <span
          className={`pill ${item.claim_basis === "inferred" ? "warning" : ""}`}
        >
          {basisLabels[item.claim_basis]}
        </span>
      </div>
      <a
        className="memory-content"
        href={memoryUrl(item.record_ref)}
        onClick={
          onOpen
            ? (e) => {
                e.preventDefault();
                onOpen(item);
              }
            : undefined
        }
      >
        {memoryText(item)}
      </a>
      <div className="context-meta">
        {item.entities.map((p) => (
          <a key={`${p.id}:${p.role}`} href={`/people/${p.id}`}>
            {p.display_name} · {label(p.role)}
          </a>
        ))}
      </div>
      <div className="context-meta">
        <span>
          {item.is_current
            ? "현재 맥락"
            : item.status === "active"
              ? "유효 기간 밖"
              : item.status === "superseded"
                ? "정정 전 기록"
                : ["deleted", "retracted"].includes(item.status)
                  ? "철회됨"
                  : item.status}
        </span>
        <span>{item.sources.filter((s) => !s.missing).length}개 출처</span>
      </div>
      {(item.valid_from || item.valid_to) && (
        <p className="small muted">
          유효 기간 {item.valid_from ? dateTime(item.valid_from) : "시작 미상"}{" "}
          → {item.valid_to ? dateTime(item.valid_to) : "종료 미상"}
        </p>
      )}
    </article>
  );
}
