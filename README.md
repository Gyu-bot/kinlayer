# Kinlayer

> Sensitivity is retired. See [retirement and compatibility contract](docs/specs/sensitivity-retirement.md).

Kinlayer는 AI 에이전트를 위한 로컬 우선 관계 맥락 레이어입니다.

AI 에이전트가 사람, 관계, 최근 상호작용, 주의할 점 같은 맥락을 대화 속에서 축적하고 다시 꺼내 쓸 수 있도록 돕되, 사용자가 대화 중 틀린 내용을 지적하면 바로 수정할 수 있게 만드는 것을 목표로 합니다.

한 문장으로 말하면:

> Kinlayer는 사람과 관계에 대한 기억을 AI 에이전트가 안전하게 활용할 수 있도록 해주는, 출처와 변경 이력을 보존하는 로컬 관계 메모리입니다.

## 왜 필요한가

AI 에이전트가 관계 맥락을 다룰 때는 단순한 장기 기억만으로는 부족합니다.

누군가의 이름, 별칭, 관계, 최근 대화, 민감한 사정, 사용자의 감정, 다시 언급하면 안 되는 정보가 서로 얽혀 있기 때문입니다. 게다가 이런 정보는 시간이 지나며 바뀌고, 잘못 기억될 수 있고, 상황에 따라 직접 말해도 되는지 여부도 달라집니다.

Kinlayer는 이 문제를 다음 관점에서 다룹니다.

- 관계 맥락은 저장만큼 수정과 폐기가 중요합니다.
- 저장한 기억은 AI가 바로 사용할 수 있습니다. 별도 AI 사용 정책이나 저장 전 승인은 없습니다.
- 보고된 진술과 AI 추론을 구분하고, 추측과 불확실성을 그대로 보존합니다.
- 명시적인 사용자 정정은 빠르게 반영되어야 합니다.
- 원본 대화를 통째로 보관하기보다, 필요한 출처와 짧은 증거를 남기는 편이 안전합니다.

## 핵심 사용 흐름

Kinlayer의 중심 흐름은 AI 에이전트와의 대화입니다.

```text
사용자가 AI 에이전트와 대화한다
→ 에이전트가 Kinlayer에서 관계 맥락을 조회한다
→ 에이전트가 출처·근거·시점이 붙은 맥락을 참고해 응답한다
→ 대화 중 새 인물, 관계, 관찰, 정정이 드러난다
→ 에이전트가 독립적으로 고칠 수 있는 기록을 /api/memories로 즉시 저장한다
→ 사용자가 대화 중 잘못된 내용을 지적하면 정정·철회·인물 재귀속을 적용한다
```

웹 UI와 CLI는 이 흐름을 보조합니다. 주된 목적은 매일 쓰는 CRM을 만드는 것이 아니라, AI가 사용하는 관계 기억을 사람이 살펴보고 통제할 수 있게 하는 것입니다.

> **중요: 에이전트 쓰기 연동 전에 반드시 읽기**
>
> Kinlayer에 프로필, 관찰, 관계, 정정 데이터를 쓰는 AI 에이전트/스킬/플러그인/MCP 어댑터는
> [Agent Write Instruction Pack](docs/agents/agent-write-instruction-pack.md)을 따라야 합니다.
> 이 문서는 `relation_type` 같은 ontology-controlled 값, edge와 observation의 경계,
> 사용자 발화 증거 규칙, 상대 날짜 처리, 명시적 정정 적용 조건을 정의합니다.

## Kinlayer가 다루는 것

Kinlayer는 다음 정보를 구조화해 저장하고 검색합니다.

- 사람과 별칭
- 사용자 자신을 나타내는 보호된 `self` 엔티티
- 사람 사이의 구조적 관계
- 관계에 대한 안정적인 사실
- 최근 상호작용과 관찰
- 커뮤니케이션 선호, 주의점, 감정, 후속 맥락
- 보고된 진술과 구분되는 AI 추론 정보
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

Kinlayer는 맥락을 저장하고, 점수화하고, 필터링하고, 출처와 근거를 붙여 제공합니다. 최종 해석과 문장 생성은 AI 에이전트의 역할입니다.

## 제품 원칙

### 1. 에이전트 대화가 중심이다

사람, 관계, 관찰, 최근 맥락, 정정은 주로 AI 에이전트와의 대화에서 생깁니다.

수동 입력은 초기 부트스트랩, 조회, 정리, 정정, 검색 디버깅을 위한 보조 수단입니다.

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

