# 라이브 데이터 정합성 수정

- 기준일: 2026-10-19
- 상태: **계획, 미구현.** 사용자가 라이브에서 같은 관계가 두 번 기록된 것을 발견하고, 라이브 DB
  기준으로 이상한 데이터를 진단해 수정 항목을 계획으로 정리해 달라고 요청했다. 코드 수정, 라이브
  배포, 라이브 데이터 수정은 각각 별도 승인 단계다.
- 순서: [임베딩 자동 생성](embedding-auto-index.md)과 독립적이므로 먼저 진행할 수 있다.
  [관찰 온톨로지 개편](observation-ontology-v1.md)보다 먼저 한다. 그 계획의 전환 manifest가
  중복 없는 관계와 하나뿐인 Self를 전제로 하기 때문이다.
- 선행 계약: [즉시 저장 메모리](save-first-memory-schema.md),
  [관계 온톨로지 relationship-v1](relationship-ontology.md)

## 0. 범위

포함:

- 같은 두 사람 사이에 같은 관계가 중복으로 활성화되는 문제의 원인 수정, DB 제약, 기존 중복 정리
- Self와 같은 사람인 별도 인물 엔티티의 정리와 재발 방지
- 낡은 관계 평가 축, 중복 프로필 사실, 기록이 없는 인물 같은 개별 데이터 정리
- 위 항목을 다시 찾을 수 있는 읽기 전용 정합성 진단

제외:

- 관찰 유형·역할·주장 형태의 재분류, 원 출처 없는 이관 관찰 94건, 근거가 `unknown`인 관계,
  출처 요약이 들어간 `relationship_detail`. 모두 [관찰 온톨로지 개편](observation-ontology-v1.md)
  5.2절에서 처리한다.
- 임베딩 대기 기록. [임베딩 자동 생성](embedding-auto-index.md)에서 처리한다.
- 관찰 본문의 일괄 재작성. 기록마다 사용자 검토를 거쳐 정정한다.

## 1. 진단 (2026-10-19 라이브 읽기 전용 조회)

`casa`의 `kinlayer-postgres`를 읽기 전용 트랜잭션으로 조회했다. 활성 인물 11명, 활성 관계 7건,
활성 관찰 241건, 활성 프로필 사실 12건이다. 개인 내용은 기록하지 않는다. 관계는 ID 앞 8자리로
표시한다.

| ID | 문제 | 근거 | 심각도 |
| --- | --- | --- | --- |
| I1 | 무방향 관계가 방향만 뒤집혀 중복 저장된다 | 활성 무방향 관계 7건 중 4건이 2쌍의 중복이다. (a) Self–한 사람 `former_partner`: `662cc6be`(사용자 기록, relationship-v1 전환에서 무방향으로 정규화, 근거 있음)와 `fd942c4f`(Hermes가 10-06 `create`로 Self→상대 방향으로 생성, 근거 있음). (b) 두 제3자 사이 `romantic_partner`: `5a24a484`(웹 직접 입력)와 `8131385f`(Hermes가 10-04 반대 방향으로 생성). 두 쌍 모두 무방향 관계라 의미가 완전히 같다. | 높음 |
| I2 | 관계 쓰기 경로에 중복 검사가 없다 | `MemoryService._write_record`(`/api/memories`의 create·correct·reattribute), `RelationshipService.create_edge`(후보 승인도 이 함수를 거친다) 모두 `validate_edge_write`로 유형·방향·속성만 검사하고 기존 활성 관계를 찾지 않는다. DB에도 `source_candidate_id` 외 유니크 제약이 없다. 인물 병합의 `_active_duplicate_edge`는 `from`·`to`를 순서대로만 비교해서 무방향 관계가 뒤집혀 있으면 중복을 놓친다. 에이전트 계약에도 관계를 만들기 전에 기존 관계를 확인하라는 규칙이 없다. | 높음 (I1의 원인) |
| I3 | Self와 같은 사람이 별도 인물로 존재한다 | Self의 표시 이름이 기본값 `Self`이고 별칭이 없다. 10-01에 에이전트가 사용자 이름으로 일반 인물 엔티티를 만들었다(별칭·후보 없음). 이 엔티티에 활성 관찰 5건, 프로필 사실 2건, 다른 관찰의 참여자 링크 3건이 붙어 있다. 같은 이름이 관계 문장, 근거 화자 표시, 자료 가져오기 actor에서 사용자를 가리킨다. Self는 병합 대상이 될 수 없어서(`Protected self cannot be merged`) 기존 병합 화면으로 정리할 수 없다. | 높음 |
| I4 | 사용자를 가리키는 표현이 섞여 있다 | 활성 관찰 본문에서 사용자를 이름 53건, `사용자` 35건, 계정명(영문) 11건, `'나' 화자` 등으로 부른다. 영어로 저장된 관찰이 13건(06월 이관분)이고, 그중 하나는 현재 `former_partner`인 상대와 "교제 중"이라고 서술해 현재 관계와 모순된다. | 중간 |
| I5 | 관계 평가 축이 서로 낡은 상태로 남는다 | 두 사람에게 `connection_state=disconnected`가 있지만 `interaction_frequency=frequent`도 활성이다. 빈도는 10-02에 기록됐고, 연결 상태는 그 뒤(한 명은 10-19)에 바뀌었다. 정의상 축은 독립적이라 규칙 위반은 아니다. 하지만 한 축을 바꿀 때 다른 축을 다시 볼 기회가 없다. | 중간 |
| I6 | 같은 뜻의 프로필 사실이 두 건 활성이다 | 한 사람에게 같은 장소를 가리키는 `location_hint` 2건이 모두 활성이다(에이전트가 따로 저장). | 낮음 |
| I7 | 기록이 하나도 없는 활성 인물이 있다 | Hermes가 만든 활성 인물 2명에게 관찰·사실·관계가 없다. 그중 1명은 이전에 삭제된 인물과 이름이 겹친다. | 낮음 |
| I8 | 근거(episode)의 actor 값이 일관되지 않다 | 웹 직접 입력과 정정은 `나`, 에이전트 대화는 `user`, 자료 가져오기는 실제 이름이다. 같은 사용자를 세 가지 값으로 부른다. 웹 프런트엔드가 `actor: "나"`를 보낸다. | 낮음 |

