# 런타임 무결성과 검색 동작 보완

- 기준일: 2026-10-22.
- 상태: **계획, 미구현.** 이번 변경은 검토 결과와 실행 순서를 문서로 정리한 것이다.
  코드 수정, 배포, 운영 데이터 전환을 완료했다는 뜻이 아니다.
- 근거: [스키마·로직 검토 기록](../verification/schema-logic-review-2026-10-22.md).
- 공통 규칙: [기록 생애주기 계약](record-lifecycle-contract.md). 교차 유형·1:N 계보,
  원본과 canonical 인물 투영, 근거의 DB 보장, 유효 시간과 현재성은 그 문서가 소유한다.
- 관련 계획: [데이터 모델 무결성](data-model-integrity.md),
  [임베딩 자동 생성](embedding-auto-index.md), [save-first](save-first-memory-schema.md).

## 1. 목표와 범위

새 스키마를 기다릴 필요가 없는 보호·동시성·조회 오류를 먼저 고친다. 이어서 기존 후보·병합·내부
쓰기 경로를 공통 생애주기 계약에 맞추고, 저장된 벡터가 실제 검색에 쓰이는 조건을 명확히 한다.
새 온톨로지나 자동 의미 분류, 운영 데이터에 대한 자율 수정은 범위 밖이다.

검토 시점의 `/api/memories`는 요청 ID 예약, 이전 행 잠금, 근거·변경 이력의 단일 트랜잭션을
구현했다. 문제는 이 경계를 우회하는 경로와 읽기·검색 경로 간 동작 차이다. 기존 SF·MI·EA 수용
기준을 대체하지 않고, 아래 RC 기준을 추가한다.

## 2. RC-A — 독립적으로 먼저 고칠 안전 조건

### 보호된 Self와 후보 상태 전이

- Self는 항상 `active`여야 한다. 일반 Entity PATCH가 `merged` 등으로 바꾸거나 보호 역할을
  제거할 수 없어야 한다. 일반 인물도 병합 영수증 없이 PATCH로 `merged`가 될 수 없다.
- 엔티티와 기록의 상태 검증을 분리한다. 여러 모델의 상태 집합을 합쳐 검사하지 않는다.
- 후보 accept뿐 아니라 reject/archive/clarify/supersede도 같은 후보 잠금을 획득한 뒤 최신 상태를
  읽어 전이 가능성을 검사한다. 이미 수락된 후보를 오래된 객체가 거절로 덮어쓰면 409이며,
  canonical 행·후보·감사 결과가 함께 유지되어야 한다.
- curation/reconciliation 내부에서 이미 잡은 잠금·트랜잭션을 재사용한다. 내부 호출 때문에
  중간 commit이 생기지 않도록 public 경계와 트랜잭션 참여 함수를 구분한다.

### FK 오류와 테스트·마이그레이션 동등성

- reconciliation은 요청의 target과 snapshot 대상을 확인한 뒤 FK를 가진 action을 flush한다.
  대상 없음은 404, 오래된 snapshot은 409이며, DB 오류/500 또는 잔여 ledger·episode를 남기지 않는다.
  요청 ID 경합 처리와 정렬된 잠금 순서는 유지한다.
- SQLite 연결마다 FK를 활성화하고 테스트 시작 시 실제 활성 상태를 확인한다. 검증을 통과하려고
  FK를 끄거나 임의의 부모 행을 만드는 방식은 금지한다.
- `Base.metadata.create_all()` 테스트와 별개로 빈 DB에서 Alembic head까지 생성한 스키마를
  검사한다. 모델과 마이그레이션의 nullable·FK·CHECK·unique/index·default 차이를 목록화한다.
- 초기 마이그레이션의 timestamp nullable 차이는 새 수정 마이그레이션으로 해결한다. 기존 null
  값이 있다면 원본 시각을 임의로 만들어 채우지 않고, 전환 규칙과 예외를 먼저 확정한다.
  이미 적용된 과거 마이그레이션을 편집해 새 DB와 기존 DB를 다르게 만들지 않는다.