MVP에서는 짧은 발췌, 해시, 출처, 발생 시각, 보존 정책을 저장합니다. 신뢰성은 정정, supersede, deprecate, evidence link, retrieval update를 통해 확보합니다.

### 4. 저장은 즉시, 오류는 대화 중 정정한다

Kinlayer에 등록한 기억은 AI 사용을 전제로 합니다. 새 쓰기는 승인 후보를 거치지 않습니다.
`claim_basis`로 보고된 진술·추론·근거 불명을 구분하고, 현재 유효한 기록을 조회합니다.
잘못된 기록은 원본과 출처를 남긴 채 교체·철회·다른 인물로 재귀속합니다.
기존 AI 사용 정책과 확인 상태 필드는 이전 클라이언트 호환용이며 저장·검색 판단에는 쓰지 않습니다.

### 5. Kinlayer는 맥락을 패키징하고, 에이전트가 추론한다

Kinlayer는 관계 조언, 메시지 초안, 자연어 브리핑을 직접 생성하지 않습니다.

대신 관계 맥락을 검색하고, 점수화하고, 출처와 근거를 붙여 에이전트가 사용할 수 있는 형태로 제공합니다.

## MVP 범위

Kinlayer MVP는 로컬에서 실행되는 단일 사용자 워크스페이스를 전제로 합니다.

포함되는 주요 기능은 다음과 같습니다.

- 로컬 HTTP API
- CLI 기반 초기화, 상태 확인, 기억 저장, 검색 디버그
- 최소 Web UI 제어판
- 사람/별칭/관계/관찰 저장
- 출처를 포함한 즉시 저장과 변경 이력
- 명시적 사용자 정정 적용
- 출처와 증거 관리
- 근거·시점·인물 역할을 포함한 검색과 Context Pack
- 1-hop ego graph
- 관찰 기반 임베딩 검색
- 선택적 로컬 bearer token 보호

2026-10-01 목업 평가 후 사용자가 기존 프론트엔드의 전체 교체를 승인했습니다.
실행 앱은 `frontend/`의 React/Vite 구현이며, 가져온 `frontend_v2/`는 디자인·상호작용
참고 자료로 보존합니다. 새 UI는 실제 API를 사용하고 저장 전 승인·AI 사용 정책을 요구하지 않습니다.
[교체 계획과 결정 변경 기록](docs/plans/frontend-rebuild.md)의 UI01–UI09를 기준으로 검증합니다.

```text
주요 탐색: /people /memories /graph /changes
상세 보기: /people/:id /memories?record=... /sources/:id
보조 탐색: /search /settings /legacy
```

## 로컬 우선 설계

Kinlayer는 로컬 또는 self-hosted 환경에서 실행하는 개인 관계 맥락 레이어입니다. Docker Compose 기본값은 Web UI와 API를 같은 네트워크의 다른 기기에서도 접속할 수 있게 호스트 인터페이스에 공개하고, Postgres만 `127.0.0.1`에 묶어 둡니다.

MVP에는 사용자 계정, 로그인 세션, 조직, 워크스페이스 멤버십, 클라우드 동기화가 없습니다. 대신 로컬 환경에서 필요한 경우 `KINLAYER_API_TOKEN`으로 간단한 bearer token 보호를 켤 수 있습니다.

이 선택은 관계 맥락이 민감한 데이터라는 점을 전제로 합니다. Kinlayer는 사용자의 관계 기억을 외부 서비스에 맡기는 제품이 아니라, 로컬 또는 self-hosted 환경에서 AI 에이전트가 호출할 수 있는 컨텍스트 계층으로 설계됩니다.

## 현재 상태

이 저장소는 Kinlayer MVP의 로컬 API, Web 제어판, CLI, 즉시 저장, 정정·철회·재귀속, context pack, ego graph, 임베딩 기반 검색 흐름을 포함합니다.

Kinlayer는 아직 클라우드 서비스나 일반 사용자용 패키지 앱이 아니라, 로컬 또는 self-hosted 환경에서 AI 에이전트가 사용할 관계 맥락 레이어를 검증하는 MVP입니다.

## 설치와 실행

Kinlayer의 기본 실행 방식은 Docker Compose입니다. API, Web UI, Postgres를 컨테이너로 올리며, Postgres 데이터는 named volume에 보관됩니다.

필요한 도구:

