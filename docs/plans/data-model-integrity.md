# 데이터 모델·온톨로지 근본 개선 — `model-integrity-v1`

- 최초 기준일: 2026-10-19. 설계 보완: 2026-10-22.
- 상태: **계획, 미구현.** 라이브에서 같은 관계가 두 번 기록된 것을 계기로, 사용자가 개별 값을
  고치지 말고 그런 데이터가 생길 수 있는 DB·온톨로지 구조를 찾아 근본적으로 고치는 계획을
  요청했다. 구현, 배포, 기존 데이터 전환은 각각 별도 승인 단계다.
- 순서: [실행 오류 수정](runtime-correctness.md)의 선행 안전 수정 후 공통 계보·쓰기 기반부터
  구현한다. [임베딩 자동 생성](embedding-auto-index.md)은 이 기반의 commit 경계를 사용한다.
  [관찰 개편](observation-ontology-v1.md)은 공통 기반에 의존하며 M8은 그 2단계와 함께 전환한다.
- 선행 계약: [즉시 저장 메모리](save-first-memory-schema.md),
  [관계 온톨로지 relationship-v1](relationship-ontology.md)

## 2026-10-22 검토 반영

[검토 증거](../verification/schema-logic-review-2026-10-22.md)와
[공통 기록 계약](record-lifecycle-contract.md)을 반영했다. S1–S12와 MI01–MI12의 식별자는
유지하되, 아래 M1/M2/M5/M6/M7/M8의 충돌하던 설계를 고치고 MI13–MI20을 추가한다.
이 문서는 목표 설계다. 구현·배포·기존 자료 전환은 별도 작업이며, 10월 19일 라이브 수치를
10월 22일 현재 데이터로 재확인한 것으로 읽지 않는다.

- 단일 `superseded_by_id` 제안은 교차 유형·1:N/N:1 계보로 대체한다.
- status만으로 정한 현재 유일성은 revision 상태와 유효기간을 구분하는 제약으로 보완한다.
- 병합의 원본 변경·import 증명 파손, 후보 상태 경합, Self 보호, FK 검사 누락은 runtime 계획과
  함께 해결한다. 일반 CRUD 종료만으로 공통 writer가 완성됐다고 판단하지 않는다.
- 공통 불변식의 세부 설계는 record-lifecycle 계약이 소유한다. 각 M 항목은 그 계약의 적용 범위다.

## 0. 문제의 성격

라이브 이상 데이터는 대부분 입력 실수가 아니다. 스키마가 **같은 사실을 여러 방식으로 표현할 수
있게** 열어 두었고, 그 사실이 하나뿐이라는 **불변식을 DB가 아니라 호출자(에이전트·화면)에게
맡겼기** 때문에 생겼다. 그래서 값을 고쳐도 같은 경로로 다시 생긴다. 이 계획은 다음 원칙으로 구조를
고친다.

1. **한 사실, 한 표현:** 의미가 같은 기록은 저장 형태도 하나만 가능해야 한다.
2. **불변식은 DB가 지킨다:** "현재 기록은 하나", "현재 기록에는 근거가 있다" 같은 규칙은 서비스 검사와
   DB 제약을 함께 둔다. 서비스 검사는 친절한 오류를, DB 제약은 최종 보장을 맡는다.
3. **정의는 한 곳:** 같은 어휘를 코드·테이블·레지스트리에 따로 두지 않는다.
4. **canonical writer는 하나:** `/api/memories`와 허용된 import·호환 실행 경로가 같은
   근거·변경 이력 트랜잭션 서비스를 사용한다. 여러 HTTP 진입점이 별도 불변식을 만들지 않는다.

범위 경계: 관찰 유형·참여자 역할·주장 형태·시간 정밀도·프로필 사실 유형 정의는
[observation-v1](observation-ontology-v1.md)이 다룬다. 이 계획은 그 아래의 공통 구조(기록의 정체성,
생애주기, 근거, 쓰기 경로, 정의 저장소)와 관계·인물·평가 모델을 다룬다.

## 1. 진단 — 라이브 증상과 구조 원인

