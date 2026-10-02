import { useRef, useState, type FormEvent } from "react";
import { api, errorText, type Person } from "./data";
import { Modal } from "./common";

export function PersonDelete({ person, onClose, onDeleted }: {
  person: Person; onClose: () => void; onDeleted: () => void;
}) {
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [deleted, setDeleted] = useState(false);
  const [error, setError] = useState<unknown>();
  const submitting = useRef(false);
  const allowed = person.status === "active" && !person.is_system && !person.system_role;

  function close() {
    if (!submitting.current) onClose();
  }

  async function remove(event: FormEvent) {
    event.preventDefault();
    if (submitting.current || deleted || !allowed || !confirmed) return;
    submitting.current = true;
    setBusy(true);
    setError(undefined);
    const path = `/api/entities/${encodeURIComponent(person.id)}`;
    const matches = (result: Person | null | undefined) => result?.id === person.id && result.status === "deleted";
    try {
      let result: Person;
      try {
        result = await api<Person>(path, { method: "DELETE" });
      } catch (err) {
        // A lost response can follow a committed deletion. Read the same entity
        // before offering a retry, which would reject an already deleted record.
        const readback = await api<Person>(path).catch(() => null);
        if (!matches(readback)) throw err;
        result = readback!;
      }
      if (!matches(result)) throw new Error("선택한 인물의 삭제 완료를 확인하지 못했어요. 다시 시도해 주세요.");
      setDeleted(true);
      onDeleted();
    } catch (err) {
      setError(err);
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  }

  return <Modal title="인물 삭제" onClose={close}>
    <form onSubmit={remove}>
      <div className="modal-body stack">
        <section className="evidence-card stack" aria-label="삭제할 인물">
          <h3>{person.display_name}</h3>
          <span className="small muted">{person.id.slice(0, 6)}</span>
        </section>
        <div className="notice stack">
          <p>이 인물을 인물 목록에서 제외합니다.</p>
          <p className="small">연결된 기억·프로필·관계·별칭과 원본 출처는 보존됩니다.</p>
          <p className="small">보존된 기록은 기억 목록이나 관계 그래프에 계속 표시될 수 있습니다.</p>
          <p className="small">현재는 삭제한 인물을 복구하는 기능이 없습니다.</p>
        </div>
        {!allowed && <p className="error-state" role="alert">현재 등록된 일반 인물만 삭제할 수 있어요. 나와 시스템 인물은 삭제할 수 없습니다.</p>}
        <label className="row"><input type="checkbox" required checked={confirmed} disabled={!allowed || busy || deleted}
          onChange={(event) => setConfirmed(event.target.checked)} />이 인물을 목록에서 제외하고, 연결된 정보는 보존하는 것을 확인했어요.</label>
        {!!error && <p className="error-state" role="alert">{errorText(error)}</p>}
      </div>
      <footer className="modal-footer">
        <button className="button" type="button" disabled={busy} onClick={close}>취소</button>
        <button className="button primary" type="submit" disabled={!allowed || !confirmed || busy || deleted}>
          {busy ? "삭제 확인 중…" : deleted ? "삭제 완료" : "인물 삭제"}
        </button>
      </footer>
    </form>
  </Modal>;
}
