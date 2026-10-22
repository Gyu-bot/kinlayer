# Kinlayer 구현 로드맵

## 2026-10-22 검토 반영과 실행 순서

**다음 구현 범위는 [실행 오류 수정 계획](plans/runtime-correctness.md)의 RC-A입니다.**
Self 보호, 후보 상태 경합, 외래키 검증 순서, 다단계 병합 조회를 먼저 고칩니다.
이번 변경은 계획 문서 정리입니다. 구현·운영 배포·기존 자료 전환을 완료하거나 새로 승인한 것은 아닙니다.

| 순서 | 담당 계획 | 완료 경계 |
| --- | --- | --- |
| 1 | [실행 오류 수정 RC-A](plans/runtime-correctness.md) | Self·경합·FK·canonical 조회 안전 수정, FK ON/실제 migration 검증 기반 |
| 2 | [공통 기록 계약](plans/record-lifecycle-contract.md) + [무결성 PR B / RC-B](plans/data-model-integrity.md) | 교차 유형·분할 계보, 병합 원본/import 증명 보존, 모든 canonical writer의 근거·이력 원자성 |
| 3 | [무결성 PR A/C/D](plans/data-model-integrity.md) | 관계 키·슬롯·정의·인물 식별·값 개수와 기간 겹침 제약; 사실 유형 전환은 관찰 계획과 조율 |
| 4 | [자동 인덱싱](plans/embedding-auto-index.md) + [검색 RC-C](plans/runtime-correctness.md) | 저장 후 인덱싱 복구와 실제 query 의미 검색을 각각 검증. RC-C 구현은 앞 단계와 독립 진행 가능 |
| 5 | [관찰 개편](plans/observation-ontology-v1.md) + 무결성 PR E | 정의/역할 정합, v3·시간 정밀도·관계 평가 분리와 웹/에이전트 호환 전환 |
| 6 | 무결성 PR F 및 전환 마무리 | 복원 리허설·기존 refs/digest/소비자 검증 이후 퇴역 열 제거 |

계획 간 공통 불변식은 record-lifecycle 문서가 소유하고 각 실행 계획은 이를 참조합니다.
기존 SF/MI/OV/EA/RO/RP/UI 수용 기준 ID, 판단 근거와 보류 항목은 유지하며 변경분을 추가했습니다.
2026-10-19의 "다음은 임베딩" 순서는 이번 검토에 따라 위 순서로 갱신합니다.

## 검토에서 확인한 현재 한계

- 병합이 같은 기억의 원본 대상을 바꾸어 import 출처 검증을 깨뜨리고, 후보 등 호환 경로가
  공통 근거·변경 이력을 우회합니다. 계보 FK 하나와 CRUD 종료만으로 해결되지 않습니다.
- 상태만 보는 유일성 제약은 과거 경력도 막습니다. 기간·부분 날짜 불확실성, NULL 슬롯 우회,
  single/multi 구분을 공통 계약으로 정리했습니다.
- 자동 인덱싱은 아직 미구현입니다. 현재 일반 문자열 검색은 query vector를 생성하지 않으므로
  저장 벡터가 ready여도 그 요청이 의미 검색을 한 것은 아닙니다.
- 관계 평가의 별도 저장과 관찰 v3는 old refs·시점·정정 토큰 및 구 웹 호환을 함께 전환해야 합니다.

검토 범위·합성 재현·테스트 결과는 [2026-10-22 검토 기록](verification/schema-logic-review-2026-10-22.md)에
있습니다. 라이브 OpenAPI는 로컬과 일치했지만 DB 직접 조회는 SSH 추가 인증으로 수행하지 못했습니다.
아래 과거 라이브 수치를 현재 상태로 재확인했다는 뜻은 아닙니다.

## 2026-10-19 운영 확인 이력

당시 `/api/memories`·자료 가져오기의 관찰 임베딩은 활성 240건 중 197건(82%)이 pending이었고,
승인된 한 번의 수동 백필 후 당시 전체 267건이 ready였습니다. 새 쓰기의 자동 처리는 별도 과제입니다.