2026-10-19 `casa` 라이브 DB를 읽기 전용으로 조회했다. 활성 인물 11명, 관계 7건, 관찰 241건,
프로필 사실 12건이다. 개인 내용은 기록하지 않는다.

| ID | 라이브 증상 | 구조 원인 |
| --- | --- | --- |
| S1 | 무방향 관계 2쌍이 방향만 뒤집혀 중복 활성(활성 관계 7건 중 4건). 둘 다 에이전트가 반대 방향으로 다시 만들었다. | 무방향 관계를 **순서쌍**(`from`,`to`)으로 저장해 같은 사실에 두 표현이 있다. "같은 두 사람·같은 유형의 현재 관계는 하나" 제약이 DB에도 서비스에도 없다. 병합의 중복 검사도 순서쌍만 비교한다. |
| S2 | 이전 `former_partner` 기록에 `directed=true`가 남아 있다(유형 정의는 무방향). | `directed`가 행마다 저장된 **파생 값**이다. 유형 정의와 어긋나도 막는 제약이 없다. |
| S3 | 관계 유형이 코드 `EDGE_DEFINITIONS`, `allowed_edge_types`, `ontology_registry_values(edge_type)` 세 곳에 있다. legacy 유형 11개가 테이블에서는 `active=true`인데 실제 쓰기는 코드의 `support_level`이 막는다. 관찰 유형도 두 테이블에 있다. | **정의 저장소가 여럿**이고 `active`의 뜻이 저장소마다 다르다. |
| S4 | 같은 두 사람 사이 `romantic_partner`·`former_partner`·`situationship`이 동시에 현재일 수 있다(지금 사례는 없음). 관계 변화가 "정정"이 아니라 "추가"로 들어올 수 있다. | 관계에 관계 평가 축 같은 **슬롯 개념**이 없다. 상태가 바뀌는 관계(연인→전 연인)를 별개 유형으로 두면서 상호 배타성을 정의하지 않았다. |
| S5 | 사용자 본인이 Self와 별도의 일반 인물로 하나 더 존재한다. Self 표시 이름은 기본값 `Self`, 별칭 0개다. | Self의 **이름·별칭이 필수가 아니다**. 인물 생성 시 이름·별칭이 겹치는지 서버가 확인하지 않고, 인물 식별을 에이전트에 맡긴다. 별칭 정규화 값에 엔티티 간 유일성 규칙이 없다. |
| S6 | 근거 `actor`가 같은 사용자를 `나`·`user`·실명으로 기록한다. 관찰 본문도 사용자를 이름·`사용자`·영문 계정명으로 부른다. | 근거의 화자가 **자유 문자열**이고 인물 엔티티와 연결되지 않는다. |
| S7 | 현재 관찰 94건, 프로필 사실 7건(12건 중), 관계 1건에 근거가 없다. 모두 save-first 이전 경로로 만들어졌다. | 근거 없는 현재 기록을 막는 불변식이 없다. 근거·변경 이력을 남기지 않는 **호환 CRUD 쓰기 경로**(`POST /api/edges`, `/api/observations`, `/api/entity-facts`, `/api/episodes`)가 아직 열려 있다(마지막 사용 10-01). |
| S8 | 교체된 관계 4건 중 1건만 `invalidated_by_edge_id`가 있다. 관찰·사실에는 대체 기록을 가리키는 열이 없다. 이력은 `memory_changes`의 문자열 참조(`table:id`)로만 이어진다. | **계보 표현이 테이블마다 다르고** FK가 없다. |
| S9 | 핵심 테이블(`entities`·`entity_edges`·`observations`·`entity_facts`·`entity_aliases`)의 `status`에 CHECK 제약이 없다. 병합 코드는 다른 경로가 쓰지 않는 `deprecated`를 쓴다. 인물은 `status`와 `confirmation_status`가 항상 짝으로 움직인다(`active/confirmed`, `merged/merged`, `deleted/deprecated`). | **생애주기 어휘가 표준화되지 않았고** 같은 정보가 두 열에 중복돼 있다. 최근 테이블(curation·reconciliation)에는 CHECK가 있다. |
| S10 | 한 사람의 같은 뜻 `location_hint`가 2건 활성이다. | 프로필 사실 유형에 **값 개수 규칙**(하나만/여럿 가능)이 없고, 같은 값의 중복을 판정할 정규화 키가 없다. |
| S11 | 두 사람이 `connection_state=disconnected`이면서 `interaction_frequency=frequent`다. 빈도가 더 오래된 기록이다. 관계 평가 11건에도 임베딩이 만들어져 있다. | 관계 평가가 **관찰 테이블에 끼워져** 있다. 전용 nullable 열 4개와, 코드 `AXES`를 복제한 인라인 CHECK가 필요하다. 검색·컨텍스트·조회 코드가 이 유형을 예외 처리한다. 축별 기록 시점을 함께 보여 주지 않아, 한 축만 바뀌면 다른 축이 낡았는지 알 수 없다. |
| S12 | 퇴역한 `sensitivity`·`ai_use_policy`·`claim_type` 열이 모든 핵심 행에 남아 있고, 레지스트리 범주도 남아 있다. | 퇴역 메타데이터가 물리 스키마에 남아 새 쓰기마다 기본값으로 채워진다. |

