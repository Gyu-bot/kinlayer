# 2026-10-22 계획·DB·온톨로지·로직 검토 기록

## 기준과 증거의 범위

계획 PR 병합 및 로컬 최신화 뒤의 `main` **`5df21a3`**를 대상으로 수행한 검토다. 이 문서는 그
검토의 결과와 후속 계획 소유권을 기록한다. 현재 문서 정리 작업에서 아래 테스트를 다시 실행했다는
뜻이 아니며, 후속 계획은 모두 구현 완료와 구분한다.

- 당시 활성 계획 8개, ORM 테이블 24개, Alembic 마이그레이션 13개를 조사했다.
- 대상 계획: save-first, frontend-rebuild, relationship-ontology, relationship-curation-cycle,
  relationship-reconciliation-cycle, embedding-auto-index, observation-ontology-v1,
  data-model-integrity. 이번에 추가하는 공통 생애주기·runtime 계획은 이 8개에 포함하지 않는다.
- 모델·마이그레이션·레지스트리·API/서비스/CLI·검색/컨텍스트·프론트엔드 계약을 대조했다.
  병합, 상태 전이, FK, 검색 문제는 합성 데이터와 격리 SQLite로 재현했다.
- 운영 DB의 실제 스키마·데이터는 확인하지 못했다. `casa` SSH 경로가 Tailscale 추가 인증을 요구해
  중단됐으며 인증을 우회하지 않았다. 과거 계획의 라이브 수치는 당시 기록이고 이번 확인값이 아니다.
- 코드·서비스·운영 데이터 수정이나 배포는 이 검토의 결과가 아니다. PostgreSQL 잠금 경합의 실제
  실행 결과도 주장하지 않는다.

## 당시 검증 결과

| 검사 | 결과와 한계 |
| --- | --- |
| 기본 backend 전체 테스트 | **773 passed, 3 skipped**. 기본 SQLite fixture의 FK 비활성 조건을 함께 해석해야 한다. |
| SQLite FK 활성화 후 backend 전체 테스트 | **772 passed, 1 failed, 3 skipped**. 아래 RV04의 실제 FK 순서 오류가 드러났다. |
| frontend 테스트 | **110 passed**. 별도 브라우저 운영 검증을 뜻하지 않는다. |
| frontend production build | 통과. |
| backend/scripts scoped lint | 통과. |
| 저장소 루트 lint | 당시 저장소 안에 있던 비추적 과거 작업 자료에서 **62건 실패**. 제품 코드 scoped 통과와 구분한다. 해당 원자료는 이후 문서 정리에서 저장소 밖 비공개 보관소로 이동했으며 이 수치는 이동 전 검사 결과다. |
| OpenAPI 대조 | **63개 path / 165개 schema**의 비교 대상이 일치했다. 계약 일치는 동작 정확성 증명이 아니다. |
| 합성 회귀 | Self PATCH, 병합 원본·import proof, 후보 상태 경합, 내부 writer 우회, 다단 병합 및 검색 경계 재현. |
| 라이브 DB | 추가 인증으로 접근 불가. 실제 운영 스키마 일치·제약 활성·데이터 정합성은 이번 결과에 포함하지 않는다. |

FK 활성 시 실패한 기존 테스트는
`backend/tests/test_reconciliation_api.py::test_existing_entity_observation_group_rejects_invalid_target_entity[target_change4-404-not_found]`
다. 404를 기대하지만 대상 검증 이전 action flush가 FK를 위반한다. 기본 테스트 통과로 이 오류를
해결됐다고 판단하면 안 된다.

## 발견 목록과 실행 소유권

`확인`은 코드 경로 또는 합성 재현에서 확인한 현재 문제다. `계획 보완`은 미구현 설계를 그대로
실행하기 전에 확정해야 할 조건이며, 이미 발생한 운영 장애로 표현하지 않는다. `보류`는 범위를
명시한 후속 작업이다. 우선순위는 이 검토 기준이며, 운영 발생 빈도 추정은 아니다.