당시 구현·라이브 반영을 확인한 범위:

- 즉시 저장 메모리 계약(`/api/memories`), 정정·철회·재귀속, 출처·변경 이력
- 한국어 교체 프론트엔드(`frontend/src/v2/`): 사람·기억·그래프·변경 이력, 직접 입력·삭제·인물 병합
- 관계 정의 `relationship-v1`과 나와의 관계 평가 네 축(`relationship-profile-v1`)
- 승인된 자료 가져오기 v2(프로필 사실·관찰)

별도 승인 전에 보류한 범위는 [관계 온톨로지 계획](plans/relationship-ontology.md)의
"별도 승인 전 보류" 절에 있습니다. 데이터 정리 과제도 별도로 남아 있습니다.
당시 원 출처가 없는 이관 관찰 94건, 근거가 `unknown`인 활성 기록, 이전 curation 설정을 어떻게 처리할지
결정해야 합니다.

## 2026-10-01 현재 방향

- 활성 실행 계약: [즉시 저장·스키마·기존 데이터 전환](plans/save-first-memory-schema.md)
- 에이전트 입력 구조: [Agent Write Contract](agents/agent-write-instruction-pack.md)
- 프론트엔드 교체: [전체 개편 계획과 승인 변경 기록](plans/frontend-rebuild.md) — 목업 기반 교체 구현 승인
- 브라우저·API·회귀 검증: [프론트엔드 v2 검증 기록](verification/frontend-v2/README.md)

새 흐름은 **대화 → 출처가 있는 개별 기억 즉시 저장 → 바로 조회 → 지적 시 정정·철회·재귀속**이다.
승인 후 저장, 신규 후보 대기열, AI 사용 정책은 제거한다. 임베딩 기능과 provider 설정은 유지한다.
직업·일정·추론을 별도 기록으로 나누고, 보고된 진술/추론의 근거, 부분 날짜, 인물 역할,
출처와 변경 이력을 저장·조회 계약 전체에서 보존한다. 기존 DB는 원본을 보존하는 전환과
검증을 거친다. 세부 수용 기준은 활성 계획의 SF01–SF14을 따른다.

### 2026-10-01 프론트엔드 교체 승인

스키마 작업 당시에는 프론트엔드를 계획만 작성하기로 했다. 이후 사용자가 목업 평가와
불일치 수정 제안을 검토한 뒤 **기존 프론트엔드를 폐기하고 이 디자인으로 교체**하도록
승인했다. 이번 결정은 계획만 작성한다는 범위를 갱신하며 기존 계획의 UI01–UI09와 배경은 보존한다.

- 실행 앱은 `frontend/`의 React/Vite 구현이며 `frontend/src/v2/`가 새 화면을 맡는다.
  `frontend_v2/`는 가져온 HTML/CSS/JS 목업과 평가 기록을 보존하는 참고 자료다.
- 주요 화면은 **사람·기억·관계 그래프·변경 이력**이다. 검색·설정·읽기 전용 이전 기록은
  보조 탐색으로 제공하고, 출처는 기억과 변경 이력에서 열 수 있다.
- 기억은 실제 API에서 읽고 `POST /api/memories`로 개별 생성·정정·철회·재귀속한다.
  이름·별칭은 기존 인물 API로 편집한다. 저장 전 승인과 AI 사용 정책 화면은 제거한다.
- 근거 구분, 미래 계획·불확실성, 부분 날짜, 말한 사람·느낀 사람·내용의 대상, 출처와
  유효 시점, 이전 기록을 보존한다. 실패한 저장은 초안을 유지하며 동일 요청을 재시도한다.
- 사람 전체 검색·관계 필터·정렬·집계, 통합 기억 조회, 출처에서 기억 역조회,
  인물별 변경 이력에 필요한 읽기 API를 보완한다. localStorage에는 사용자가 입력한 연결
  토큰만 저장하며 운영 데이터를 브라우저 안에서 따로 수정하지 않는다.