정상 확인: 삭제·병합된 인물을 가리키는 현재 기록 0건, `memory_changes` 참조 중 없는 행을 가리키는
것 0건, 같은 본문 중복 관찰 0건, 관계 평가 축 유일성 유지.

## 2. 개선 항목

### M1 관계의 정체성 (S1, S2)

- **무방향 관계의 현재 키는 정규 순서로 저장한다:** `directed=false`이면 canonical from < canonical to.
  서비스가 정렬하고 CHECK로 보장한다. 새 payload도 같은 순서로 만들되 과거 원본 FK는 보존한다.
  단순 병합은 canonical 키를 갱신하며 의미 정정이 필요한 경우에만 새 revision을 만든다.
- **관계 유일성:** canonical 인물 쌍과 유형이 같고 revision 상태가 active/disputed인 기록의
  유효기간 중복을 막는다. 끝난 기간과 새 기간은 공존할 수 있다. 정규 키·PostgreSQL 기간 겹침
  제약은 공통 계약 5절을 따르며, status만 보는 부분 유니크 인덱스 제안은 대체한다.
  SQLite 서비스 테스트와 실제 PostgreSQL 제약 테스트를 구분한다.
- **canonical `directed`는 유형에서 파생한다:** 현재 제약에 쓰는 projection의
  `(relation_type, directed)`가 정의를 복합 FK로 참조한다. 과거 원본 payload의 directed에는
  최신 정의 FK를 소급 적용하지 않는다. 새 쓰기는 방향을 정의에서 도출하며, 기존 구조를 그대로
  보존하는 정정의 호환 어댑터는 원본 표현과 검증된 canonical 키를 구별한다. 과거 방향을 현재
  키로 해석할 근거가 모호하면 전환을 중단하고 manifest 검토 대상으로 남긴다.
- **충돌 응답:** 위반은 HTTP 409 `relationship_edge_conflict` + `details.current_record_ref`로
  돌려준다. 부분 날짜 때문에 겹침을 배제할 수 없는 경우 그 이유·정밀도도 제공한다.
  병합은 같은 canonical 키로 검사하고 검증된 중복만 원본·import 증명을 보존하며 통합한다.

### M2 관계 슬롯과 상호 배타성 (S4)

- 관계 유형 정의에 `slot`을 둔다. 같은 두 사람 사이에 같은 슬롯의 현재 관계는 하나만 허용한다.
  예: `romance`(`situationship`, `romantic_partner`, `former_partner`), `marriage`(`spouse`,
  `former_spouse`), `employment`(`coworker`, `former_coworker`). 슬롯이 없는 유형(친구, 가족,
  동문 등)은 M1 규칙만 적용한다.
- 슬롯 안의 관계 변화는 기존 exact ref를 지정한 작업으로 처리한다. 단순 오기 정정은 supersession,
  실제 시간에 따른 변화는 이전 기간 종료와 새 기간을 함께 기록한다. 두 경우를 구별하고, 참이었던
  과거 관계를 틀린 사실로 덮어쓰거나 현재 관계와 기간이 겹친 채 방치하지 않는다.