| ID | 구분·우선순위 | 발견과 근거 | 실행 소유권 |
| --- | --- | --- | --- |
| RV01 | 확인 P1 | 후보 merge가 기존 fact/edge/observation 대상과 participant를 직접 바꾼다. V2 import의 같은 ref에서 proof가 사라지고 MemoryChange는 create만 남는다. `services/candidates.py`의 merge helper, `services/material_provenance.py`의 payload digest 비교. | [RC08](../plans/runtime-correctness.md#5-수용-기준) + [공통 계약](../plans/record-lifecycle-contract.md), MI 생애주기 |
| RV02 | 확인 P1 | 일반 Entity PATCH가 Self의 `status=merged`를 받아 active Self를 없앤다. `services/entities.py`는 deleted만 막고 공통 상태 합집합을 허용한다. | RC01; MI 인물/상태 제약과 함께 회귀 |
| RV03 | 확인 P2 | accept 후 오래된 세션의 reject가 후보 상태를 rejected로 덮어쓰고 canonical 인물은 active로 남긴다. `CandidateService._resolve`에 최신 상태 잠금이 없다. | RC02 |
| RV04 | 확인 P2 | reconciliation action의 target FK flush가 대상 검증보다 먼저여서 없는 target 요청이 예상 404 대신 IntegrityError를 낸다. FK 활성 기존 테스트로 확인. | RC03–RC04 |
| RV05 | 확인 P2 | 기본 SQLite 테스트가 FK를 보장하지 않아 RV04를 놓친다. ORM `TimestampMixin`의 NOT NULL과 초기 Alembic timestamp nullable도 30개 다르다. PostgreSQL 전용 trigram 인덱스 4개는 migration에만 있으며 의도적 차이 여부를 구분해야 한다. | RC04–RC05 |
| RV06 | 확인 P2 | 실제 A→B→C 병합 후 A context-card는 404, C는 200, A memories는 200이다. `ContextService._redirect_merged_entity`는 한 단계만 따라간다. | RC06, 공통 canonical resolver |
| RV07 | 확인 P2 | 존재하지 않는 ID도 hints가 비어 있지 않으면 ambiguity를 끈다. `RetrievalService._is_ambiguous`가 hint 유효성을 확인하지 않는다. | RC07 |
| RV08 | 확인 P2·계획 보완 | user 후보에 evidence 없이 observation을 넣고 accept하면 active 행이 생기지만 evidence/MemoryChange는 없다. 일반 CRUD 종료만으로 후보·curation·reconciliation·enrichment 내부 writer가 닫히지 않는다. | RC09 + MI 쓰기 단일화 + 공통 근거 계약 |
| RV09 | 확인·계획 보완 P2 | 일반 텍스트 요청은 query embedding을 만들지 않는다. 합성 `espresso` 질의가 vector 없이 0건, 명시적 호환 vector로 1건이었다. 현행 optional caller 계약 자체의 위반은 아니지만 저장 벡터 자동 생성만으로 사용자 의미 검색 목표를 충족하지 못한다. | RC10 query 경로; EA는 저장 후 색인 |
| RV10 | 확인 P2 | 같은 차원의 다른 모델과 stale 저장 벡터도 검색에 쓰인다. 설정 기반 provider ready는 실제 검색 준비를 증명하지 않는다. | RC11–RC12, EA 재색인 연계 |
| RV11 | 확인 P2 | lexical-only `coffee` 일치에도 entity-level `pgvector_observation` 근거가 붙는다. semantic/lexical 중 최대 점수를 semantic 근거로 재사용한다. | RC13 |
| RV12 | 확인·계획 보완 | 임베딩 갱신이 correction concurrency token을 바꾼다. SQLAlchemy Core UPDATE도 onupdate를 그대로 두면 timestamp가 바뀌는 재현을 확인했다. | [EA04](../plans/embedding-auto-index.md); derived update의 토큰 불변 구현·회귀 |
| RV13 | 계획 보완 | M5의 유형별 단일 self-FK만으로 save-first의 교차 유형 정정과 1:N 분할 계보를 표현할 수 없다. 원본 보존·현재 인물 투영도 함께 정해야 한다. | [공통 계약](../plans/record-lifecycle-contract.md), MI 생애주기 |
| RV14 | 계획 보완 | 상태만 보는 unique는 valid_from/valid_to와 충돌한다. 미래·만료 기록의 슬롯 점유와 부분 날짜 종료 경계 의미를 확정해야 한다. | 공통 temporal 계약, MI 관계/사실 슬롯, OV 시간 |
| RV15 | 계획 보완 | nullable slot 복합 FK와 single/multi partial unique는 제약을 단순 나열해서 보장되지 않는다. FK의 NULL 의미, 판정 열의 정의 일치와 predicate를 실행 가능한 DDL로 확정해야 한다. | MI 관계 슬롯·사실 cardinality |
| RV16 | 계획 보완 | 근거 존재를 서비스 종료 검사에만 맡기면 다른 writer/SQL이 우회한다. 관계 평가 분리의 필드·계보·시간 계약도 MI와 OV 사이에서 하나로 정해야 한다. | 공통 근거 계약, MI 관계 평가·쓰기, OV |
| RV17 | 보류 | participant로 연결된 기억은 카드/기억 읽기에서 보이지만 subject 중심 retrieval 후보·점수와 같지 않다. 참여자 역할별 검색 확장은 의미와 scoring 계약이 필요하다. | OV 역할 정리 이후 별도 검색 확장; RC 최소 완료와 구분 |

현재 구현의 관계 중복·정의 저장소 분산·legacy 상태와 미근거 기록 문제는 MI의 기존 S1–S12 진단과
겹친다. 이를 모두 새 발견으로 세지 않는다. 반대로 M6의 내부 writer 누락, M5의 1:N/교차 유형
불일치처럼 기존 계획을 실행해도 남는 부분은 위 목록에서 별도 추적한다.

## 합성 회귀 재현

아래는 기존 검토에서 사용한 조건을 지속 가능한 테스트로 옮기기 위한 절차다. 개발자 `/tmp` 파일이나
운영 인물·발췌·인증정보에 의존하지 않는다. 임시 DB, 가상 인물, provider stub을 사용한다.

### Self와 후보 상태

1. 테스트 앱에 보호된 Self를 만든다. `PATCH /api/entities/{self_id}`에 `{"status":"merged"}`를
   보낸다. 검토 시점에는 200이며 active Self 조회는 0건이었다. 수정 후에는 거절과 active 유지가
   기대값이다.
2. pending new_entity 후보를 세션 A에서 읽는다. 세션 B가 accept와 commit을 마친 뒤 A가 이미 읽은
   객체로 reject한다. 검토 시점에는 rejected 후보와 active canonical 인물이 함께 남았다. 수정 후
   stale 전이는 409여야 한다. 실제 병렬 경합은 격리 PostgreSQL에서도 검증한다.

### 병합·증명·다단 인물 해석

1. 가상 source와 target을 만든다. V2 material import로 source의 typed fact와 observation을 저장하고
   모든 source의 `material_provenance`가 있는지 확인한다. 기존
   `backend/tests/test_material_imports_v2.py`의 합성 manifest 구성을 사용할 수 있다.
2. source→target merge 후보를 만들고 accept한다. 검토 시점에는 같은 record ID의 대상이 바뀌고
   source proof가 응답에서 사라지며, record별 MemoryChange는 최초 create 한 건뿐이었다.
   수정 후에는 원본 payload와 proof를 그대로 검증할 수 있고 현재 인물은 별도 투영돼야 한다.
3. 별도의 세 인물 A/B/C를 실제 API로 만들어 A→B, B→C를 차례로 병합한다. A/B/C의 context-card,
   graph, memory 및 hint를 비교한다. 검토 시점 A context-card 404 / C context-card 200 /
   A memories 200을 재현했다. 수정 후 모든 정상 체인이 같은 canonical 인물로 이어져야 한다.
4. 순환·없는 target·삭제된 끝점은 별도 합성 fixture로 만들고 resolver가 안전하게 실패하는지
   검사한다. 운영 DB에 손상된 체인을 만드는 방식은 사용하지 않는다.

### 내부 writer와 FK

1. `created_by=user`, `evidence=[]`로 observation 후보를 생성하고 accept한다. 검토 시점에는
   active observation이 생기지만 evidence와 MemoryChange가 모두 0건이었다. 중앙 writer 전환 후
   신규 무근거 기록이 생기지 않는지, 실패가 후보·canonical 일부만 저장하지 않는지 확인한다.
2. SQLite DB 연결에 `PRAGMA foreign_keys=ON`을 적용하고 실제 값을 확인한다. 위의 existing-target
   reconciliation 테스트를 실행한다. 검토 시점에는 `ReconciliationService.apply`가 action을 먼저
   flush하여 IntegrityError가 났다. 수정 후 HTTP 404와 전체 무변경을 확인한다.
3. 빈 격리 DB를 Alembic head로 생성한 뒤 ORM schema와 비교한다. create_all로 만든 DB만 검증하면
   timestamp nullable 등 migration 차이를 놓칠 수 있다. 기존 데이터를 모사한 upgrade도 별도 검증한다.

### 검색·벡터·시간 토큰

1. lexical 어휘가 겹치지 않지만 stub query vector와 가까운 observation을 만든다. 일반 텍스트
   검색과 명시적 vector 검색을 비교한다. query/index 양쪽 경로가 연결돼야 차이가 해소된다.
2. 같은 차원·다른 모델, stale, 차원 불일치, 0 norm, 비유한값, provider failure/disabled를 각각 넣어
   의미 점수 사용 여부와 lexical fallback·진단을 확인한다. 외부 provider를 호출하지 않는다.
3. lexical-only 질의와 없는 entity hint를 각각 넣는다. semantic 설명을 붙이지 않는지, 원래
   동명이인 모호성이 숨겨지지 않는지 검사한다.
4. observation의 `updated_at`을 읽고 임베딩 열만 ORM/Core 경로로 갱신한 뒤 같은 시각으로 correction을
   보낸다. 수정 후 색인 때문에 stale-write 409가 나지 않아야 한다. Core 사용 자체를 해결 증거로
   삼지 않고 token 값과 실제 correction 결과를 확인한다.

## 후속 상태와 완료 경계

이 문서의 발견은 **계획에 배정된 상태이며 수정 완료가 아니다.** runtime의 RC-A는 독립적으로 먼저
실행하고, 원본·계보·근거는 공통 계약과 MI/RC-B에서 함께 구현한다. 검색 query는 RC-C, 저장 후
색인은 EA가 소유한다. 기존 계획의 수용 ID·유보 사항·과거 검증은 유지한다.

다음 검증 기록에는 구현 revision, 적용한 테스트 조건(FK 활성 여부 포함), 수정된 RV/RC/MI/EA ID,
격리 PostgreSQL 결과와 별도로 승인된 라이브 적용 여부를 적는다. 운영 DB 접근이 열리면 실제
마이그레이션 head·제약·nullable·진단 결과를 읽기 전용으로 확인한다. 접근이 막힌 이번 결과를
운영 스키마가 올바르다는 근거로 바꾸지 않는다.