- 임베딩 설정과 실제 검색 데이터 처리 현황을 구분한다. 기존 후보와 에이전트 쓰기
  기록은 읽기 전용 조회·내보내기로 남기고, 새 임베딩 실행·후보 승인 UI는 만들지 않는다.

이번 교체는 새 DB 마이그레이션이나 기존 운영 데이터 전환을 추가하지 않는다. 검증용
가상 데이터 API는 임시 DB를 사용하며 실제 서비스 배포·재시작과 분리된다. 실행 방법은
[README](../README.md), 최종 검증 결과와 운영 적용 범위는 위 검증 기록에서 확인한다.

아래 2026-08-24 curation 로드맵은 과거 결정과 구현 이력이다. 기존 요구·단계를 지우지 않고
보존하지만, 아래의 “다음 목표”, “승인”, “승격”, “provisional”은 새 쓰기 흐름의 요구가 아니다.

---

## 이전 로드맵 및 결정 이력


이 문서는 사용자가 Kinlayer의 현재 구현 방향과 다음 작업을 빠르게 확인하기 위한 한글 안내서다. 구체적인 실행 계약과 acceptance criteria는 `docs/plans/`의 활성 계획 문서를 따른다.

## 현재 계획 문서

- 활성 구현 계획: `docs/plans/relationship-curation-cycle.md`
- 제품/API 계약: `docs/specs/`
- 에이전트 통합·쓰기 경계: `docs/agents/`
- 이전 구현 기록: `docs/archive/` — 역사적 참고용이며 현재 실행 SSOT가 아님

## 현재 구현 상태

2026-08-24 기준:

- 구조화 프로필 사실 검증이 직접 API, 후보 accept/edit-accept, correction apply, agent-write validation 경로에 반영돼 있다.
- 일반 프로필 사실을 구조화 사실로 승격하는 API·CLI·Web 흐름이 구현돼 있다.
- candidate accept/edit-accept가 canonical record를 만들고 `canonical_record_ref`를 남기는 기본 경로가 존재한다.
- post-turn pending candidate를 bounded source pack, deterministic policy, transactional executor로
  정리·승격하는 repository Phases 1-4가 구현돼 있다.
- 사용자는 2026-08-24에 별도 curation/dreaming 단계 구현을 승인했다.

## 다음 구현 목표

Repository Phases 1-4는 구현됐다. 다음 경계는 **Phase 5 profile-local adapter**, shadow 검토,
그리고 별도 승인되는 runtime activation이다.

핵심 흐름:

```text
대화 후 빠른 추출
→ pending candidate 축적
→ 별도 주기적 curation 단계
→ 관련 후보·근거·기존 canonical context 비교
→ 중복 제거·내용 정리·충돌 판정
→ 안전한 관찰만 canonical 승격
→ canonical record와 context readback 검증
```

Honcho의 상세 Dreaming 알고리즘을 복제하는 작업이 아니다. 실시간 후보 생성과 사후 정리·승격을 분리한다는 개념만 사용한다.

## 역할 경계

### Hermes 또는 외부 에이전트

- curation 주기 실행
- Kinlayer가 만든 bounded source pack 해석
- 구조화된 curation plan 생성
- 근거가 부족할 때만 관련 source turn을 제한적으로 추가 조회

### Kinlayer

- pending candidate와 evidence 보관
- bounded source pack 생성
- curation run/decision 상태와 cursor 저장
- ontology·evidence·대상·위험 정책의 결정론적 검증
- 허용된 accept/edit-accept/consolidation 실행
- transaction, idempotency, audit, rollback, canonical readback

Kinlayer core에는 provider-specific LLM 호출을 넣지 않는다. 외부 LLM이 제안하고 Kinlayer가 허용 여부와 canonical 상태를 통제한다.

## 구현 단계

### 1. Curation 상태 모델과 API 계약

- `curation_runs`와 `curation_decisions`
- disabled/shadow/apply 모드
- run cursor와 idempotency key
- source-pack/run/list/get API

### 2. Candidate 기반 bounded source pack