- DB 보장: 정의와 행에 NOT NULL 파생 `slot_key`를 두고 복합 FK로 일치시킨다. 슬롯 없음은
  내부 `none`으로 표시하고 이 경우 슬롯 겹침 제약만 제외한다. NULL 복합 FK 우회는 허용하지 않는다.
  같은 슬롯의 가능한 유효기간 중복을 공통 계약 5–6절에 따라 검사한다.
- 관계 온톨로지 계획에서 보류한 "구조화된 충돌·해결 모델"과는 다르다. 동시 현재 관계 하나만 막고,
  충돌 해결 절차는 만들지 않는다(Q2).

### M3 정의 저장소 단일화 (S3)

- 관계 유형의 원본은 버전이 붙은 코드 정의 하나로 한다. DB에는 시드가 매번 upsert하는 테이블 하나만
  둔다: `relation_type`, `label`, `inverse_label`, `directed`, `slot_key`, `category`, `support_level`,
  `ontology_version`.
- `ontology_registry_values`의 `edge_type`·`observation_type` 범주를 제거한다. 관찰 유형 정의 테이블의
  내용은 observation-v1 3.1이 정한다. 이 항목은 저장 위치와 시드 방식만 통일한다.
- `active`(조회 가능)와 `support_level`(새 쓰기 가능)의 뜻을 문서와 API에서 하나로 정의한다.
  legacy 유형은 `support_level=legacy`로만 표시한다.

### M4 인물 정체성과 Self (S5, S6)

- **Self 이름 필수:** 부트스트랩은 `KINLAYER_SELF_NAME`이 없거나 `Self`이면 경고하고, 진단 API에
  `self_unnamed`를 보고한다. Self의 표시 이름과 별칭은 웹 설정에서 바꿀 수 있다.
- **이름도 별칭으로 관리:** 표시 이름과 정규화 이름을 별칭 행으로도 저장해, 인물 조회와 중복 판정이
  한 인덱스를 쓴다.
- **서버 측 식별 강제:** `POST /api/entities`와 후보 accept 등 실제 인물 생성 경로는 정규화 이름·별칭이
  활성 인물(Self 포함)과 정확히 일치하면 409 `entity_identity_conflict`를 반환하고, 일치한 인물 ID를
  알려 준다. 동명이인이면 `homonym_confirmed=true`로 명시해야 만들 수 있다. 에이전트는 기존
  `/api/entities/resolve`로 먼저 조회한다. 웹 인물 추가 화면은 이 409를 받으면 기존 인물을
  보여 주고, 사용자가 동명이인이라고 확인하면 다시 보낸다.
- **보호 상태와 해석:** Self는 항상 active이며 generic PATCH로 merged/disputed 등으로 바꿀 수 없다.
  일반 인물도 merged 전이는 정식 병합 작업만 허용한다. 이름·별칭 변경 시에도 같은 충돌 검사를
  적용한다. 모든 조회는 공통 canonical resolver를 사용하고 유효하지 않은 검색 힌트를 신원 확인으로
  사용하지 않는다. 구체적인 회귀 수정은 runtime 계획이 소유한다.
- **근거 화자를 구조화:** `episodes`에 `actor_kind`(`self`·`person`·`agent`·`system`)와 nullable
  `actor_entity_id` FK를 추가한다. 기존 `actor` 문자열은 표시용으로 보존한다. 사용자 본인의 발화는
  `actor_kind=self`가 되어 표현 차이(`나`·`user`·실명)가 사라진다. 관찰 본문 속 사용자 지칭은
  observation-v1의 참여자 역할(`experiencer` 등)이 구조로 대신한다.

### M5 기록 생애주기와 계보 통일 (S8, S9)

- **상태 어휘 표준화:** 관계·관찰·프로필 사실·별칭은 `active`·`disputed`·`superseded`·`deleted`
  네 가지로 정하고 CHECK 제약을 건다. 인물은 `active`·`merged`·`deleted`로 정한다. `deprecated`를
  쓰는 코드는 `superseded`로 바꾼다. 인물의 `confirmation_status`는 `status`와 정보가 중복되므로
  제거한다(읽기 호환 필드로 일정 기간 계산해 반환).