- PostgreSQL에서도 핵심 FK·상태 경합·rollback 회귀를 실행한다. SQLite 통과로 PostgreSQL 행 잠금
  검증을 대신하지 않는다. 운영 DB 대신 격리된 테스트 DB를 사용한다.

### canonical 인물 조회와 힌트

- [공통 계약](record-lifecycle-contract.md)의 canonical identity resolver를 context-card, graph,
  memory 읽기, retrieval hints/focal ID가 함께 사용한다. A→B→C 병합은 C까지 해석한다.
- 원래 저장된 record의 대상 ID와 증명은 그대로 두고, 현재 사용자 화면·검색에서 사용할 canonical
  ID를 별도로 투영한다. 과거 참조를 조회했다는 이유로 기록을 다시 저장하지 않는다.
- resolver는 순환, 없는 대상, 삭제된 끝점에 대한 명시적 실패 결과와 탐색 한도를 가진다.
  유효하지 않은 체인을 임의의 사람으로 해석하거나 반복해서 따라가지 않는다.
- `entity_hints`는 canonical active 인물로 검증한 뒤 사용한다. 없는 ID, 삭제된 ID, 해석 실패한
  병합 ID는 유효한 식별 근거가 아니다. 진단을 반환하되 이런 힌트 때문에 동명이인 모호성을 끄지
  않는다. 복수의 유효한 힌트도 그 자체로 단일 인물 식별을 증명하지 않는다.

RC-A는 RC-B나 MI의 대규모 스키마 전환 완료를 기다리지 않는다. resolver의 원본 보존 의미는 공통
계약을 따른다. 새 계보 스키마를 먼저 도입할 필요는 없다.

## 3. RC-B — 병합과 모든 canonical writer 통합

이 단계는 공통 계약과 MI의 생애주기·근거 실행 단위를 **함께 구현**한다. RC 완료를 MI의 선행
조건으로, MI 완료를 RC의 선행 조건으로 동시에 두지 않는다.

- 후보 accept/edit-accept, fact promote, curation, reconciliation, enrichment, material import,
  일반 memory 쓰기, 승인된 migration 도구를 포함한 writer 목록을 만든다. 외부 CRUD 라우트만
  410으로 바꾸는 것으로 쓰기 단일화를 완료했다고 판단하지 않는다.
- 도메인 내부의 canonical 쓰기도 원본·근거·계보·변경 이력을 원자적으로 남기는 공통 서비스에
  참여시킨다. 내부에서 HTTP를 재호출하거나 별도 commit을 만들지 않는다. 기존 import authorization,
  reconciliation binding, bounded source, idempotency와 readback 계약을 보존한다.
- 신규 현재 기록은 공통 계약의 DB 근거 불변식을 만족해야 한다. 근거 없는 legacy 행은 명시된
  예외 상태로 다루며, 입력 주체가 `user`라는 이유만으로 신규 무근거 행을 허용하지 않는다.
- 병합은 기존 fact·edge·observation의 대상과 participant를 덮어쓰지 않는다. canonical 인물 투영과
  기록의 의미 변경을 구분하고, 의미 변경이 필요한 경우에만 새 revision과 명시적 계보를 만든다.
  중복 통합 때도 각 원본과 근거를 조회할 수 있어야 한다.
- V2 import manifest와 payload digest는 원본 기준으로 계속 검증되어야 한다. 병합 이후 현재 인물
  화면에 표시할 때도 authorization/source proof를 잃지 않는다. 증명을 맞추려고 기존 manifest나
  digest를 덮어쓰지 않는다. V1 candidate linkage, reconciliation readback도 함께 회귀한다.
- 동일 요청 재시도는 처음 영수증을 반환하고, 그 영수증이 가리키는 원본 의미가 뒤에서 달라지지
  않아야 한다. 병합 결과와 관련 변경 이력은 별도로 추적한다.

## 4. RC-C — 실제 검색에 연결되는 임베딩

### EA와의 소유권