참고로 조회 결과 정상이었던 항목:

- 현재 기록이 삭제·병합된 인물을 가리키는 경우 0건
- 같은 주체·유형·본문의 완전 중복 관찰 0건. 임베딩 유사도 0.85 이상인 쌍은 1건이며, 같은 사건을
  사건(`recent_interaction`)과 감정(`user_feeling`)으로 나눈 의도된 분리다.
- 관계 평가 축 유니크 제약은 지켜지고 있다(사람·축마다 활성 1건).

## 2. 수정 항목

### 2.1 관계 중복 방지 (I2) — 코드

1. **동등 관계 조회 함수:** `relationship_ontology.py`에 `find_current_equivalent_edge(session,
   from_id, to_id, relation_type, directed, exclude_id=None)`를 둔다. 상태가 `active`·`disputed`이고
   유형이 같은 관계를 찾는다. 무방향이면 두 사람을 순서 없이, 방향 관계면 순서대로 비교한다.
2. **쓰기 거부:** `MemoryService._write_record`(create·correct·reattribute)와
   `RelationshipService.create_edge`(후보 승인 경로 포함)가 1을 호출한다. 동등 관계가 있으면
   HTTP 409 `relationship_edge_conflict`를 `details.current_record_ref`와 함께 반환한다.
   관계 평가 축 충돌(`relationship_axis_conflict`)과 같은 형태다. 정정(`correct`)은 교체되는 원본
   자신을 제외하고 검사한다. `lock_active_entities`가 두 인물 행을 잠그므로 같은 쌍에 대한 동시
   쓰기는 직렬화된다.
3. **인물 병합:** `CandidateService._active_duplicate_edge`도 1을 쓴다. 중복으로 판정된 관계는 상태를
   `deprecated`가 아니라 다른 경로처럼 `superseded`로 바꾸고, `invalidated_by_edge_id`로 남는 관계를
   가리킨다.
4. **DB 제약:** Alembic 마이그레이션으로 부분 유니크 인덱스 두 개를 만든다.
   - 무방향: `(least(from_entity_id, to_entity_id), greatest(from_entity_id, to_entity_id),
     relation_type) WHERE directed = false AND status IN ('active','disputed')`
   - 방향: `(from_entity_id, to_entity_id, relation_type) WHERE directed = true AND status IN
     ('active','disputed')`
   - SQLite 테스트 DB에서는 `min()`·`max()`로 같은 식 인덱스를 만든다. 마이그레이션은 시작 전에
     중복을 세고, 남아 있으면 레코드 ID를 출력하며 중단한다(2.4 정리 이후에만 적용 가능).
   - `IntegrityError`가 나면 2의 409로 바꾼다(`MemoryService.write`의 기존 처리 방식을 확장).
