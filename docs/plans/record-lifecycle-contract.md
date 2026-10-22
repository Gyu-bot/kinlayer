# 기록 생애주기·계보·근거 공통 계약 — `record-lifecycle-v1`

- 기준: 2026-10-22 검토, 저장소 `5df21a3`.
- 상태: **목표 설계, 미구현.** 문서 정리 요청을 반영한 계획이며 구현·배포·기존 데이터 전환의
  완료나 승인을 뜻하지 않는다. 현재 API는 [즉시 저장 계약](save-first-memory-schema.md)을 따른다.
- 적용: [모델 무결성](data-model-integrity.md) M1–M8,
  [관찰 개편](observation-ontology-v1.md), [실행 오류 수정](runtime-correctness.md).
- 역할: 여러 계획이 공유하는 불변식의 단일 기준이다. 각 기능의 실행 순서·수용 기준은 담당 계획에
  두며, 관측 사실은 [2026-10-22 검토 기록](../verification/schema-logic-review-2026-10-22.md)에 둔다.

## 1. 결정 변경과 유지 범위

즉시 저장 → 이후 대화로 정정하는 흐름, bounded human source, 원본 보존, 요청 멱등성은 유지한다.
승인 대기열·정책 기반 검색 차단·코어 LLM 분류를 추가하지 않는다. 기존 SF/MI/OV/RO/RP ID는 유지한다.

2026-10-19 M5의 단일 self-FK 제안을 교차 유형·다중 후속 기록 계약으로 대체한다. 같은 테이블의
`superseded_by_id` 하나는 관찰→사실 이동, 한 관찰의 분할, 여러 중복 기록의 통합을 표현하지 못한다.
또한 병합 때 원본의 인물 FK를 직접 바꾸는 방식은 import digest 검증과 과거 이력을 훼손한다.
아래는 이를 해결하는 권장 구현 구조이며, 물리 DDL은 LC01–LC10 검증을 충족하도록 구현 PR에서 확정한다.

## 2. 기록 정체성과 대체 관계

- 공통 `memory_records` 정체성 테이블을 두는 안을 기준으로 한다. 전역 ID, record kind,
  기존 외부 `record_ref` 대응, 생애주기와 근거 상태를 관리하고, fact/edge/observation/assessment
  payload는 유형별 테이블에 둔다. 문자열 `table:id`는 호환 주소이며 FK의 대용으로 쓰지 않는다.
- 유형별 payload와 공통 정체성의 1:1·kind 일치, 부모 없는 payload 및 payload 없는 부모 금지를
  FK/UNIQUE와 커밋 시 제약으로 보장한다. 중복 상태 열을 남기면 쓰기 원본과 동기화 제약을 명시한다.
- `memory_replacements`는 old/new 공통 ID, 변경 작업 ID, 교체 사유를 참조한다. 1:1 정정,
  1:N 분할, N:1 중복 통합 및 observation↔fact 이동을 표현한다. 자기 참조·중복 링크·순환을 금지한다.
- `memory_changes`는 작업·원본·후속 기록에 FK로 연결한다. 기존 old/new 문자열 응답은 유지하고,
  다중 결과는 전체 replacement 집합을 추가 반환한다. 기존 요청 재실행은 동일 작업·동일 refs를 돌려준다.
- 새로 `superseded`가 된 revision에는 후속 링크가 최소 하나 있어야 한다. 링크와 상태는 같은
  트랜잭션에서 바뀌며 커밋 시 검사한다. 철회는 `deleted`이며 후속 기록을 만들지 않는다.
- 후속 기록을 복원할 수 없는 과거 행은 migration manifest와 연결된 명시적 legacy 예외로 보존한다.
  예외 목록을 파일로만 남기고 DB CHECK를 무시하지 않는다. 일반 API는 이 예외를 만들 수 없다.

## 3. 원본 보존과 인물 병합

- 저장된 revision의 의미 필드, 원본 인물 ID·참여자, source excerpt/hash, import manifest와
  authorization digest를 덮어쓰지 않는다. 내용 정정·재귀속은 새 revision과 대체 링크를 만든다.