| 책임 | 소유 계획 |
| --- | --- |
| canonical 저장 후 observation 벡터 생성, sweep·retry·재색인·내용 토큰 불변성 | [EA](embedding-auto-index.md) |
| 검색 요청의 query 벡터 생성, caller vector 호환, 비교 가능성 판단, fallback·검색 설명 | 이 계획 RC-C |
| 어떤 기록이 현재이고 검색 대상인지, 관계 평가의 위치 | [공통 계약](record-lifecycle-contract.md), MI·OV |

EA의 저장 후 indexing만 끝나도 일반 텍스트 검색이 의미 검색으로 바뀐다고 주장하지 않는다.
RC-C는 EA 자동화 완료 전에도 이미 생성된 호환 벡터를 대상으로 구현·검증할 수 있다. 두 단계가
공유하는 모델·차원·전처리 식별 계약을 먼저 확정하고, 각 단계의 완료를 서로 기다리게 하지 않는다.

### query 벡터와 호환 계약

- 일반 Web·CLI·agent의 텍스트 검색은 검색 서버가 query embedding을 생성하는 방식을 권장한다.
  요청당 제한된 timeout과 호출 횟수를 두고, disabled·timeout·provider 실패 때 lexical 검색으로
  내려간다. 검색 실패가 저장 성공이나 이미 저장된 기록을 바꾸지 않는다.
- 기존 `query_embedding` 입력 형식은 전환 기간에 수용하되 모델·차원·전처리 식별 정보를 추가한다.
  벡터 차원이 같다는 사실만으로 같은 공간이라고 보지 않는다. 메타데이터가 없는 기존 caller
  vector는 호환성을 추측해 비교하지 않고 서버 생성 벡터를 사용하거나 lexical fallback과 원인을
  반환한다. 검증 가능한 metadata를 보낸 caller vector는 재생성 없이 사용할 수 있다.
- query와 저장 벡터는 유한한 수, 비어 있지 않은 값, 0이 아닌 norm, 일치하는 차원과 같은 embedding
  공간을 만족해야 한다. 잘못된 명시적 vector 입력은 문서화한 422로 거절한다. 손상된 저장 벡터는
  검색에서 제외하고 재색인 진단으로 분류한다.
- 검색은 `embedding_status=ready`이면서 현재 query와 호환되는 벡터만 비교한다. 같은 차원의 다른
  모델, `stale`/`failed`/`pending`, 차원 불일치는 의미 점수에 기여하지 않는다. 적합한 lexical
  결과는 계속 사용할 수 있다. 모델 변경 시 재색인 표시는 EA가 담당한다.
- 설정값 존재만으로 실제 provider 연결·색인 준비·검색 준비가 모두 `ready`라고 표시하지 않는다.
  설정 유효성, 마지막 실제 생성 결과, 현재 검색 가능한 벡터 건수, 이번 요청의 사용 모드를 구분한다.
  status 조회 자체가 불필요한 외부 호출을 일으키지 않게 한다.
- lexical 점수가 높다는 이유로 `pgvector_observation`을 붙이지 않는다. observation와 entity-level
  설명 모두 실제 기여한 lexical/semantic/recency/hint 신호만 표시한다. DB pgvector 연산을 사용하지
  않는 구현이라면 semantic 유사도와 DB 검색 실행을 혼동시키지 않는 명칭을 사용한다.

참여자 역할을 검색 후보/점수에 반영하는 확장은 OV의 역할 의미와 별도 검색 계약을 확정한 뒤 한다.
현재 subject 중심 retrieval의 한계는 검토 기록에 남기며 이 계획의 최소 완료 조건에 몰래 포함하지
않는다. 원본 participant 보존과 canonical 투영은 RC-B의 필수 조건이다.

## 5. 수용 기준