- **대체 계보 통일:** 공통 record identity와 replacement 연결을 사용해 교차 유형·1:N·N:1을
  표현한다. 기존 `invalidated_by_edge_id`는 대응 계보로 이관한다. 단일 self-FK를 필수화하지 않는다.
  새 superseded revision의 후속 링크 존재·순환 금지는 커밋 시 보장하고, 복원 불가능한 과거 계보는
  DB에 추적 가능한 migration 예외로 남긴다. 철회에는 가짜 후속 기록을 만들지 않는다.
- **변경 이력 참조 구조화:** `memory_changes`를 공통 identity·작업에 FK로 연결하고 기존 문자열
  ref 응답과 재시도를 보존한다. 여러 후속 기록을 빠짐없이 반환한다. 병합은 원본 의미 필드를
  덮어쓰지 않고 정체성 매핑과 변경 audit를 남긴다. 세부 계약은 공통 기록 계약 2–3절을 따른다.

### M6 근거 불변식과 쓰기 경로 단일화 (S7)

- **호환 CRUD 쓰기 종료:** `POST/PATCH/DELETE /api/edges`, `/api/observations`, `/api/entity-facts`,
  `/api/episodes`의 쓰기는 410을 반환한다(또는 같은 서비스로 `/api/memories` 계약에 위임한다, Q4).
  읽기는 유지한다. 웹은 관계·관찰·사실을 이미 `/api/memories`로만 쓴다(2026-10-19 코드 확인).
  인물·별칭 CRUD는 근거 대상이 아니므로 유지한다.
- **내부 쓰기 포함:** 후보 accept/edit-accept, correction, curation, reconciliation, enrichment,
  import v1/v2와 migration까지 목록화해 공통 writer로 위임한다. 보안·승인·스냅샷 검증은 유지한다.
  일반 CRUD만 410으로 바꾼 뒤 단일화 완료를 선언하지 않는다.
- **불변식:** 모든 새 canonical revision의 episode·evidence·change가 같은 트랜잭션에 있어야 한다.
  공통 계약 4절의 FK/CHECK/커밋 시 evidence 검사로 보장하고, 연결 삭제도 검사한다. 단순 서비스
  검사나 진단 집계만으로 DB 보장을 대신하지 않는다.
- **근거 없는 기존 기록:** 출처를 만들어 내지 않는다. `evidence_status=missing_legacy` 같은 명시적
  표시를 둬서 "근거 없음"이 오류가 아니라 알려진 상태임을 구분한다. 처리 방식은 observation-v1
  5.2(이관 관찰 94건)와 같은 결정을 따른다.

### M7 프로필 사실의 값 개수 규칙 (S10)

- 사실 유형 정의에 `cardinality`(`single`·`multi`)를 둔다. 예: `birth_date`는 single,
  `email`·`phone`·`location_hint`·`job`은 multi. 실제 값은 observation-v1 Q4·Q5와 함께 정한다.
- `entity_facts`에 정규화 값 키 `value_key`를 둔다(구조화 값의 정규형 또는 정규화한 본문).
- DB 보장: NOT NULL 파생 cardinality를 정의와 FK로 일치시키고, single/multi predicate를 분리한다.
  single 키는 canonical 인물+유형, multi는 여기에 비어 있지 않은 value_key를 더한다. 공통 계약의
  기간 겹침 규칙을 적용하며, multi의 다른 값이나 겹치지 않는 과거 경력을 single 제약으로 막지 않는다.
  위반은 409와 기존 ref를 반환한다.
- 같은 장소를 다르게 쓴 경우처럼 정규화로 잡히지 않는 의미 중복은 막지 않는다. 진단 목록에만
  보고한다.

### M8 관계 평가 모델 분리 (S11)

- 관계 평가를 `relationship_assessments` payload로 분리하고 공통 record identity·근거·계보에
  연결한다. perspective/subject, axis/value와 함께 reported basis, confidence, 실제 평가/유효 시점,
  created_at/updated_at, created_by를 보존한다. 축·값은 정의 테이블 FK로 검증한다.
