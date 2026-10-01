# Frontend v2 replacement verification

최초 검증일: 2026-10-01. 대상은 `codex/frontend-v2-audit` 작업 브랜치의 실제 React/Vite 앱과
동일 브랜치의 FastAPI 코드다. 사용자가 제공한 목업의 가상 인물만 임시 SQLite DB에 넣었다.
운영 DB, Docker, 운영 서버, 원본 Open Design 프로젝트는 변경하지 않았다.

## 구현과 검증 결과

- 기존 `frontend/src/routes/` UI를 제거하고 `frontend/src/v2/`로 교체했다.
  `frontend_v2/`는 가져온 목업과 최초 감사 자료를 보존한다.
- 프론트엔드 테스트: **45 passed / 6 files**. `npm ci --ignore-scripts`로 독립 설치 후
  `npm test`와 `npm run build` 성공. TypeScript 검사 및 Vite 프로덕션 번들 생성 완료.
- 백엔드 전체 테스트: **594 passed, 3 skipped**. 기존 선택적 PCR 플러그인 통합 검사는
  별도 체크아웃 환경변수가 없어 skip되었다. Ruff 검사와 `git diff --check` 성공.
- 인앱 브라우저에서 주요 네 화면을 데스크톱과 모바일로 직접 확인했다.
  전체 여덟 화면 × 320/768/1440px, 총 **24개 조합에서 가로 넘침 없음**:
  [측정 결과](viewport-checks.json). 390px 주요 화면과 320px 편집 대화상자도 시각 확인했다.
- 최종 브라우저 [오류 로그](browser-console-errors.json)는 빈 배열이다.
- UI 코드와 API 계약을 독립 검토하고, 지적된 canonical 병합 인물/누락 출처/과거 참조 링크/
  오류 초기화/LAN HTTP 요청 ID 문제를 고쳤다. 최종 검토에서 새 P0/P1/P2를 발견하지 못했다.

## 실제 브라우저 여정

1. 사람 목록에서 가족 필터 → 카드 보기 → 존재하지 않는 이름 검색 → 빈 결과 → 초기화.
   서버 건수는 8 → 2 → 0 → 8이며 미리보기도 해당 결과에 맞춰 바뀌었다.
2. 김민지 상세에서 기억 추가 → 문구 정정 → 박서준으로 재귀속 → 철회를 실행했다.
   각 단계가 API 영수증 후 표시되고 원문/근거가 변경 이력에 남는 것을 확인했다.
3. 브라우저와 별개로 HTTP GET을 통해 세 기록을 재조회했다. 상태는
   `superseded / superseded / deleted`, 마지막 대상은 박서준, 출처 발췌는 모두 보존,
   현재 기억 검색 결과는 0건이다. [기록·출처·이력 증거](browser-write-api-proof.json).
4. 관계 그래프에서 김민지와의 연결을 선택하고 출처 화면으로 이동해 발췌/발화 시점/
   수집 시점/원래 관계 기억 링크를 확인했다.
5. 검색에서 김민지와 회의 문서를 선택해 실제 retrieve/pack 결과와 정확한 기억/출처 링크를
   확인했다. 설정의 API/DB 정상 상태와 임베딩 비활성·대기 건수, 이전 기록의 빈 목록도 확인했다.
6. 320px에서 기억 추가 폼과 고정 하단 저장 버튼이 넘치지 않았다. 키보드 Enter로 연 뒤
   Escape로 닫으면 초점이 기억 추가 버튼으로 돌아오는 것을 수정 후 직접 확인했다.

## UI01–UI09 근거

| ID | 확인한 결과 |
| --- | --- |
| UI01 | 주요 메뉴는 사람·기억·관계 그래프·변경 이력. 승인/정책 양식 제거; App 회귀 검사. |
| UI02 | 기억 상세, 원본 근거, 정확한 old/new 참조 및 출처 역방향 조회; browser-write-api-proof.json. |
| UI03 | 실제 API create/correct/reattribute/retract 여정, 409 초안 유지·재시도 ID 회귀 검사. |
| UI04 | reported/inferred/unknown, 부분 생일, 역할·확신도·방향·시각 정밀도 보존 테스트. |
| UI05 | 과거 문구·출처 보존 및 재귀속 전후 인물별 이력, 병합 lineage API 테스트. |
| UI06 | 기존 retrieve/pack 실제 연결, 유효 기간 밖의 기록을 현재 맥락에서 제외하는 API 회귀 검사. |
| UI07 | 서버 설정과 임베딩 처리 건수를 구분; provider 비활성에서도 사람/기억 읽기 정상. |
| UI08 | 24개 반응형 조합, 4화면 데스크톱/모바일 비교, 대화상자 키보드 복귀 및 빈 결과 직접 확인. 오류/409/로딩은 컴포넌트 회귀 검사도 포함. |
| UI09 | 실제 source/audit 읽기, legacy 읽기 전용 호환, localStorage에는 API 토큰만 저장. |