| ID | 필수 검증 |
| --- | --- |
| RC01 | Self의 비활성화·역할 제거와 일반 PATCH의 가짜 merged 전이가 거절되고 보호된 active Self가 유지된다. |
| RC02 | accept와 reject/archive/clarify/supersede 경합에서 하나의 유효 전이만 완료된다. 수락된 canonical 행과 rejected 후보 조합이 생기지 않는다. |
| RC03 | 없는 reconciliation target은 FK를 켠 DB에서 404, stale snapshot은 409이며 action·episode·candidate·canonical 부분 저장이 없다. |
| RC04 | 모든 SQLite 테스트 연결에서 FK가 켜져 있다. 핵심 FK/동시성 회귀가 격리 PostgreSQL에서도 통과한다. |
| RC05 | Alembic head 생성 스키마와 ORM의 차이가 검사되며 nullable·FK·CHECK·index·default의 설명 없는 차이가 없다. 기존 DB 수정 마이그레이션도 검증한다. |
| RC06 | 실제 A→B→C 병합 뒤 A/B/C context-card·graph·memory·hint가 같은 canonical 인물로 해석된다. 순환·누락·삭제 끝점은 정해진 오류를 낸다. |
| RC07 | 무효 hint나 복수 hint가 동명이인 모호성을 숨기지 않는다. hint 없음과 무효 hint만 있음의 식별 안전성이 같다. |
| RC08 | 병합 뒤 원래 record payload·participant·import manifest/digest·증명이 보존된다. 현재 인물 투영과 병합 이력은 조회 가능하고 재시도 영수증의 의미가 변하지 않는다. |
| RC09 | 모든 writer가 공통 트랜잭션·근거·계보·이력 계약을 만족한다. 무근거 user 후보 accept도 신규 현재 행을 만들지 못하며 실패·재시도는 부분 저장이나 중복을 남기지 않는다. |
| RC10 | 일반 텍스트 Web·CLI·API 검색이 서버 query 벡터로 의미상 관련된 비동일 어휘 기록을 찾는다. provider 실패·비활성일 때 lexical 결과와 fallback 이유가 일치한다. |
| RC11 | caller vector 호환 정책이 문서화되고, 같은 차원의 다른 모델·stale·차원 불일치·비유한값·zero norm은 의미 비교에 쓰이지 않는다. |
| RC12 | 설정 상태·마지막 provider 생성 결과·호환 색인 건수·요청별 검색 모드가 구분된다. 설정만 존재하거나 오래된 벡터만 있을 때 검색 준비 완료로 오인시키지 않는다. |
| RC13 | lexical-only 결과에는 semantic/pgvector 근거가 붙지 않는다. entity와 observation의 설명이 실제 점수 기여와 일치한다. |
| RC14 | 관련 backend/CLI/frontend 회귀, scoped lint, build를 통과한다. UI 표시 변경은 브라우저에서 확인하며 라이브 검증은 별도 승인된 배포 단계에서 기록한다. |

## 6. 실행과 회귀 재현

1. **RC-A:** Self·후보 상태 경합, reconciliation FK 순서, FK 활성 테스트·schema parity, 공통 resolver와
   hint 검증. 서로 독립적인 수정은 작은 PR로 나눌 수 있다. RC01–RC07을 완료 조건으로 둔다.
2. **RC-B + MI 생애주기·근거:** 공통 계약을 확정한 뒤 writer inventory와 병합/증명 보존을 함께
   구현한다. RC08–RC09와 해당 MI/LC 기준을 같은 리뷰에서 검증한다. 운영 전환은 별도 단계다.
3. **RC-C + EA 연결 확인:** query/index 책임을 나눠 구현하고 일반 사용자 검색을 끝까지 확인한다.
   RC10–RC13과 EA의 저장·재색인 조건을 각각 충족해야 전체 의미 검색 경로 완료다.
4. **회귀·적용:** 각 PR에 RC14를 적용한다. 기존 SF·curation·reconciliation·import acceptance를
   삭제하지 않는다. 승인된 운영 배포 이후에는 적용 revision과 비밀 없는 readback을 별도 기록한다.

최소 재현 시나리오는 [검토 기록](../verification/schema-logic-review-2026-10-22.md#합성-회귀-재현)에
있다. 임시 스크립트의 파일명이나 개발자 로컬 DB에 의존하지 않고 정식 합성 fixture/test로 옮긴다.