- Git
- Docker Desktop 또는 Docker Engine

처음 설치할 때는 저장소를 받은 뒤 `.env` 파일을 만듭니다.

```bash
git clone git@github.com:Gyu-bot/kinlayer.git
cd kinlayer
cp .env.example .env
```

기본값 그대로 실행하면 embedding provider 없이 Kinlayer가 시작됩니다.

```bash
docker compose up -d --build
```

API 컨테이너는 시작할 때 DB 마이그레이션을 자동 적용하고, protected self entity가 없으면 `.env`의 `KINLAYER_SELF_NAME` 값으로 생성합니다.

실행 후 같은 머신에서는 다음 주소를 사용합니다.

```text
http://127.0.0.1:5173
http://127.0.0.1:8765
```

같은 로컬 네트워크의 다른 기기에서는 서버 머신의 IP를 넣어 접속합니다.

```text
http://<server-ip>:5173
http://<server-ip>:8765
```

Web UI를 `http://<server-ip>:5173`으로 열면 기본 API 주소도 같은 host의 `:8765`를 사용합니다. 다른 API 주소를 강제로 쓰고 싶으면 `.env`에 `VITE_KINLAYER_API_URL`을 설정하고 컨테이너를 다시 올립니다.

로컬 스택이 뜬 뒤 fixture와 API/CLI 수용 스모크를 실행할 수 있습니다. 이 스모크는 후보 승인, 명시적 정정, 중복 사람 병합, 검색/context/graph 연속성을 함께 확인합니다.

```bash
python3 scripts/load-acceptance-fixtures.py --api-url http://127.0.0.1:8765
python3 scripts/smoke-acceptance-api.py --api-url http://127.0.0.1:8765
KINLAYER_API_URL=http://127.0.0.1:8765 scripts/smoke-acceptance-cli.sh
```

로컬 bearer token은 기본 설치에 필요하지 않습니다. `.env`의 `KINLAYER_API_TOKEN`을 비워두면 Web UI와 API를 바로 사용할 수 있습니다.

로컬 네트워크에 API를 공개하는 경우에는 `.env`에 값을 넣고 컨테이너를 다시 올리는 것을 권장합니다.

```dotenv
KINLAYER_API_TOKEN=원하는-로컬-토큰
```

관계 reconciliation 액션 API는 일반 API 토큰과 분리된
`KINLAYER_RECONCILIATION_TOKEN`을 사용합니다. 이 값이 비어 있으면
`/api/reconciliation/actions` POST/GET은 비활성화되며, 일반
`KINLAYER_API_TOKEN`만으로는 접근할 수 없습니다. 토큰은 응답이나
시스템 설정 조회에 노출되지 않습니다.

토큰을 켠 경우에만 Web UI의 `/settings`에서 같은 값을 API 토큰으로 저장해야 관계 데이터 화면을 볼 수 있습니다. token 값은 저장 후 다시 표시되지 않습니다.

## 프론트엔드 개발과 가상 데이터 검증

일반 개발은 실행 중인 API에 연결합니다. `frontend/`에서 다음 명령을 사용합니다.
Vite 개발 서버와 빌드 프리뷰의 기본 주소는 기존과 같이 `0.0.0.0:5173`입니다.

```bash
cd frontend
npm ci
npm run dev
```

```bash
npm test
npm run build
npm run preview
```

운영 데이터와 분리해서 새 화면의 쓰기·출처·변경 이력을 검증하려면 저장소 루트에서
가상 데이터용 API를 실행합니다. 실제 FastAPI 경로와 임시 SQLite DB를 사용하며,
DB는 프로세스 종료 시 제거됩니다. 기존 DB나 서비스 설정을 대상으로 실행하지 않습니다.

```bash
PYTHONPATH=backend/src uv run python scripts/serve-frontend-demo.py --port 8785
```

다른 터미널의 `frontend/`에서 다음과 같이 화면을 연결합니다. 사용 중인 서버와 포트가
겹치지 않는지 먼저 확인하고, 이미 5173 포트를 사용 중이면 `--port`로 빈 포트를 지정합니다.

```bash
VITE_KINLAYER_API_URL=http://127.0.0.1:8785 VITE_KINLAYER_PREVIEW_LABEL='가상 데이터 · 테스트 API' npm run dev -- --host 127.0.0.1 --strictPort
```

이 실행법은 검증용이며 운영 배포 완료를 의미하지 않습니다. 화면 증거와 테스트 결과는
[프론트엔드 v2 검증 기록](docs/verification/frontend-v2/README.md)에 모읍니다.