- 단순 인물 병합은 **원본 ID를 보존하고 현재 조회에서 canonical 인물을 해석**하는 안을 우선한다.
  원래 인물/현재 인물을 구별해 반환하고, 원본 ref 상세·과거 source 검증은 원본 payload를 사용한다.
  인물 병합 자체의 audit와 영향 받은 refs는 기록하되 원문을 새 발언으로 꾸미지 않는다.
- canonical resolver는 A→B→C 전체 체인을 따라가며 순환·누락 대상을 명시적 오류로 처리한다.
  사람·기억·context-card·graph·검색·변경 이력 모두 같은 resolver를 사용한다.
- 병합으로 현재 관계/사실/평가가 충돌하면 canonical 대상 기준으로 탐지한다. 명시적으로 검증된
  중복만 lineage를 남겨 통합하고, 상충하는 값은 자동 선택하지 않는다. 해당 병합은 롤백 또는
  검토 가능한 충돌 응답으로 종료하며, 먼저 인물을 merged로 확정한 뒤 충돌 기록을 방치하지 않는다.
- 공통 정체성의 현재 canonical 대상 키를 유일성 검사에 사용하는 경우, 병합 대상과 영향 받은
  현재 키를 결정적 순서로 잠그고 같은 트랜잭션에서 갱신한다. 원본 payload의 FK는 바꾸지 않는다.
- source 여러 개를 통합하는 경우 원본 evidence 집합과 각 import의 검증 경로를 그대로 보존한다.
  새 파생 revision에는 원본별 계보를 제시하며 과거 승인 manifest를 다시 해시해 승인한 것처럼 만들지 않는다.
- 명시적으로 확인된 일반 인물을 Self에 귀속하는 전환은 migration 전용 연산이다. 일반 병합의
  Self 금지와 Self 항상 active 규칙을 약화하지 않고, 원본·정체성 매핑·전환 audit를 남긴다.

## 4. 공통 쓰기와 근거의 커밋 불변식

- HTTP 진입점이 여러 개여도 canonical revision을 만드는 트랜잭션 서비스는 하나다.
  memories, material imports v1/v2, candidate accept/edit-accept, correction, curation,
  reconciliation, enrichment, migration을 모두 호출 경로 목록에 포함한다.
- 기존 인증·자료 가져오기 승인·서명·스냅샷 검증은 각 경계에서 유지하고 공통 writer를 호출한다.
  내부에서 HTTP를 재호출하지 않으며, writer는 외부 트랜잭션의 commit 권한을 빼앗지 않는다.
- 새 canonical revision, 실제 source episode, evidence, change/lineage, 요청 receipt는 원자적으로
  저장한다. 실패 시 전부 롤백한다. 인덱싱은 이 commit 이후의 파생 작업이다.
- DB 보장의 기준안: 공통 record에 `evidence_status`와 nullable `primary_source_episode_id` FK를
  두고, 새 `available` 기록은 이 FK가 반드시 존재하도록 CHECK한다. 커밋 시 제약 트리거로
  해당 record의 evidence 링크에 같은 episode가 존재하고 연결된 episode가 실재함을 검증한다.
  evidence 삭제·이관 및 record 상태 전이에도 같은 검사를 적용한다.
- `missing_legacy`는 실제 과거 원본/전환 작업에 연결된 경우만 허용하고 신규 입력 필드로 노출하지
  않는다. 근거가 없는 과거 기록의 분할도 결손 상태와 원본 lineage를 계승하며 가짜 episode를 만들지 않는다.
- 상태 전이마다 잠금 이후 최신 상태를 읽는다. accept/reject/archive/clarify/supersede와 grouped
  executor가 같은 규칙을 사용한다. FK 대상의 존재·상태 검증은 이를 참조하는 ledger INSERT보다 먼저 한다.

## 5. revision 상태와 유효기간, 유일성

`active|disputed`는 철회·교체되지 않은 revision 상태다. **현재 유효함**은 이 상태와 유효기간의
교집합이며 둘을 같은 뜻으로 사용하지 않는다. 끝난 경력은 올바른 과거 사실일 수 있으므로 단지
시간이 지났다는 이유로 superseded로 바꾸지 않는다.