5. **에이전트 계약:** `docs/agents/agent-write-instruction-pack.md`에 다음을 추가한다. 관계를 만들기
   전에 두 사람의 관계 목록을 조회한다. 같은 관계가 있으면 새로 만들지 않는다. 409
   `relationship_edge_conflict`는 "이미 기록됨"으로 처리하고 재시도하지 않는다. 무방향 관계는
   저장 방향에 의미가 없다. Hermes 쪽 갱신은 외부 설치본에서 별도로 확인한다.
6. **진단:** `/api/ontology/edge-type-diagnostics`(CLI `ontology edge-diagnostics`)에
   `duplicate_edges` 목록을 추가한다(관계 ID, 유형, 정규화한 두 사람 ID만 포함, 본문 제외).

### 2.2 Self 식별 (I3, I4, I8) — 코드·설정

1. **Self 이름과 별칭:** 라이브 `.env`에 `KINLAYER_SELF_NAME`을 사용자가 정한 이름으로 설정한다.
   `_ensure_protected_self`는 Self가 이미 있으면 이름을 바꾸지 않으므로, 기존 Self는 웹이나 API
   `PATCH`로 표시 이름을 바꾸고 사용자 이름과 계정명을 별칭으로 추가한다(라이브 쓰기, 승인 필요).
2. **Self와 같은 인물 생성 차단:** 에이전트(`created_by=ai_agent`)가 인물을 만들 때 이름이나
   정규화 별칭이 Self와 일치하면 409를 반환하고 `details.self_entity_id`를 함께 준다. 사용자
   직접 입력은 같은 경우 경고만 한다(동명이인 가능성).
3. **에이전트 계약:** 사용자 자신에 관한 기록은 Self ID를 쓴다. 본문에서 사용자는 한 가지 표현으로
   부른다(Q3에서 결정). 영어 본문을 쓰지 않는다.
4. **episode actor:** 웹 직접 입력·정정의 `source.actor`를 에이전트 경로와 같은 값으로 맞춘다.
   기존 episode는 바꾸지 않는다(근거 원본 보존).

### 2.3 관계 평가 축 재확인 (I5) — 화면·계약

- 웹에서 `connection_state`를 `distant`나 `disconnected`로 바꿀 때, 같은 사람의
  `interaction_frequency`가 `frequent`·`occasional`이면 함께 검토하라는 안내를 표시한다.
  자동으로 바꾸지는 않는다(`none`은 명시적 표현일 때만 쓰는 값이다).
- 에이전트 계약에 같은 규칙을 넣는다. 연결 상태를 바꾸는 근거가 빈도에 대해서도 말하면 함께
  정정하고, 그렇지 않으면 그대로 둔다.

### 2.4 라이브 데이터 정리 — 기록별, 승인 후

기존 `MemoryMigrationService` manifest 방식(dry-run, 멱등, 변경 이력, 원본 보존)으로 처리한다.
manifest는 개인 내용을 포함하므로 저장소 밖에 둔다.

| 대상 | 처리 |
| --- | --- |
| I1 (a) `662cc6be` + `fd942c4f` | `662cc6be`(먼저 생긴 사용자 기록)를 유지한다. `fd942c4f`의 근거 링크를 `662cc6be`에 복사하고, `fd942c4f`는 `superseded`와 `invalidated_by_edge_id=662cc6be`로 바꾼다. `fd942c4f`의 `relationship_detail`(출처 요약)은 옮기지 않는다. |
| I1 (b) `5a24a484` + `8131385f` | `5a24a484`(사용자 직접 입력)를 유지한다. `8131385f`의 근거를 복사하고 같은 방식으로 superseded 처리한다. |
| I3 Self 중복 인물 | 사용자 확인(Q2) 후 관찰 5건과 프로필 사실 2건은 Self로 재귀속(`reattribute`)한다. 참여자 링크 3건은 Self 링크로 교체하는 metadata 항목으로 처리한다. 그다음 빈 엔티티를 삭제한다. Self에 이미 같은 뜻의 사실이 있으면 옮기지 않고 superseded로 둔다. |
| I4 모순 관찰 1건 | 현재 관계와 모순되는 "교제 중" 서술은 사용자 확인 후 철회하거나 기간을 밝힌 문장으로 정정한다. 나머지 영어 관찰 12건은 [관찰 온톨로지 전환](observation-ontology-v1.md) manifest에서 함께 검토한다. |
| I5 평가 축 2명 | 사용자에게 현재 교류 빈도를 묻고, 답한 값으로만 정정한다. 답이 없으면 그대로 둔다. |
| I6 중복 위치 사실 | 하나로 정정하고 다른 하나는 철회한다(사용자 확인). |
| I7 빈 인물 2명 | 사용자가 유지 또는 삭제를 정한다. |

