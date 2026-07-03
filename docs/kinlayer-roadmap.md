# Kinlayer 구현 로드맵

이 문서는 사용자인 내가 구현을 지시할 때 읽기 위한 한글 계획 문서다. 실제 실행 계획의 SSOT는 `.omo/plans/`이며, 이 문서는 그 계획을 사람이 보기 쉽게 풀어쓴 안내서다.

## 현재 계획 SSOT

- 실행 계획 SSOT: `.omo/plans/index.md`
- 상위 롤업 계획: `.omo/plans/kinlayer-next-work.md`
- 실제 구현 slug 계획:
  - `.omo/plans/structured-profile-fact-validation.md`
  - `.omo/plans/profile-fact-promotion-core.md`
  - `.omo/plans/profile-fact-promotion-interfaces.md`
  - `.omo/plans/profile-fact-docs-smoke.md`
- 보류 계획: `.omo/plans/optional-background-curation.md`
- 계획 초안과 결정 기록: `.omo/drafts/kinlayer-next-work.md`
- 이전 루트 계획 아카이브: `docs/archive/planning/implementation-plan-2026-06-27.md`

`docs/archive/` 안의 문서는 참고용 기록일 뿐이며, 현재 계획이나 제품 동작의 SSOT로 쓰지 않는다.

## 다음 구현 목표

다음 작업의 핵심은 일반 프로필 사실을 구조화된 프로필 사실로 안전하게 승격하는 것이다. 예를 들어 "민지는 회사 이메일이 minji@example.com" 같은 일반 메모를 검토한 뒤 `email` 타입의 구조화된 사실로 만들 수 있어야 한다.

이 작업은 두 가지를 함께 끝내야 한다.

- 구조화 타입별 내용 검증: 이메일, 전화번호, 생년월일, 이름, 주소, 소속, 역할 같은 값이 타입에 맞는지 막는다.
- 명시적 승격 워크플로우: API, CLI, Web, 후보 리뷰에서 일반 사실을 구조화 사실로 승격하되 원본 기록과 증거를 추적 가능하게 남긴다.

## 구현 순서

### 1. 구조화 프로필 사실 검증

목표: 잘못된 구조화 값이 어떤 쓰기 경로로도 저장되지 않게 한다.

범위:

- 직접 사실 생성/수정 API
- 후보 생성, accept, edit-accept
- 명시적 correction apply
- agent write validate

완료 확인:

- 잘못된 이메일, 전화번호, 생년월일이 `validation_error`로 거절된다.
- 일반 프로필 사실은 기존처럼 저장된다.
- 구조화 타입 목록과 검증 규칙이 테스트와 문서에 남는다.

### 2. 일반 사실을 구조화 사실로 승격하는 API/서비스

목표: 기존 일반 사실을 원본 손실 없이 구조화 사실로 바꿀 수 있게 한다.

기본 결정:

- 원본을 제자리 수정하지 않는다.
- 새 구조화 사실을 만들고, 원본 일반 사실은 deprecated 또는 superseded 상태로 내린다.
- 반복 승격이나 이미 삭제된 원본 승격은 거절한다.

완료 확인:

- 응답에 원본 record ref와 새 record ref가 함께 나온다.
- 사람 상세 조회에서 원본은 활성 일반 사실에서 빠지고, 새 사실은 구조화 사실로 보인다.

### 3. 후보 리뷰 기반 승격

목표: 에이전트가 바로 canonical write를 하지 않고, `profile_field` 후보 리뷰를 통해 승격을 제안하게 한다.

범위:

- 후보의 `supersedes_record_ref`가 원본 `entity_facts:<id>`를 가리킨다.
- accept/edit-accept 시 구조화 사실을 만들고 원본을 내린다.
- 검증 실패 시 후보가 canonical write를 만들지 못한다.

완료 확인:

- 일반 `profile_field` 후보 생성은 그대로 동작한다.
- 원본 ref가 있는 후보는 명시적 승격으로 처리된다.
- 에이전트 write validate에서 잘못된 구조화 값이 잡힌다.

### 4. CLI 명령 추가

목표: 사용자가 JSON 파일만으로 우회하지 않아도 CLI에서 직접 승격할 수 있게 한다.

예상 명령 형태:

```bash
kinlayer fact promote <fact_id> --fact-type email --content minji@example.com --json
```

완료 확인:

- 텍스트 출력과 JSON 출력 모두 원본 ref와 새 ref를 보여준다.
- 잘못된 값은 API의 `validation_error`를 그대로 보여준다.

### 5. Web 사람 상세 화면 승격 UX

목표: `/people/:id`에서 일반 프로필 사실을 검토하고 구조화 사실로 승격할 수 있게 한다.

범위:

- General Profile Facts 행에 승격 액션을 추가한다.
- 승격 폼에서 타입, 내용, 민감도, AI 사용 정책을 확인한다.
- 성공 후 사실이 Structured Profile Facts 영역으로 이동한다.
- 실패 시 API 검증 오류를 화면에 보여준다.

완료 확인:

- 프론트 테스트와 빌드가 통과한다.
- 브라우저에서 성공 케이스와 실패 케이스를 직접 확인한다.

### 6. 문서와 스모크 갱신

목표: 구현된 동작이 활성 spec, agent pack, acceptance smoke에 반영된다.

갱신 대상:

- API spec
- CLI spec
- candidate lifecycle spec
- Web UI spec
- data model spec
- agent write instruction pack
- API/CLI acceptance smoke

완료 확인:

- 활성 문서에서 승격, 검증, `supersedes_record_ref`, `validation_error`를 찾을 수 있다.
- API/CLI smoke가 새 승격 경로를 검증한다.

## 보류된 작업

선택형 LLM-assisted background curation은 이번 구현 범위가 아니다. 구조화 프로필 사실 검증과 승격 워크플로우가 끝난 뒤 별도 OMO plan으로 다시 설계한다.

이번에 하지 않는 것:

- LLM이 배경 정보를 자동으로 큐레이션하는 기능
- 키워드 기반 자동 승격
- 별도 연락처/profile 테이블
- Web에서만 상태가 바뀌는 기능

## 구현을 지시하는 방법

전체 패키지를 시작하려면 이렇게 지시하면 된다.

```text
.omo/plans/structured-profile-fact-validation.md 부터 승인할게. 구현 시작해줘.
```

부분적으로 시작하려면 이렇게 지시하면 된다.

```text
구조화 프로필 사실 검증부터 시작해줘.
```

또는:

```text
Web 승격 UX는 나중에 하고, API/CLI 승격 경로까지만 먼저 구현해줘.
```

slug별로 지시하려면 이렇게 말하면 된다.

```text
.omo/plans/profile-fact-promotion-core.md 승인할게. API/service와 candidate 승격부터 구현해줘.
```

또는:

```text
.omo/plans/profile-fact-promotion-interfaces.md 승인할게. CLI/Web 승격 화면을 구현해줘.
```

구현을 시작하기 전에는 최신 `origin/main`, 현재 브랜치 상태, 활성 코드와 spec을 다시 확인해야 한다. Docker, 브라우저, 로컬 서비스가 필요하면 honcho 포트와 Kinlayer 포트 충돌을 먼저 확인한다.