- 관찰 테이블에서 `perspective_entity_id`·`relationship_axis`·`relationship_value`와 인라인 CHECK를
  제거한다. 검색·컨텍스트·조회의 예외 처리도 없앤다. 평가는 임베딩하지 않는다.
- 프로필 조회는 축마다 기록 시점을 함께 반환한다. 웹은 오래된 축을 표시한다. 한 축(특히
  `connection_state`)을 바꾸면 응답에 `review_axes`로 다른 축을 다시 보라는 신호를 준다. 자동으로
  바꾸지는 않는다.
- 기존 observation ref·v2 쓰기·정정·철회·receipt를 어댑터로 해석한다. 물리 이동만으로 정정 토큰을
  바꾸지 않는다. observation-v1의 일반 관찰 assertion_mode 검증에서 평가를 분리하며 evaluation
  의미는 유지한다. 공통 계약 7절의 additive 배포→소비자 갱신→전환→검증→제거 순서를 따른다.

### M9 퇴역 열 제거 (S12)

- `sensitivity`·`ai_use_policy`·`claim_type` 열과 레지스트리 범주를 제거한다. 먼저 "immutable digest"
  계산(reconciliation commitment 등)이 이 열을 읽는지 확인한다. 읽는다면 digest 버전을 올리거나
  보관 테이블로 옮긴다(Q5).
- API 노출 정리는 observation-v1 F13과 함께 처리한다.

### M10 스키마 검증 기반 (2026-10-22 추가)

- ORM create_all과 Alembic로 생성한 DB의 차이를 비교한다. timestamp nullable 30개 차이는 원본을
  점검한 뒤 보정하고, 없는 과거 시각을 현재 시각으로 채우지 않는다. 확정 불가능한 값은 명시적인
  legacy null 계약으로 조회/정정 버전 처리를 정한 후 제약을 적용한다.
- SQLite 테스트의 FK를 켜고 대상 없는 reconciliation 요청의 flush 순서를 고친다. PostgreSQL
  전용 trigram 인덱스 등 의도적 차이는 비교 예외로 설명한다. RC 계획의 검증 기반과 공유한다.
- 최종 제약은 create_all 기반 단위 테스트뿐 아니라 Alembic upgrade, 실제 PostgreSQL FK·기간
  겹침·트리거·동시성 및 복원 리허설로 검증한다.

## 3. 기존 데이터 전환

새 제약을 걸려면 기존 행이 먼저 제약을 만족해야 한다. 값을 새로 해석하지 않고 구조만 맞춘다.
기존 `MemoryMigrationService` manifest 방식(dry-run, 멱등, 원본·근거·이력 보존)을 쓰고, 개인 내용이
담긴 manifest는 저장소 밖에 둔다.

| 제약 | 전환 대상(2026-10-19) | 처리 |
| --- | --- | --- |
| M1 정규 순서·유일성 | 무방향 현재 관계 7건, 그중 중복 2쌍 | 원본 payload·source를 보존하고 canonical 키를 정규화한다. 새 revision이 필요하면 대체 계보를 남긴다. 확인된 중복은 원본별 근거·import 증명을 보존해 통합한다. |
| M2 슬롯 | 위반 0건 | 마이그레이션 사전 검사만 한다. |
| M4 Self | 사용자 본인으로 확인된 별도 인물 1명(관찰 5, 사실 2, 링크 3) | migration 전용 정체성 매핑으로 Self에 귀속한다. 원본 refs를 보존하고 Self는 active로 유지한다. 이름·별칭을 설정한다. 일반 Self 병합 금지를 해제하지 않는다. |
| M4 근거 화자 | episode 215건 | `actor` 값으로 판정 가능한 것만 `actor_kind`·`actor_entity_id`를 채우고 나머지는 null로 둔다. |
| M5 상태·계보 | 대체 링크 없는 superseded 관계 3건, 관찰 27건, 사실 12건 | 모든 확인 가능한 교차 유형·복수 후속 링크를 채운다. 복원 불가능한 것은 DB의 migration 예외로 추적한다. |
| M6 근거 | 근거 없는 현재 기록 102건 | `missing_legacy` 표시만 한다. |
| M7 값 개수 | 같은 유형·같은 키 현재 사실 | 정규화 키가 같은 것만 하나로 합친다. 의미만 같은 것은 진단 목록으로 보낸다. |
| M8 평가 분리 | 현재 평가 11건과 이력 | 공통 identity에 연결해 payload를 이동한다. 기존 ref·토큰·시점·근거·receipt 호환을 검증한 뒤에만 구 저장 구조를 제거한다. |
| M10 timestamp | 생성 DDL과 ORM의 nullable 차이 30개 | 실제 null 여부를 전환 직전 조사한다. 과거 시각을 조작하지 않고 정한 legacy 계약에 따라 보정/예외 처리한다. |

