# Kinlayer

Kinlayer는 AI 에이전트를 위한 로컬 우선 관계 맥락 레이어입니다.

AI 에이전트가 사람, 관계, 최근 상호작용, 주의할 점 같은 맥락을 대화 속에서 축적하고 다시 꺼내 쓸 수 있도록 돕되, 사용자가 그 맥락을 직접 검토하고 수정하고 제한할 수 있게 만드는 것을 목표로 합니다.

한 문장으로 말하면:

> Kinlayer는 사람과 관계에 대한 기억을 AI 에이전트가 안전하게 활용할 수 있도록 해주는, 수정 가능하고 정책을 이해하는 로컬 관계 메모리입니다.

## 왜 필요한가

AI 에이전트가 관계 맥락을 다룰 때는 단순한 장기 기억만으로는 부족합니다.

누군가의 이름, 별칭, 관계, 최근 대화, 민감한 사정, 사용자의 감정, 다시 언급하면 안 되는 정보가 서로 얽혀 있기 때문입니다. 게다가 이런 정보는 시간이 지나며 바뀌고, 잘못 기억될 수 있고, 상황에 따라 직접 말해도 되는지 여부도 달라집니다.

Kinlayer는 이 문제를 다음 관점에서 다룹니다.

- 관계 맥락은 저장만큼 수정과 폐기가 중요합니다.
- AI가 내부적으로 참고할 수 있는 정보와 사용자에게 직접 말해도 되는 정보는 다릅니다.
- AI가 추론한 정보는 바로 사실이 되어서는 안 되며, 후보로 검토되어야 합니다.
- 명시적인 사용자 정정은 빠르게 반영되어야 합니다.
- 원본 대화를 통째로 보관하기보다, 필요한 출처와 짧은 증거를 남기는 편이 안전합니다.

## 핵심 사용 흐름

Kinlayer의 중심 흐름은 AI 에이전트와의 대화입니다.

```text
사용자가 AI 에이전트와 대화한다
→ 에이전트가 Kinlayer에서 관계 맥락을 조회한다
→ 에이전트가 정책 라벨이 붙은 맥락을 참고해 응답한다
→ 대화 중 새 인물, 관계, 관찰, 정정이 드러난다
→ 에이전트가 후보 또는 명시적 정정을 Kinlayer에 제출한다
→ 사용자가 모호한 후보를 검토하고, 필요한 맥락을 수정한다
```

웹 UI와 CLI는 이 흐름을 보조합니다. 주된 목적은 매일 쓰는 CRM을 만드는 것이 아니라, AI가 사용하는 관계 기억을 사람이 살펴보고 통제할 수 있게 하는 것입니다.

## Kinlayer가 다루는 것

Kinlayer는 다음 정보를 구조화해 저장하고 검색합니다.

- 사람과 별칭
- 사용자 자신을 나타내는 보호된 `self` 엔티티
- 사람 사이의 구조적 관계
- 관계에 대한 안정적인 사실
- 최근 상호작용과 관찰
- 커뮤니케이션 선호, 주의점, 감정, 후속 맥락
- 후보 상태의 AI 추론 정보
- 명시적인 사용자 정정
- 짧은 증거, 출처, 발생 시각, 보존 정책

이 정보는 AI 에이전트가 쓸 수 있는 Context Pack, 사람별 Context Card, 검색/디버그 결과로 패키징됩니다.

## Kinlayer가 하지 않는 것

Kinlayer는 다음을 목표로 하지 않습니다.

- 일반 CRM
- 소셜 네트워크 분석 도구
- 관계 상담 앱
- 메시지 원문 보관소
- 멀티유저 SaaS
- 최종 답변이나 조언을 직접 생성하는 AI

Kinlayer는 맥락을 저장하고, 점수화하고, 필터링하고, 정책 라벨을 붙여 제공합니다. 최종 해석과 문장 생성은 AI 에이전트의 역할입니다.

## 제품 원칙

### 1. 에이전트 대화가 중심이다

사람, 관계, 관찰, 최근 맥락, 정정은 주로 AI 에이전트와의 대화에서 생깁니다.

수동 입력은 초기 부트스트랩, 검토, 정리, 후보 승인, 검색 디버깅을 위한 보조 수단입니다.

### 2. API가 기준이다

Kinlayer의 기능 기준은 HTTP API입니다.

```text
HTTP API = 정식 기능 계층
Web UI = 사람이 보기 좋은 제어판
CLI = 운영, 디버그, 에이전트 호출용 도구
AI agent = API 또는 CLI를 호출하는 클라이언트
```

웹에서만 가능한 상태 변경은 만들지 않습니다.