절차:

1. 일관된 DB 백업을 만들고 격리된 복사본에 복원한다.
2. 복사본에서 manifest dry-run, 적용, readback을 한다. readback 항목은 중복 관계 0건, Self 이외의
   사용자 엔티티 0건, 근거 링크 수 보존, 변경 이력 존재, 인물 화면과 context card 표시다.
3. 복사본에 2.1의 유니크 인덱스 마이그레이션을 적용해 통과하는지 확인한다.
4. **라이브 적용(별도 승인):** 데이터 정리 → 코드 배포(인덱스 마이그레이션 포함) → 같은 readback.
   데이터 정리를 먼저 하지 않으면 마이그레이션이 의도대로 중단된다.

## 3. 수용 기준

| ID | 완료 조건 |
| --- | --- |
| DI01 | 무방향 관계를 같은 방향과 반대 방향으로 다시 만들면 둘 다 409 `relationship_edge_conflict`이고, 응답의 `current_record_ref`가 기존 관계를 가리킨다. |
| DI02 | 방향 관계(`parent_of` 등)는 반대 방향 생성을 허용하고 같은 방향 생성은 409를 반환한다. |
| DI03 | 기존 관계 정정과 superseded·deleted 관계와 같은 관계를 새로 만드는 것은 성공한다. |
| DI04 | 동시 생성 테스트에서 활성 관계가 1건만 남고, 다른 요청은 409를 받는다. |
| DI05 | 인물 병합이 반대 방향 무방향 관계를 중복으로 판정해 superseded로 남긴다. |
| DI06 | 에이전트가 Self의 이름이나 별칭으로 인물을 만들면 409와 `self_entity_id`를 받는다. |
| DI07 | 진단 API가 중복 관계를 보고하고, 정리 후 라이브에서 0건이다. |
| DI08 | 라이브 정리 후 활성 관계 5건(중복 2건 제거), Self와 같은 사람인 별도 엔티티 0건, 정리 대상의 근거 링크가 유지된 관계에 모두 연결돼 있다. |
| DI09 | 백엔드·프런트엔드 테스트, lint, 빌드, 브라우저 확인(평가 축 안내)을 통과한다. |

## 4. 실행 단위

1. **PR A — 관계 중복 방지:** 2.1의 1–3, 5, 6과 테스트. 인덱스 마이그레이션은 PR A에 넣되,
   중복이 있으면 중단하는 사전 검사를 포함한다.
2. **PR B — Self 식별·평가 축 안내:** 2.2, 2.3과 테스트, 에이전트 계약.
3. **PR C — 정리 manifest 도구:** 관계 근거 복사 + superseded 연산, Self 재귀속 항목. 기존
   마이그레이션 서비스에 없는 연산만 추가한다.
4. **라이브(각각 별도 승인):** 사용자 결정 수집(Q2–Q5) → 복사본 리허설 → 라이브 데이터 정리 →
   PR A·B 배포 → Hermes 계약 갱신 확인.

## 5. 구현 전 확정할 결정

| ID | 질문 | 이 계획의 권장안 |
| --- | --- | --- |
| Q1 | 이미 기록된 관계에 새 근거가 들어오면 어떻게 할지 | 첫 단계는 409만 반환한다. 기존 관계에 근거를 덧붙이는 `corroborate` 동작은 필요성이 확인되면 따로 계획한다. |
| Q2 | 사용자 이름으로 만들어진 인물이 정말 사용자 본인인지 | 본인으로 보인다(근거 화자, 관계 문장, 가져오기 actor가 일치). 정리 전에 사용자가 확인한다. |
| Q3 | 관찰 본문에서 사용자를 부르는 표현 | 사용자 이름 하나로 통일한다(현재 가장 많이 쓰임). |
| Q4 | 같은 두 사람 사이의 서로 배타적인 관계(`romantic_partner`와 `former_partner` 등)를 동시에 막을지 | 이번에는 막지 않는다. 라이브 사례가 없고 정의상 기간이 다르면 공존할 수 있다. 진단 목록에만 추가한다. |
| Q5 | 무방향 관계의 저장 순서 정규화(작은 ID를 `from`) | 하지 않는다. 비교 함수와 식 인덱스로 충분하고, 기존 기록을 다시 쓰지 않는다. |