절차: 백업 → 격리 복사본 복원 → 스키마 마이그레이션(제약 없이 열 추가) → manifest dry-run·적용 →
제약 활성화 마이그레이션 → readback(제약 위반 0, 근거·이력 수 보존, 인물·기억 화면, context card) →
**사용자 승인 후 라이브** 같은 순서. 제약 활성화 마이그레이션은 위반 행이 남아 있으면 ID만 출력하고
중단한다.

## 4. 수용 기준

| ID | 완료 조건 |
| --- | --- |
| MI01 | 기간이 겹치는 같은 무방향 관계의 반대 방향 입력은 409이고 DB도 거절한다. 방향 관계의 반대 방향과 겹치지 않는 과거 기간은 허용한다. |
| MI02 | 관계의 directed·NOT NULL slot_key는 정의와 FK로 일치하고 NULL 슬롯 우회는 거절된다. |
| MI03 | 같은 슬롯의 기간 중복은 409다. 정정과 실제 관계 변화를 구별하며 원본·대체 계보·과거 기간을 보존한다. |
| MI04 | 관계·관찰 유형 정의는 저장소가 하나이며, 시드 재실행 시 갱신된다. |
| MI05 | Self 이름이나 별칭과 같은 인물 생성은 409 `entity_identity_conflict`이고, `homonym_confirmed`로만 우회된다. |
| MI06 | 새 episode는 `actor_kind`를 갖고, 사용자 본인의 발화는 경로와 관계없이 `self`다. |
| MI07 | 상태 CHECK와 공통 계보가 교차 유형·분할·통합을 지원하며 새 superseded revision의 후속 링크 누락/순환은 커밋되지 않는다. |
| MI08 | 호환 CRUD는 410 또는 공통 writer로 위임되고, 후보·내부 executor·import까지 새 canonical 기록의 근거·이력을 DB 커밋 시 보장한다. |
| MI09 | 기간이 겹치는 single 값·multi 같은 키는 409다. multi 다른 키와 겹치지 않는 기간은 허용하고 틀린 cardinality/빈 value_key는 거절한다. |
| MI10 | 관계 평가는 별도 테이블에 있고 임베딩되지 않는다. 프로필 조회가 축별 기록 시점을 주고, 웹은 오래된 축을 표시한다. |
| MI11 | 전환은 복원 리허설, dry-run, 재실행 멱등성, 원본·근거·이력 보존을 만족하고, 제약 활성화 후 위반 0건이다. |
| MI12 | 백엔드·프런트엔드 테스트, lint, 빌드, 브라우저 확인과 Hermes 계약 갱신 확인을 통과한다. |
| MI13 | 병합 후 import 원본 payload·authorization 검증·이전 refs가 보존되고 canonical 대상 기준의 충돌은 원자적으로 처리한다. |
| MI14 | Self 비활성화와 generic merged 전이는 거절되고, A→B→C 조회가 공통 canonical 대상에 도달한다. |
| MI15 | 모든 후보 상태 전이는 잠금 후 최신 상태를 검사하고 accept와 stale reject 경합이 canonical/audit 불일치를 만들지 않는다. |
| MI16 | SQLite FK ON과 PostgreSQL에서 missing-target 요청이 정해진 404/409로 종료되며 부분 ledger/record가 남지 않는다. |
| MI17 | Alembic/ORM nullable 차이와 의도적 전용 인덱스 차이를 설명하고 실제 migration DB에서 제약을 검증한다. |
| MI18 | assessment old ref·v2 재시도·시점·정정 토큰·원본 근거가 물리 이동 뒤 보존되고 일반 관찰과 중복 저장되지 않는다. |
| MI19 | 부분 날짜 경계의 uncertain 판정이 목록·카드·검색·DB 겹침 검사에 일치하며 날짜를 발명하지 않는다. |
| MI20 | 기존 소비자 호환과 복원 리허설을 통과한 후에만 구 열·ref 어댑터를 제거한다. |

