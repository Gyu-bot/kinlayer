# Kinlayer 프론트엔드 v2 목업

2026-10-01 저장소 인수 평가와 브라우저 수정을 반영했습니다. [평가·스키마 불일치·교체 제안](AUDIT.md), [검증 기록](verification.md)을 먼저 읽어 주세요. AI 정책/리뷰는 과거 계약을 따른 데모이며 현재 운영 API 계약으로 채택할 수 없습니다.

`index.html` 또는 `people.html`을 열면 시작합니다. 별도의 빌드, 서버, 외부 CDN 없이 작동합니다.

## 화면

- 사람: `people.html`
- 인물 상세: `person.html?person=minji`
- 관계 그래프: `graph.html`
- 리뷰: `reviews.html`

탐색 메뉴와 프로필 링크로 화면을 오갈 수 있습니다. 검색, 필터, 정렬, 카드 보기, 인물 추가, 편집, 정책 변경, 출처 조회, 리뷰 처리가 작동합니다. 그래프에서는 중심 인물, 관계 필터, 노드/선 선택, 확대/축소와 이동을 사용할 수 있습니다.

## 데모 범위

표시된 사람과 기록은 가상 데이터입니다. 운영 Kinlayer API나 DB에 연결하지 않았습니다. 수정은 브라우저 localStorage의 `kinlayer-v2-demo-1`에만 저장합니다. 브라우저 저장소를 사용할 수 없는 환경에서는 해당 페이지를 열어 둔 동안만 유지합니다. 왼쪽 아래 '목업 안내'에서 데모를 초기화할 수 있습니다.

## 구성

- `styles.css`: modern-minimal 토큰, 반응형 레이아웃, 상호작용 상태
- `demo-data.js`: 명시된 가상 데이터와 관계/정책 레이블
- `app.js`: 네 화면의 렌더링과 로컬 상호작용
- `DESIGN.md`: 제품 이해, 화면 방향과 API 연결 경계

실서비스로 구현할 때는 기존 HTTP API로 상태 변경을 연결하고 서버 측 정책·검증·동시 수정·증거 연결을 유지해야 합니다. 병합과 자동 reconciliation 실행은 이 목업의 범위가 아닙니다.

## 저장소에서 실행·검사

작업 브랜치의 저장소 루트에서 실행합니다. 현재 프론트엔드와 다른 포트를 사용합니다.

```bash
python3 -m http.server 5184 --bind 127.0.0.1 --directory frontend_v2
# http://127.0.0.1:5184/people.html

node frontend_v2/interaction-checks.cjs
# 기존 frontend/node_modules를 재사용할 때는 경로를 마지막 인자로 전달할 수 있습니다.
```

회귀 검사는 기존 frontend의 jsdom 개발 의존성을 재사용하며 별도 런타임 의존성을 추가하지 않습니다. 화면 자체는 계속 빌드 없이 실행됩니다. `*.artifact.json`은 가져온 Open Design 원본 메타데이터로, 실행에 필요하지 않습니다. `import-manifest.json`은 원본 비교용이며 `evidence/`는 이번 브라우저 검사 결과입니다.