## OpenAI embedding 설정

OpenAI-compatible embedding API key는 Web UI에 직접 입력하지 않습니다. 서버 컨테이너가 읽는 `.env`에 설정합니다.

```dotenv
KINLAYER_EMBEDDING_API_KEY=sk-...
```

API key만 설정하면 OpenAI-compatible embedding이 켜집니다. provider는 `openai_compatible`, API URL은 `https://api.openai.com/v1/embeddings`, model은 `text-embedding-3-small`, dimension은 `1536`을 기본값으로 사용합니다.

`.env`를 수정한 뒤에는 컨테이너를 다시 빌드/시작합니다.

```bash
docker compose up -d --build
```

설정이 반영되면 `/settings`에서 embedding provider, model, dimension, API URL configured, API key configured 상태를 확인할 수 있습니다. API key 실제 값은 화면에 표시하지 않습니다.

## 업데이트

새 버전으로 업데이트할 때는 최신 코드를 받은 뒤 앱 컨테이너만 다시 빌드합니다. 필요한 DB 마이그레이션은 API 컨테이너 시작 시 자동 적용됩니다.

```bash
git pull --ff-only
docker compose up -d --build api web
```

운영 데이터가 쓰이기 시작한 뒤에는 일반 업데이트 때 Postgres 이미지를 매번 pull하거나 재기동하지 않는 편이 안전합니다. Postgres/pgvector 이미지 갱신은 보안 패치나 운영 점검이 필요할 때 백업 후 별도 유지보수 작업으로 진행합니다.

일시 중지는 컨테이너만 멈춥니다.

```bash
docker compose stop
```

컨테이너를 제거하더라도 기본 데이터는 `kinlayer-postgres-data` volume에 남습니다.

```bash
docker compose down
```

## 사용자가 할 수 있는 일

Kinlayer를 사용하면 다음 일을 할 수 있습니다.

- 사람, 별칭, 프로필 사실, 관계, 최근 관찰을 한곳에서 관리합니다.
- 에이전트가 출처와 함께 저장한 새 정보를 바로 조회합니다.
- 잘못 저장된 정보는 명시적 정정으로 바로 고칩니다.
- 보고된 진술·추론·불확실성·출처를 확인하고, 잘못된 기억을 철회하거나 다른 사람에게 옮깁니다.
- 검색 결과와 Context Pack을 확인해 에이전트가 어떤 맥락을 참고하는지 점검합니다.
- 1-hop ego graph로 사용자 주변의 관계 구조를 살펴봅니다.

## 주요 화면

- `/people`: 이름·별칭 검색, 관계 필터, 최근 참조순·이름순 정렬, 목록/카드 전환,
  인물 미리보기와 새 인물 추가를 제공합니다. 필터·집계·페이지 이동은 서버가 처리합니다.
- `/people/:id`: 프로필, 관계, 기억별 출처, 변경 이력을 보고 이름·별칭을 편집합니다.
- `/memories`: 사람·종류·근거·현재/과거 상태·본문으로 기억을 찾습니다. 각 기억의 정확한
  참조와 출처를 확인하고 하나씩 정정·철회·다른 인물로 옮길 수 있습니다.
- `/graph`: 선택한 사람의 직접 관계를 실제 ontology 종류와 방향에 맞춰 표시합니다.
  모바일 관계 목록에서도 같은 기억과 출처를 열 수 있습니다.
- `/changes`: 새 기억·정정·철회·재귀속의 전후 내용과 변경 근거를 확인합니다.
- `/sources/:id`: 짧은 원문 발췌, 말한 사람, 출처 시점·위치와 연결된 현재·과거 기억을 봅니다.
- `/search`: 검색 및 Context Pack을 조회하고 근거·불확실성·부분 날짜와 원래 기록을 확인합니다.
- `/settings`: 연결·인증과 임베딩 설정 및 실제 데이터 처리 현황을 구분해 보여줍니다.
- `/legacy`: 과거 후보와 에이전트 쓰기 기록을 읽기 전용으로 조회합니다. 적용된 필터의
  JSONL은 처음 200건까지, CSV는 현재 페이지의 작업만 내보냅니다.