## 5. 실행 단위

2026-10-22 변경: 기존 PR A–F 이름을 유지하지만 **B를 A보다 먼저** 수행한다. 계보와 원본
보존 기반 없이 관계를 정규화하거나 이전 writer를 종료하지 않는다.

1. **선행 RC 안전 수정·검증:** Self·후보 경합·FK 순서·공통 resolver, M10의 검증 기반.
2. **PR B — 생애주기·쓰기 경로·근거:** M5, M6와 공통 계약 LC01–LC04, RC 병합/provenance 수정.
3. **PR A — 관계 정체성·슬롯·정의 단일화:** M1, M2, M3와 LC05–LC06. 제약 활성화는 전환 뒤로 분리한다.
4. **PR C — 인물 정체성·근거 화자:** M4. 선행 안전 수정 위에 충돌 UX·actor 구조화를 추가한다.
5. **PR D — 사실 값 개수:** M7. observation-v1의 사실 유형 정리와 같은 PR로 합칠 수 있다.
6. **PR E — 관계 평가 분리:** M8, 웹·소비자 호환 포함. observation-v1 2단계와 공동 배포한다.
7. **PR F — 퇴역 열 제거:** M9. 과거 digest 검증·소비자 호환 확인 후 진행한다.
8. **전환 도구와 라이브(각각 별도 승인):** manifest 연산 추가 → 복사본 전체 리허설 → additive
   서버/어댑터 배포 → 웹·CLI/helper·Hermes 갱신 및 구/신 계약 호환 확인 → 라이브 자료 전환 →
   제약 활성화 → 모든 소비자·근거·계보 readback → 구 저장 구조/어댑터 제거 조건 판정.

## 6. 구현 전 확정할 결정

| ID | 질문 | 이 계획의 권장안 |
| --- | --- | --- |
| Q1 | 무방향 관계 정규 순서를 기존 기록에도 적용할지 | 현재 canonical 키에 적용한다. 원본 payload·digest를 직접 바꾸지 않고 필요한 교체는 계보를 남긴다. |
| Q2 | 관계 슬롯(상호 배타성)을 도입할지 | 도입한다. 동시 현재 관계만 막고 충돌 해결 모델은 계속 보류한다. |
| Q3 | 동명이인 인물 생성 방식 | `homonym_confirmed=true` 명시를 요구한다. |
| Q4 | 호환 CRUD 쓰기 경로 | 일반 저수준 CRUD는 종료(410)를 권장한다. 유지되는 후보·import·실행 경로는 기존 인증을 유지하며 공통 writer로 위임한다. |
| Q5 | 퇴역 열이 digest에 쓰일 때 | digest 버전을 올리고 열을 제거한다. 이전 digest 검증이 필요하면 보관 테이블로 옮긴다. |
| Q6 | 관계 평가 분리 시점 | observation-v1 2단계 스키마 변경과 같은 배포 창에서 한다. 관찰 테이블 변경이 두 번 일어나지 않게 하기 위해서다. |
| Q7 | 공통 정체성·근거·기간 제약의 물리 DDL | 공통 기록 계약의 테이블/FK/커밋 트리거/배제 제약 안을 격리 PostgreSQL에서 검증한 뒤 구현 PR에 확정한다. |
| 확정 | 사용자 이름으로 만들어진 별도 인물이 본인인지 | **2026-10-19 사용자 확인:** 본인이다. M4 전환에서 Self로 합친다. |
