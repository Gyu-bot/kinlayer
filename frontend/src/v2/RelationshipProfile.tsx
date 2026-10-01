import { useState } from "react";
import { ErrorState, Loading } from "./common";
import { MemoryEditor } from "./MemoryEditor";
import {
  dateTime,
  memoryUrl,
  useResource,
  type MemoryItem,
  type Ontology,
  type RelationshipProfileRead,
} from "./data";

export function RelationshipProfile({
  personId,
  ontology,
  version = 0,
  editable = true,
  onChanged,
}: {
  personId: string;
  ontology?: Ontology;
  version?: number;
  editable?: boolean;
  onChanged: () => void;
}) {
  const registry = ontology?.relationship_profile;
  const profile = useResource<RelationshipProfileRead>(
    registry ? `/api/entities/${encodeURIComponent(personId)}/relationship-profile` : null,
    version,
  );
  const [editing, setEditing] = useState<{
    axis: string;
    record?: MemoryItem;
    action: "create" | "correct" | "retract";
  }>();
  const [notice, setNotice] = useState("");
  return (
    <section className="panel content-panel stack" aria-label="나와의 관계">
      <div className="section-heading">
        <h2>나와의 관계</h2>
        <a className="text-link" href={`/changes?person=${encodeURIComponent(personId)}`}>변경 이력</a>
      </div>
      <p className="small muted">나의 관점에서 직접 기록한 현재 상태입니다. 각 속성은 독립적이며, 미설정은 낮은 친밀도나 연락 없음을 뜻하지 않습니다.</p>
      {notice && <p className="notice" role="status">{notice}</p>}
      {profile.data && !profile.data.perspective_entity_id && <p className="small muted">기준 인물 ‘나’가 설정되지 않아 값을 저장할 수 없어요.</p>}
      {!registry ? <p className="muted">관계 속성 정보를 불러오는 중이거나 서버에서 지원하지 않아요.</p>
        : profile.loading ? <Loading />
          : profile.error ? <ErrorState error={profile.error} retry={profile.reload} />
            : profile.data && (
              <div className="fact-grid">
                {Object.entries(registry.axes).map(([axis, definition]) => {
                  const current = profile.data!.axes[axis];
                  const record = current?.record || undefined;
                  const source = record?.sources.find((s) => !s.missing);
                  const valueLabel = definition.values.find((v) => v.value === current?.value)?.label || current?.label || current?.value || "미설정";
                  return (
                    <section className="fact stack" key={axis} aria-label={definition.label}>
                      <h3>{definition.label}</h3>
                      <span className="pill">{valueLabel}</span>
                      <p className="small muted">{definition.description}</p>
                      {record && (
                        <div className="stack small">
                          <span>{source?.actor || "출처 미상"} · {dateTime(record.updated_at)}</span>
                          <div className="row wrap">
                            <a className="text-link" href={memoryUrl(record.record_ref)}>기억과 출처 보기</a>
                            <a className="text-link" href={`/changes?record=${encodeURIComponent(record.record_ref)}`}>이 값의 변경 이력</a>
                          </div>
                        </div>
                      )}
                      <div className="row wrap">
                        <button className="button" disabled={!editable || !profile.data?.perspective_entity_id}
                          onClick={() => setEditing({ axis, record, action: record ? "correct" : "create" })}>
                          {definition.label} {record ? "수정" : "설정"}
                        </button>
                        {record && <button className="text-link" disabled={!editable}
                          onClick={() => setEditing({ axis, record, action: "retract" })}>
                          {definition.label} 미설정으로 변경
                        </button>}
                      </div>
                    </section>
                  );
                })}
              </div>
            )}
      {editing && profile.data && <MemoryEditor
        item={editing.record}
        personId={profile.data.entity_id}
        action={editing.action}
        relationshipAxis={editing.axis}
        perspectiveEntityId={profile.data.perspective_entity_id || undefined}
        onClose={() => setEditing(undefined)}
        onSaved={() => {
          setNotice(editing.action === "retract" ? "미설정으로 변경했어요. 이전 값과 출처는 이력에 남습니다." : "나와의 관계를 저장했어요.");
          setEditing(undefined);
          profile.reload();
          onChanged();
        }}
      />}
    </section>
  );
}