기억 변경은 `POST /api/memories`를 사용합니다. 서버의 저장 계약 v2 지원을 확인한 뒤,
정확한 이전 기록·갱신 시각과 이번 입력의 출처를 함께 제출합니다. 실패한 저장은 초안을
보존하고 동일 요청을 재시도할 수 있습니다. 원래 내용과 출처는 변경 이력에서 확인합니다.
인물 생성과 이름·별칭 편집은 기존 identity API를 사용합니다.

불확실한 미래 계획을 현재 프로필로 확정하지 않으며, 알려지지 않은 날짜·발화 시점을
채우지 않습니다. localStorage에 보관하는 것은 사용자가 입력한 API 토큰뿐입니다.
이 교체 자체로 운영 서비스를 배포·재시작하거나 DB를 마이그레이션하지 않습니다.

## 설정에서 확인하는 것

설정 화면은 Kinlayer가 현재 어떤 방식으로 동작하는지 보여줍니다.

- API 연결 상태와 데이터베이스 상태
- 서버에 bearer token 보호가 켜져 있는지 여부
- 브라우저에 로컬 API token이 저장되어 있는지 여부
- embedding provider, model, dimension, 상태
- OpenAI-compatible embedding API URL과 API key가 서버에 설정되어 있는지 여부
- 관찰 임베딩의 전체·준비됨·대기·실패·갱신 필요 개수. 서버 설정의 준비 상태와 별도로 표시합니다.

OpenAI embedding API key 같은 secret 값은 화면에 다시 표시하지 않습니다. 임베딩 제공자 비밀 값은 서버에서 관리합니다. 연결용 API 토큰은 사용자가 이 브라우저에 저장·삭제할 수 있고 저장된 값은 다시 표시하지 않습니다.

## 에이전트와 함께 쓰는 방식

Kinlayer의 기본 사용자는 사람 혼자가 아니라 AI 에이전트와 사람의 조합입니다.

에이전트는 대화 전에 관련 사람과 최근 맥락을 조회하고, 대화 중 새로 드러난 정보를 출처와 함께 `/api/memories`로 즉시 저장합니다. 요청은 한 번에 하나의 주장을 담고, 재시도 가능한 `request_id`와 `claim_basis`를 포함합니다.

먼저 entity resolve로 사람을 확인하고, 명확한 새 인물은 바로 생성합니다. `그 사람`처럼 대상을 식별할 수 없으면 임의로 기존 사람과 합치지 않습니다. 사용자가 지적한 오류는 정확한 이전 record ref를 대상으로 `correct`, `retract`, `reattribute`를 실행합니다. 출처·기록·변경 이력은 한 transaction으로 저장하며, 검색 결과나 AI 답변을 새 증거로 재사용하지 않습니다. 공인/뉴스 인물, 허구 예시, 일반 집단을 사용자 관계로 임의 저장하지 않습니다.

이 구조 덕분에 에이전트는 관계 맥락을 더 잘 기억할 수 있지만, 최종 통제권은 사용자에게 남습니다.

## 관련 문서

README는 제품 설명과 기본 설치 흐름을 다룹니다. API 계약, 데이터 모델, 구현 작업 추적은 아래 문서에서 다룹니다.

- `docs/README.md`: 문서 구조와 active/archive 구분
- `docs/specs/prd.md`: 제품 요구사항과 원칙
- `docs/plans/save-first-memory-schema.md`: 현재 즉시 저장·스키마·기존 데이터 전환 계약
- `docs/plans/frontend-rebuild.md`: 프론트엔드 교체 승인 변경 기록과 UI01–UI09 수용 기준
- `docs/verification/frontend-v2/README.md`: 프론트엔드 교체의 브라우저·API·회귀 검증 근거와 적용 범위
- `docs/plans/relationship-curation-cycle.md`: 이전 후보 curation 구현 이력과 호환 경계
- `docs/kinlayer-roadmap.md`: 사용자가 구현 지시를 내릴 때 보는 한글 로드맵
- `docs/specs/api-spec.md`: HTTP API 계약
- `docs/specs/data-model.md`: 데이터 모델
- `docs/specs/cli-spec.md`: CLI 계약
- `docs/specs/web-ui-spec.md`: Web UI 범위
- `docs/specs/acceptance-scenarios.md`: MVP 수용 시나리오
- `docs/specs/context-output-contract.md`: 검색 결과와 Context Pack 계약
- `docs/specs/candidate-lifecycle-and-payload.md`: 기존 후보 API의 호환 계약
- `docs/agents/agent-integration-notes.md`: 에이전트 통합 메모