## 화면 증거

| 화면 | 데스크톱 | 모바일 |
| --- | --- | --- |
| 사람 목록 | [화면](people-desktop.png) | [화면](people-mobile.png) |
| 인물 상세 | [화면](person-desktop.png) | [화면](person-mobile.png) |
| 관계 그래프 | [화면](graph-desktop.png) | [화면](graph-mobile.png) |
| 변경 이력 | [화면](changes-desktop.png) | [화면](changes-mobile.png) |

[원본과 나란히 비교한 디자인 QA](../../../frontend/design-qa.md),
[320px 편집 폼](memory-editor-mobile-320.png), [철회 후 기록](retracted-memory-proof.png),
[관계 출처](source-mobile.png), [검색](search-desktop.png).
`*-initial.png`는 수정 전 문제를 보여주는 중간 증거이며 최종 화면이 아니다.

## 재현과 적용 범위

저장소 루트에서 `PYTHONPATH=backend/src uv run python scripts/serve-frontend-demo.py --port 8785`,
`frontend/`에서 README의 `VITE_KINLAYER_API_URL=http://127.0.0.1:8785` 개발 실행법을 사용한다.
데이터는 새 임시 DB에 매번 생성되므로 재실행 시 ID가 달라진다. 이 실행은 임베딩 외부 호출이나
운영 저장을 하지 않으며 프로세스 종료 시 임시 DB를 정리한다. 테스트용 표시는 환경변수로만 켠다.

새 읽기 API가 필요하므로 배포 시 **이 브랜치의 백엔드와 프론트엔드를 함께 반영**해야 한다.
추가 DB migration은 없다. 이 검증은 임시 SQLite와 인앱 Chromium 기준이며 운영 Postgres,
운영 데이터, 실기기 Safari, 외부 임베딩 제공자에 대한 배포 검증을 주장하지 않는다.
기존 계획의 운영 데이터셋 검증은 별도 배포 단계에 남는다. 시간 범위 목록 필터와 채팅 전송
연동은 이번 구현에 포함하지 않았고 해당 제한을 계획·스펙에 명시했다.

## 2026-10-01 라이브 적용과 이관 이력 회귀 검사

사용자의 후속 병합·배포 승인으로 PR #11과 읽기 helper 보완 PR #12를 메인에 병합하고
API/Web을 함께 배포했다. 배포 전 DB 백업과 이전 이미지를 보존했으며 기존 Postgres
컨테이너·볼륨·설정과 스키마 `20261001_0012`를 유지했다. 주요 9개 테이블의 전체 행
해시가 배포 전후 일치했고, 실행 컨테이너의 API/Web 파일도 체크아웃과 일치했다.
라이브 검사는 GET과 읽기 전용 DB 조회로 수행했으며 운영 기록을 수정하지 않았다.

실제 데이터의 인물 이관 행이 일반 기억 API로 연결되어 변경 이력 비교에 422 오류가
발생하는 문제를 발견했다. 참조 종류별로 조회와 링크를 분기하고, 당시 인물 상태가
보관되어 있지 않다는 안내와 현재 인물 링크를 표시하도록 수정했다. 인물별 이력도
병합 전 인물과 비활성 별칭의 이관 기록을 포함한다. 기억 쓰기 계약은 바꾸지 않았다.

후속 회귀 검사: 백엔드 **610 passed, 3 skipped**, 프론트엔드 **49 passed / 6 files**,
프로덕션 빌드 및 `ruff check backend scripts` 성공. 기존 비추적 `.omo` 작업 자료는
코드 린트 범위에서 제외했다. 실제 API를 사용하는 수정 프론트엔드에서 첫 이관 기록의
안내·링크가 정상이며 오류 알림과 잘못된 기억 링크가 0개인 것을 브라우저로 확인했다.
운영 인물·발췌가 포함된 원자료와 화면은 공개 저장소에 추가하지 않는다.