### 3. 원본 보관보다 수정 가능성이 중요하다

Kinlayer는 대화 원문 전체를 보관하는 시스템이 아닙니다.

MVP에서는 짧은 발췌, 해시, 출처, 발생 시각, 민감도, 보존 정책을 저장합니다. 신뢰성은 정정, supersede, deprecate, evidence link, retrieval update를 통해 확보합니다.

### 4. AI가 참고하는 것과 직접 말하는 것은 다르다

민감한 정보는 AI가 내부 판단에 참고할 수는 있어도, 사용자에게 그대로 드러내면 안 될 수 있습니다.

Kinlayer는 저장된 민감도와 사용 정책을 바탕으로 검색 시점에 다음 surface bucket을 계산합니다.

- `direct_surface`
- `conditional_surface`
- `internal_only`
- `blocked`

### 5. Kinlayer는 맥락을 패키징하고, 에이전트가 추론한다

Kinlayer는 관계 조언, 메시지 초안, 자연어 브리핑을 직접 생성하지 않습니다.

대신 관계 맥락을 검색하고, 점수화하고, 출처와 정책을 붙여 에이전트가 사용할 수 있는 형태로 제공합니다.

## MVP 범위

Kinlayer MVP는 로컬에서 실행되는 단일 사용자 워크스페이스를 전제로 합니다.

포함되는 주요 기능은 다음과 같습니다.

- 로컬 HTTP API
- CLI 기반 초기화, 상태 확인, 후보 검토, 검색 디버그
- 최소 Web UI 제어판
- 사람/별칭/관계/관찰 저장
- 후보 검토 흐름
- 명시적 사용자 정정 적용
- 출처와 증거 관리
- 정책 인식 검색과 Context Pack
- 1-hop ego graph
- 관찰 기반 임베딩 검색
- 선택적 로컬 bearer token 보호

Web UI의 MVP 화면은 다음과 같습니다.

```text
/people
/people/new
/people/:id
/candidates
/graph
/retrieval-debug
/settings
```

## 로컬 우선 설계

Kinlayer는 기본적으로 `127.0.0.1`에 바인딩되는 로컬 인스턴스입니다.

MVP에는 사용자 계정, 로그인 세션, 조직, 워크스페이스 멤버십, 클라우드 동기화가 없습니다. 대신 로컬 환경에서 필요한 경우 `KINLAYER_API_TOKEN`으로 간단한 bearer token 보호를 켤 수 있습니다.

이 선택은 관계 맥락이 민감한 데이터라는 점을 전제로 합니다. Kinlayer는 사용자의 관계 기억을 외부 서비스에 맡기는 제품이 아니라, 로컬 또는 self-hosted 환경에서 AI 에이전트가 호출할 수 있는 컨텍스트 계층으로 설계됩니다.

## 현재 상태

이 저장소는 Kinlayer MVP의 로컬 API, CLI, Web 제어판, 후보 검토, 명시적 정정, context pack, ego graph, 임베딩 상태/백필, acceptance fixture/smoke 흐름을 포함합니다.

주요 문서:

- `prd.md`: 제품 요구사항과 원칙
- `implementation-plan.md`: 추적 가능한 구현 작업 계획
- `api-spec.md`: HTTP API 계약
- `data-model.md`: 데이터 모델
- `cli-spec.md`: CLI 계약
- `web-ui-spec.md`: Web UI 범위
- `acceptance-scenarios.md`: MVP 수용 시나리오
- `context-output-contract.md`: 검색 결과와 Context Pack 계약
- `candidate-lifecycle-and-payload.md`: 후보 생명주기와 payload 규칙
- `agent-integration-notes.md`: 향후 에이전트 통합 메모

## 설치 준비

로컬 개발 환경에는 다음 도구가 필요합니다.

- Python 3.11 이상
- `uv`
- Node.js 22 이상
- npm
- Docker Desktop 또는 Docker Engine

macOS에서 도구가 없다면 다음처럼 준비할 수 있습니다.

```bash
brew install uv node
```

Docker는 Postgres, API, Web을 한 번에 띄울 때 필요합니다. Kinlayer는 기본적으로 honcho 서비스와 충돌하지 않는 포트를 사용합니다.

## 설치 방법

저장소를 받은 뒤 Python과 Web 의존성을 설치합니다.

```bash
git clone git@github.com:Gyu-bot/kinlayer.git
cd kinlayer
uv sync
cd frontend
npm install
cd ..
```

로컬 데이터베이스와 API/Web 컨테이너를 시작하고 마이그레이션을 적용합니다.

```bash
docker ps --format 'table {{.Names}}\t{{.Ports}}'
docker compose up -d --build
uv run alembic upgrade head
```

