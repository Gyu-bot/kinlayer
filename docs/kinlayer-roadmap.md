# Kinlayer 구현 로드맵

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
