# Kinlayer frontend v2 — 목업 디자인

> 2026-10-01 인수 평가: 아래는 원본 목업의 설계 의도를 보존한 기록이다. AI 사용 정책과 저장 전 리뷰는 현재 save-first 계약과 맞지 않는다. 운영 전환 기준은 [AUDIT.md](AUDIT.md)와 저장소 `docs/plans/frontend-rebuild.md`이며, 이번에는 시각·조작 오류만 수정했다.

## 목적과 근거

Kinlayer는 AI 에이전트가 사용하는 사람과 관계의 맥락을 사용자가 확인하고 정정하는 로컬 우선 제어판이다. 일반 CRM, 관계 상담 또는 전체 소셜 네트워크 분석 화면으로 확장하지 않는다.

읽은 기준: 연결 저장소의 README.md, docs/README.md, docs/specs/prd.md, web-ui-spec.md, data-model.md, sensitivity-retirement.md, docs/plans/relationship-reconciliation-cycle.md 및 현재 프론트엔드/ontology 코드.

## 시각 체계

Open Design `modern-minimal` 방향의 토큰을 그대로 사용한다.

```css
:root {
  --bg:      oklch(99% 0.002 240);
  --surface: oklch(100% 0 0);
  --fg:      oklch(18% 0.012 250);
  --muted:   oklch(54% 0.012 250);
  --border:  oklch(92% 0.005 250);
  --accent:  oklch(58% 0.18 255);

  --font-display: -apple-system, BlinkMacSystemFont, 'SF Pro Display', system-ui, sans-serif;
  --font-body:    -apple-system, BlinkMacSystemFont, 'SF Pro Text', system-ui, sans-serif;
}
```

- 넓고 조용한 작업 영역, 가는 테두리, 명확한 표와 문서 계층을 사용한다.
- 색 강조는 주요 행동과 선택된 인물에만 사용한다. 포커스 링은 중립색이다. 기본 강조 토큰은 유지하고, 흰색 버튼 글자의 대비를 위해 버튼 배경만 OKLch L=54%의 파생 토큰을 사용한다.
- 데이터 중심 제품이므로 방향에 지정된 시스템 서체를 사용한다. 한국어는 자간 0, 제목 행간 1.35, 본문 1.75를 적용한다.
- 카드 장식 대신 관계 그래프 자체를 핵심 시각 요소로 사용한다.
- 기본 화면에서는 내부 ID와 원시 JSON을 숨기고 이름, 맥락, 출처, 정책을 보여준다.

## 화면과 동작

1. `people.html`: 이름/별칭 검색, 관계 필터, 최근순/이름순 정렬, 목록/카드 전환, 선택 인물 미리보기, 새 인물 추가.
2. `person.html`: 개요/프로필/관계/출처 탭, 프로필 편집, 맥락 정정, 출처 발췌 확인, AI 사용 범위 변경.
3. `graph.html`: 중심 인물 선택, 직접 연결된 1단계 관계, 관계 필터, 노드/선 선택, 확대/축소/이동/초기화.
4. `reviews.html`: 대기/처리됨 필터, 제안과 현재 정보 비교, 출처 확인, 반영/수정 후 반영/거절/보관/추가 확인.

## 데이터와 구현 경계

- 인물·출처·날짜·리뷰는 모두 명시된 가상 데모 데이터이다. 실제 서비스에 접속하지 않는다.
- 변경은 브라우저 localStorage에만 보관한다. 운영 API/DB의 변경이나 구현 완료를 의미하지 않는다.
- 인물은 저장 후 수정 가능하며, 모든 저장을 리뷰 전에 막지 않는다. 리뷰는 모호한 후보를 다룬다.
- `freely_use`, `cautious_use`, `ask_before_use`, `never_surface`를 저장 정책으로 사용한다. 검색 시 결정되는 노출 버킷과 혼동하지 않는다.
- 폐기된 sensitivity 분류를 노출하지 않는다. 소속은 프로필 사실이며 그래프의 조직 노드로 만들지 않는다.
- 실제 연동 시 HTTP API를 유일한 상태 변경 기준으로 삼아야 한다. 이 목업은 로컬 상호작용 시연이다.