첫 실행에서는 보호된 self 엔티티를 만듭니다.

```bash
uv run kinlayer init --self-name "나" --json
```

Web UI는 다음 주소에서 열 수 있습니다.

```text
http://127.0.0.1:5173
```

API는 다음 주소에서 동작합니다.

```text
http://127.0.0.1:8765
```

## 사용 방법

### Web UI

Web UI는 사람이 관계 기억을 살펴보고 조정하는 제어판입니다.

- `/people`: 사람 목록, 검색, 필터
- `/people/new`: 새 사람, 별칭, 초기 관계, 초기 관찰 추가
- `/people/:id`: 사람별 context card, 별칭, profile facts, 관계, 관찰, 출처 확인
- `/candidates`: AI가 제안한 후보 검토, 승인, 수정 승인, 거절, 보관
- `/graph`: 1-hop ego graph 확인
- `/retrieval-debug`: 검색 점수, surface bucket, context pack 디버그
- `/settings`: API 상태, token 설정, embedding 상태, ontology 값 확인

### CLI

CLI는 운영, 스모크, 에이전트 호출에 쓰기 좋은 인터페이스입니다.

```bash
uv run kinlayer status --json
uv run kinlayer person create --name "김민지" --alias "민지" --note "초기 메모" --json
uv run kinlayer person list --query "민지" --json
uv run kinlayer person show <entity_id> --json
uv run kinlayer retrieve "민지와 최근에 이야기한 내용" --json
uv run kinlayer context pack "민지에게 답장하기 전에 참고할 맥락" --json
uv run kinlayer context-card <entity_id> --json
uv run kinlayer debug retrieval "민지 프로젝트 이야기" --json
uv run kinlayer embedding status --json
```

후보와 정정은 JSON payload 파일로 제출합니다.

```bash
uv run kinlayer candidate submit candidate.json --json
uv run kinlayer candidate list --json
uv run kinlayer candidate accept <candidate_id> --json
uv run kinlayer correction apply correction.json --json
```

### HTTP API

HTTP API가 정식 기능 계층입니다. Web UI와 CLI도 같은 API를 사용합니다.

```bash
curl -fsS http://127.0.0.1:8765/api/system/health
curl -fsS 'http://127.0.0.1:8765/api/entities?entity_type=person&limit=20'
curl -fsS -X POST http://127.0.0.1:8765/api/context/retrieve \
  -H 'Content-Type: application/json' \
  -d '{"query":"민지와 최근에 이야기한 내용","debug":true}'
```

에이전트가 새 정보를 발견했지만 사용자가 명시적으로 정정한 것은 아니라면 `candidates`로 제출합니다. 사용자가 직접 “그 정보는 틀렸고 X가 맞아”처럼 명시적으로 정정한 경우에는 correction apply 흐름을 사용합니다.

## 로컬 실행과 검증

기본 포트는 honcho 서비스와 충돌하지 않도록 다음 값을 사용합니다.

- API: `http://127.0.0.1:8765`
- Web: `http://127.0.0.1:5173`
- Postgres: `127.0.0.1:15432`

주요 검증 명령:

```bash
uv run ruff check .
uv run pytest
cd frontend && npm run test
cd frontend && npm run build
```

Docker 기반 스모크:

```bash
docker ps --format 'table {{.Names}}\t{{.Ports}}'
docker compose up -d --build
uv run alembic upgrade head
curl -fsS http://127.0.0.1:8765/api/system/health
uv run kinlayer status --json
uv run kinlayer init --self-name Self --json
uv run kinlayer person list --json
```

한 번에 확인하려면:

```bash
scripts/smoke-slice0.sh
```

Acceptance fixture와 smoke:

```bash
python3 scripts/load-acceptance-fixtures.py
python3 scripts/smoke-acceptance-api.py
scripts/smoke-acceptance-cli.sh
```

선택적 bearer token 모드:

```bash
KINLAYER_API_TOKEN=t029-local docker compose up -d --build api web
KINLAYER_API_TOKEN=t029-local uv run alembic upgrade head
KINLAYER_API_TOKEN=t029-local python3 scripts/smoke-acceptance-api.py
KINLAYER_API_TOKEN=t029-local scripts/smoke-acceptance-cli.sh
```

토큰 모드에서는 `/api/system/health`와 `/api/system/version`은 공개로 유지되고, 관계 데이터 엔드포인트는 `Authorization: Bearer <token>`이 필요합니다. Web UI는 `/settings`에서 로컬 토큰을 저장할 수 있지만 토큰 값을 화면에 다시 표시하지 않습니다.