- 마지막 cursor 이후 pending만 증분 조회
- 같은 target entity 또는 unresolved identity key별 그룹화
- candidate evidence의 짧은 사용자 원문과 source metadata만 포함
- 기존 canonical context는 compact projection으로 포함
- 전체 세션·전체 episode body·assistant/tool output은 포함하지 않음

### 3. 결정론적 자동 실행 정책

첫 버전에서 자동 승격 가능한 것은 정확한 기존 인물에 연결된 안전한 `observation`으로 제한한다.

자동 승격에서 제외:

- 새 인물·별칭·병합
- 관계 edge와 profile field
- 충돌·대체
- 모호하거나 유사 이름인 인물
- 역할명만 있는 인물
- 고위험·고민감 정보
- validation warning 또는 canonical conflict가 남은 후보

### 4. 후보 통합과 transactional promotion

- 겹치는 후보를 하나의 observation으로 통합
- 원래 evidence episode를 모두 보존
- 한 transaction에서 canonical write와 source candidate 상태 변경
- 오류 시 rollback하고 원래 candidate를 pending으로 유지
- 재시도 시 중복 canonical record를 만들지 않음

### 5. Readback과 실행 감사

각 decision마다 다음을 남긴다.

- 입력 candidate ID
- 사용한 episode ID
- 결정과 reason code
- 실행 API/operation
- canonical record ref
- readback 결과
- planner/model/policy version

완료 조건:

- candidate가 `accepted` 또는 `edited_accepted`
- `canonical_record_ref` 존재
- exact canonical record 확인
- evidence link 확인
- target context card 또는 compact canonical projection 재조회
- 중복·superseded candidate 상태 확인

### 6. Provisional pending context

다음 curation 전에 최근 pending이 완전히 보이지 않는 문제를 줄이기 위해, opt-in provisional context를 별도 필드로 제공한다.

- canonical과 구조적으로 분리
- exact existing entity의 최근 observation만
- `unreviewed` 표시
- identity/structural/high-risk candidate 제외
- 새 쓰기의 evidence로 재사용 금지

### 7. Hermes periodic curator

Kinlayer API와 executor가 안정된 후 profile-local Hermes adapter를 구현한다.

- Kinlayer run cursor 사용
- 전체 세션 sweep 금지
- bounded source pack을 모델에 전달
- strict structured output으로 plan 제출
- shadow 검증 후에만 live apply 활성화
- Gateway restart나 live activation은 구현과 별도 승인 경계

## 현재 실행 브랜치

```text
codex/kinlayer-curation-cycle
```

외부 Codex 세션은 다음 문서를 실행 계약으로 사용한다.

```text
docs/plans/relationship-curation-cycle.md
```

다음 실행 범위는 Phase 5 adapter handoff부터 시작한다.

```text
Read AGENTS.md, docs/plans/relationship-curation-cycle.md, and docs/agents/agent-integration-notes.md. Repository Phases 1-4 are implemented. Implement the profile-local Phase 5 adapter against the exact bounded source-pack/run contract, run shadow inspection, and keep Gateway restart or apply activation as separate explicitly authorized deployment actions.
```

## 검증 원칙

- 구현 중에는 변경 계약을 직접 보호하는 focused tests를 먼저 실행한다.
- semantic batch가 안정된 뒤 backend tests와 lint를 한 번 실행한다.
- CLI/Web 변경 시 각각 targeted test와 build를 실행한다.
- Docker나 서비스-backed smoke 전에 Honcho/Kinlayer 포트와 현재 실행 상태를 먼저 확인한다.
- 실제 live candidate/canonical 데이터에 apply하는 것은 별도 활성화 승인 전까지 금지한다.

## 완료 기준

- 사용자가 pending을 하나씩 검토하지 않아도 별도 curation 단계가 안전한 후보를 정리·승격한다.
- 일반 실행은 candidate-driven 증분 처리이며 전수 세션 sweep이 아니다.
- 모호하고 민감한 구조 변경만 예외 review 대상으로 남는다.
- 승격은 provenance·transaction·idempotency·readback을 보존한다.
- LLM 해석은 Hermes에, canonical state control은 Kinlayer에 남는다.