- 정확한 기간은 `[valid_from, valid_to)`로 비교한다. null 시작/끝은 각각 열린 경계이며, 같은
  유형·슬롯·값이어도 겹치지 않는 기간은 공존할 수 있다. 만료된 과거 기록이 재입사를 차단하면 안 된다.
- 관계 중복 키는 canonical 두 인물+relation type, 슬롯 키는 canonical 두 인물+slot이다.
  방향 관계는 순서를 보존하고 무방향 관계는 canonical 인물의 정규 순서로 비교한다.
- 현재 유형의 directed·slot 일치 제약은 canonical projection에 적용한다. 과거 원본의 방향이나
  속성을 최신 정의에 강제로 맞추지 않는다. 원본 표현을 보존하는 기존 정정 호환과 현재 키 검증을
  구별하고, 의미가 모호한 역사 기록의 projection은 manifest에서 확인하기 전 임의 전환하지 않는다.
- fact는 single이면 canonical 인물+fact type, multi이면 여기에 정규화 `value_key`를 추가한다.
  `cardinality`는 NOT NULL인 파생 값이며 정의와 복합 FK로 일치시킨다. single/multi 제약의
  predicate를 각각 분리하고 multi의 `value_key`는 null/빈 문자열을 허용하지 않는다.
- nullable slot 복합 FK만으로 정의 일치를 주장하지 않는다. 정의와 행에 NOT NULL `slot_key`를
  두고 `none`을 슬롯 없는 내부 값으로 사용하며 FK로 일치시킨다. slot 제약은 `slot_key <> 'none'`에
  적용한다. 이는 저장 제약용 값이며 새로운 관계 온톨로지 유형이 아니다.
- PostgreSQL에서는 위 키와 유효기간 겹침을 배제 제약으로 검사하는 안을 우선 검증한다.
  필요한 연산자/확장, canonical 키 갱신과 동시 INSERT를 격리 DB에서 검증한다. SQLite 검사는
  서비스 동작만 보완하며 운영 DB의 배제 제약을 검증했다고 간주하지 않는다.
- `now()`가 들어간 부분 인덱스나 주기적인 active 상태 변경으로 시간 흐름을 흉내 내지 않는다.
  정확한 기간·미상 기간·부분 날짜와 경합에 대한 PostgreSQL 테스트 통과 전 제약을 확정하지 않는다.

## 6. 부분 날짜의 의미

부분 날짜는 원래 components·precision·해석 timezone을 보존하며 한 시각으로 단정하지 않는다.
예를 들어 `valid_to=2026년 3월`은 종료 시각이 3월 1일 이상 4월 1일 미만에 있다는 정보다.
이 구간 시작을 실제 종료로 비교하거나 구간 끝을 실제 종료라고 표시하지 않는다.

- 정확한 시각은 점 경계, 부분 날짜는 가능한 경계의 구간으로 해석한다. 기존 datetime과 offset은
  그대로 보존한다. legacy precision=null은 원래 시각을 삭제하거나 임의 day로 낮추는 근거가 아니다.
- 조회는 `current|not_current|uncertain` 판정과 원래 정밀도를 구별한다. 가능한 시작 중 가장 늦은
  경계 이후이면서 가능한 종료 중 가장 이른 경계 이전이면 확실한 current다. 경계 구간과 겹치는
  시점은 uncertain이다. exact timestamp의 `[from,to)` 판정은 유지한다.
- v3의 기본 현재 목록은 current와 uncertain을 포함하되 uncertain을 구별해 표시한다. 구버전
  boolean `is_current`는 이 포함 여부로 투영하고, 불확실성 메타데이터를 추가한다. 조회에서 빠지거나
  확정 사실처럼 보이지 않도록 카드·검색·웹에 동일 규칙을 적용한다.
- 유일성 검사는 두 기록의 **가능한 유효기간**이 겹치면 자동 공존을 허용하지 않는다. 부분 경계
  때문에 충돌하는 경우 이유와 원래 정밀도를 반환해 정밀한 정보나 명시적 정정을 요청한다.
  이 보수적 검사는 사실 확정이나 자동 supersession이 아니다.
- 상대 날짜는 실제 출처 시각·timezone이 있을 때만 변환한다. 저장 시각을 출처 시각으로 대체하지 않는다.

## 7. 관계 평가 분리와 버전 호환

- M8의 assessment는 공통 record identity·근거·계보를 사용하는 별도 payload다. self 관점,
  subject, axis/value, reported basis, confidence, 알려진 occurred_at/valid_from,
  created_at/updated_at 및 created_by를 보존한다. valid_to·미래 평가 금지 등 RP 규칙을 유지한다.
- 단순한 물리 테이블 이동은 의미 정정이 아니다. 원래 외부 ref와 조회 가능한 이력, 요청 receipt,
  concurrency token을 보존하는 매핑을 둔다. payload가 실제로 바뀌는 전환은 새 revision으로 구별한다.
- 기존 `observations:<id>` 주소, v2 relationship_assessment 입력, exact-ref correction/retract는
  전환 어댑터로 해석한다. 일반 관찰의 assertion_mode 검증·임베딩 대상으로 다시 흘려보내지 않는다.
  평가의 의미는 evaluation이지만 새 일반 관찰 행을 만드는 것은 아니다.
- 먼저 additive schema/read/write adapter를 배포하고 웹·CLI/helper·Hermes를 갱신한 다음 자료를
  전환한다. 계약 버전 discovery는 지원 버전 집합과 선택 버전을 구별한다. v2와 v3를 동시에 받을 때
  기존 웹의 strict version=2 검사로 모든 쓰기가 중단되지 않도록 호환 값을 유지하거나 웹을 먼저 갱신한다.
- old refs·v2 재시도·import 증명·모든 소비자의 readback 확인 후에만 구 열과 어댑터 제거 단계를
  실행한다. 배포 전 검증 없이 관찰 행이나 예전 ref 대응을 먼저 삭제하지 않는다.

## 8. 공통 수용 기준

| ID | 완료 조건 |
| --- | --- |
| LC01 | observation→fact, 1:N 분할, N:1 통합이 FK로 연결되고 원본·모든 후속 refs·동일 요청 재실행이 보존된다. |
| LC02 | 새 superseded 기록의 후속 링크 누락·순환은 커밋되지 않는다. legacy 예외는 원본/전환 작업을 추적하며 일반 쓰기로 생성할 수 없다. |
| LC03 | V2 import 사실·관찰의 인물 병합 뒤 원본 payload/hash/provenance와 과거 ref 조회가 유지되고 현재 대상은 canonical 인물로 해석된다. |
| LC04 | 모든 canonical writer에 성공/실패/재시도 검증이 있으며 근거·change 누락은 서비스와 실제 PostgreSQL 커밋 제약에서 거절된다. |
| LC05 | 기간이 겹치는 같은 관계·슬롯 및 single 값은 충돌하고, 기간이 분리된 과거 경력·재입사는 공존한다. 동시 INSERT도 같은 결과다. |
| LC06 | NULL slot 우회·틀린 cardinality·multi의 비어 있는 value_key는 DB에서 거절하며 multi의 서로 다른 값은 저장된다. |
| LC07 | 부분 종료 월의 시작·중간·끝, timezone 경계, 미상·legacy 날짜에서 표시/현재 판정/검색/유일성 결과가 일치한다. |
| LC08 | assessment의 old ref·시점·basis·confidence·근거·정정 토큰과 미설정 null이 전환 전후 보존되며 임베딩되지 않는다. |
| LC09 | v2/v3, 구 웹/새 웹, CLI/helper/Hermes와 ref 재시도 호환을 단계별로 검증한 뒤 제거 마이그레이션을 실행한다. |
| LC10 | Alembic 생성 DB/ORM 차이와 의도적 PostgreSQL 전용 제약을 기록하고, 복원·전환·제약 활성화·readback 리허설을 통과한다. |

## 9. 구현 경계

물리 테이블·트리거·배제 제약 DDL과 canonical key 갱신 방식은 MI PR B/A/D에서 검증·확정한다.
LC의 불변식을 약화하는 대안은 결정 변경으로 기록한다. RC의 Self·상태 경합·FK 오류·resolver
수정은 이 전체 스키마 전환을 기다리지 않는다. 공통 writer와 병합 provenance 수정은 MI PR B와
함께 완료하고, M8은 observation-v1 2단계와 같은 배포 창에서 수행한다.
