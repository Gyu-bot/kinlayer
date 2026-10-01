#!/usr/bin/env node
'use strict';

// Reproducible regression checks added during the repository handoff.
// These are new checks, not the unavailable original 24-check suite.
// DOM/events/storage only: jsdom does not verify browser pixels or CSS layout.
// Usage: node frontend_v2/interaction-checks.cjs [path/to/frontend/node_modules]
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const moduleRoot = process.argv[2]
  ? path.resolve(process.argv[2])
  : path.resolve(__dirname, '../frontend/node_modules');
const { JSDOM, VirtualConsole } = require(path.join(moduleRoot, 'jsdom'));
const storageKey = 'kinlayer-v2-demo-1';
const scripts = new Map(['demo-data.js', 'app.js'].map(file => [file, fs.readFileSync(path.join(__dirname, file), 'utf8')]));
const tests = [];
let openApps = [];

function load(page = 'people.html', saved = null, width = 1440) {
  const file = page.split('?')[0];
  const errors = [];
  const virtualConsole = new VirtualConsole();
  virtualConsole.on('jsdomError', error => errors.push(error.message));
  const dom = new JSDOM(fs.readFileSync(path.join(__dirname, file), 'utf8'), {
    url: `https://kinlayer-mockup.invalid/${page}`,
    runScripts: 'outside-only',
    virtualConsole,
    // External resources are deliberately disabled; this never calls the API.
  });
  const { window } = dom;
  openApps.push({ dom, errors });
  window.matchMedia = query => ({
    matches: query === '(max-width:1030px)' && width <= 1030,
    media: query,
  });
  window.CSS ||= {};
  window.CSS.escape ||= value => String(value).replace(/[^a-zA-Z0-9_-]/g, char => `\\${char.codePointAt(0).toString(16)} `);
  // jsdom lacks the native modal methods. Only model open/close and its event;
  // focus trapping and browser dialog geometry require separate browser QA.
  window.HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
  window.HTMLDialogElement.prototype.close = function () {
    this.removeAttribute('open');
    this.dispatchEvent(new window.Event('close'));
  };
  if (saved) window.localStorage.setItem(storageKey, saved);
  const document = window.document;
  for (const element of document.querySelectorAll('script[src]')) {
    const source = element.getAttribute('src');
    assert.ok(scripts.has(source), `Unexpected external script: ${source}`);
    window.eval(scripts.get(source));
  }
  const one = selector => {
    const element = document.querySelector(selector);
    assert.ok(element, `Missing element: ${selector}`);
    return element;
  };
  return {
    window, document, one,
    all: selector => Array.from(document.querySelectorAll(selector)),
    click: selector => one(selector).dispatchEvent(new window.MouseEvent('click', { bubbles: true })),
    key: (selector, key) => one(selector).dispatchEvent(new window.KeyboardEvent('keydown', { key, bubbles: true, cancelable: true })),
    set(selector, value, event = 'input') {
      const element = one(selector);
      element.value = value;
      element.dispatchEvent(new window.Event(event, { bubbles: true }));
    },
    submit: selector => one(selector).dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true })),
    saved: () => window.localStorage.getItem(storageKey),
    state: () => JSON.parse(window.localStorage.getItem(storageKey) || JSON.stringify(window.KinlayerDemo)),
  };
}

function test(name, run) { tests.push({ name, run }); }
function ids(app) { return app.all('.person-row').map(element => element.dataset.id); }
function person(app, id = 'minji') { return app.state().people.find(item => item.id === id); }
function selectReview(app, id) { app.click(`[data-action="select-review"][data-id="${id}"]`); }
function addPerson(app, name = '새 인물') {
  app.click('[data-action="new-person"]');
  app.set('#person-name-input', name);
  app.set('#person-alias-input', '새 별칭, 새 별칭');
  app.set('#new-relation', 'friend', 'change');
  app.submit('#person-form');
  return app.state().people.find(item => item.name === name);
}

test('네 화면과 진입 페이지 렌더링 / HTML ID 중복 없음', () => {
  for (const page of ['index.html', 'people.html', 'person.html?person=minji', 'graph.html', 'reviews.html']) {
    const app = load(page);
    assert.ok(app.one('main h1').textContent.trim());
    assert.equal(app.document.documentElement.lang, 'ko');
    if (page === 'index.html') {
      assert.equal(app.one('meta[http-equiv="refresh"]').content, '0;url=people.html');
      assert.equal(app.one('[data-od-id="open-people"]').getAttribute('href'), 'people.html');
    }
    const elements = app.all('[id]').map(element => element.id);
    assert.equal(new Set(elements).size, elements.length, `${page}: duplicate HTML id`);
  }
});

test('사람 이름과 별칭 검색', () => {
  const app = load();
  app.set('#people-search', '엄마');
  assert.deepEqual(ids(app), ['eunhee']);
  app.set('#people-search', '  김민지  ');
  assert.deepEqual(ids(app), ['minji']);
});

test('빈 검색 결과에서 검색과 필터 초기화', () => {
  const app = load();
  app.click('[data-action="people-filter"][data-value="family"]');
  app.set('#people-search', '존재하지 않는 인물');
  assert.deepEqual(ids(app), []);
  assert.match(app.one('#people-results .empty-state').textContent, /일치하는 사람이 없어요/);
  app.click('[data-action="clear-search"]');
  assert.equal(ids(app).length, 8);
  assert.equal(app.one('#people-search').value, '');
  assert.equal(app.one('[data-action="people-filter"][data-value="all"]').getAttribute('aria-pressed'), 'true');
});

test('관계 필터와 검색 결과가 바뀌면 미리보기도 표시된 인물로 동기화', () => {
  const app = load();
  assert.equal(app.one('#preview h2').textContent, '김민지');
  app.click('[data-action="people-filter"][data-value="friend"]');
  assert.equal(app.one('#preview h2').textContent, '이지호');
  assert.equal(app.one('.person-row.selected').dataset.id, 'jiho');
  app.set('#people-search', '수진');
  assert.equal(app.one('#preview h2').textContent, '최수진');
  assert.deepEqual(ids(app), ['sujin']);
  app.set('#people-search', '없는 이름');
  assert.equal(app.document.querySelector('#preview [data-od-id="selected-person-panel"]'), null);
  assert.equal(app.document.querySelector('.person-row.selected'), null);
  assert.match(app.one('#preview').textContent, /조건에 맞는 인물/);
});

test('필터와 빈 검색이 적용되어 있어도 추가한 인물은 즉시 목록/미리보기에 표시', () => {
  const app = load();
  app.click('[data-action="people-filter"][data-value="family"]');
  app.set('#people-search', '추가 전에는 없는 이름');
  const added = addPerson(app, '신규 친구');
  assert.equal(app.one('#people-search').value, '');
  assert.equal(app.one('[data-action="people-filter"][data-value="all"]').getAttribute('aria-pressed'), 'true');
  assert.ok(ids(app).includes(added.id));
  assert.equal(app.one('.person-row.selected').dataset.id, added.id);
  assert.equal(app.one('#preview h2').textContent, '신규 친구');
});

test('사람 관계 필터와 이름 정렬', () => {
  const app = load();
  app.click('[data-action="people-filter"][data-value="coworker"]');
  assert.deepEqual(ids(app), ['minji', 'seojun', 'doyun']);
  app.click('[data-action="people-filter"][data-value="all"]');
  app.set('#people-sort', 'name', 'change');
  const names = app.all('.person-row .person-name').map(element => element.textContent);
  assert.deepEqual(names, [...names].sort((a, b) => a.localeCompare(b, 'ko')));
  assert.equal(names.length, 8);
});

test('카드/목록 보기 전환과 키보드로 인물 미리보기', () => {
  const app = load();
  app.click('[data-action="view"][data-value="cards"]');
  assert.ok(app.one('.people-table').classList.contains('cards'));
  assert.equal(app.one('[data-value="cards"]').getAttribute('aria-pressed'), 'true');
  app.key('[data-action="select-person"][data-id="jiho"]', 'Enter');
  assert.equal(app.one('#preview h2').textContent, '이지호');
  app.click('[data-action="view"][data-value="list"]');
  assert.ok(!app.one('.people-table').classList.contains('cards'));
});

test('사람 추가 필수 이름 검증과 취소 시 무변경', () => {
  const app = load();
  const before = app.state();
  app.click('[data-action="new-person"]');
  app.set('#person-name-input', '   ');
  app.submit('#person-form');
  assert.equal(app.one('#form-error').hidden, false);
  assert.match(app.one('#form-error').textContent, /이름/);
  assert.equal(app.one('#modal').open, true);
  assert.deepEqual(app.state(), before);
  app.click('#modal [data-action="close-modal"]');
  assert.equal(app.one('#modal').open, false);
  assert.deepEqual(app.state(), before);
});

test('사람 추가 / 별칭 중복 제거 / 입력 HTML 이스케이프', () => {
  const app = load();
  const name = '<img src=x onerror="window.injected=true">';
  const added = addPerson(app, name);
  assert.ok(added);
  assert.deepEqual(added.aliases, ['새 별칭']);
  assert.equal(app.one('#total-people').textContent, '9');
  assert.equal(app.one(`[data-id="${added.id}"] .person-name`).textContent, name);
  assert.equal(app.document.querySelector('img[src="x"]'), null);
  assert.equal(app.window.injected, undefined);
  assert.ok(app.state().edges.some(edge => edge.b === added.id && edge.type === 'friend'));
});

test('localStorage 재로딩과 새 인물 상세 링크 복원', () => {
  const app = load();
  const added = addPerson(app);
  const saved = app.saved();
  const reloaded = load('people.html', saved);
  assert.ok(ids(reloaded).includes(added.id));
  const detail = load(`person.html?person=${added.id}`, saved);
  assert.equal(detail.one('[data-od-id="person-name"]').textContent, '새 인물');
  assert.deepEqual(detail.state(), app.state());
});

test('프로필 편집의 이전 값과 원 출처 보존', () => {
  const app = load('person.html?person=minji');
  const before = app.state();
  const original = person(app).facts.find(fact => fact.type === 'organization');
  app.click('[data-od-id="edit-profile"]');
  app.set('#person-org-input', '새 스튜디오');
  app.submit('#person-form');
  const updated = person(app).facts.find(fact => fact.type === 'organization');
  assert.equal(person(app).org, '새 스튜디오');
  assert.equal(updated.value, '새 스튜디오');
  assert.deepEqual(updated.previous, { value: original.value, source: original.source });
  assert.equal(app.state().sources[updated.source].priorId, original.source);
  assert.deepEqual(app.state().sources[original.source], before.sources[original.source]);
  app.click(`[data-action="source"][data-id="${updated.source}"]`);
  assert.match(app.one('#modal').textContent, /수정 이전의 출처/);
  assert.ok(app.one('#modal').textContent.includes(before.sources[original.source].excerpt));
});

test('AI 사용 범위 변경과 화면/저장 값 일치', () => {
  const app = load('person.html?person=minji');
  app.click('[data-action="policy"]');
  app.one('input[name="policy"][value="ask_before_use"]').checked = true;
  app.submit('#policy-form');
  assert.equal(person(app).policy, 'ask_before_use');
  assert.match(app.one('.policy-value').textContent, /사용 전 확인/);
});

test('맥락 정정 필수 입력 검증과 원 출처 보존', () => {
  const app = load('person.html?person=minji');
  const before = app.state();
  const old = person(app).contexts.find(context => context.id === 'minji-comms');
  app.click('[data-action="edit-context"][data-id="minji-comms"]');
  app.set('#context-title', '');
  app.submit('#context-form');
  assert.equal(app.one('#form-error').hidden, false);
  assert.deepEqual(app.state(), before);
  app.set('#context-title', '정정한 소통 맥락');
  app.set('#context-text', '대화 후 요점을 문서로 공유해요.');
  app.submit('#context-form');
  const updated = person(app).contexts.find(context => context.id === old.id);
  assert.equal(updated.title, '정정한 소통 맥락');
  assert.equal(updated.text, '대화 후 요점을 문서로 공유해요.');
  assert.deepEqual(updated.previous, { text: old.text, source: old.source });
  assert.equal(app.state().sources[updated.source].priorId, old.source);
  assert.deepEqual(app.state().sources[old.source], before.sources[old.source]);
  app.click(`[data-action="source"][data-id="${updated.source}"]`);
  assert.ok(app.one('#modal').textContent.includes(before.sources[old.source].excerpt));
});

test('존재하지 않거나 self 또는 빈 person URL은 다른 인물로 대체하지 않음', () => {
  for (const id of ['does-not-exist', 'self', '']) {
    const app = load(`person.html?person=${id}`);
    assert.match(app.one('main h1').textContent, /인물을 찾을 수 없어요/);
    assert.equal(app.document.querySelector('[data-od-id="person-hero"]'), null);
    assert.equal(app.document.querySelector('[data-action="edit-person"]'), null);
  }
});

test('관계 목록에서 기준 인물은 잘못된 self 상세 링크를 만들지 않음', () => {
  const app = load('person.html?person=minji');
  app.click('[data-action="person-tab"][data-value="relations"]');
  assert.equal(app.document.querySelector('a[href="person.html?person=self"]'), null);
  assert.match(app.one('[data-od-id="relationships-content"]').textContent, /나/);
});

test('리뷰 반영 후 프로필 값/이전 값/원 출처/처리 목록 일치', () => {
  const app = load('reviews.html');
  const before = app.state();
  app.click('[data-action="review-accept"][data-id="review-1"]');
  const result = app.state();
  const review = result.reviews.find(item => item.id === 'review-1');
  const updated = person(app).facts.find(fact => fact.type === 'organization');
  assert.equal(review.status, 'accepted');
  assert.equal(person(app).org, '모노랩');
  assert.equal(updated.previous.value, '오브 스튜디오');
  assert.equal(result.sources[review.source].priorId, 'review-minji');
  assert.deepEqual(result.sources['review-minji'], before.sources['review-minji']);
  assert.deepEqual(result.sources['minji-work'], before.sources['minji-work']);
  app.click('[data-action="review-filter"][data-value="processed"]');
  assert.match(app.one('.review-detail').textContent, /반영 완료/);
  assert.equal(app.document.querySelector('[data-action="review-accept"]'), null);
});

test('리뷰 수정 후 반영의 빈 입력 차단과 별도 정정 출처', () => {
  const app = load('reviews.html');
  app.click('[data-action="review-edit"][data-id="review-1"]');
  app.set('#review-value', '  ');
  app.submit('#review-form');
  assert.equal(app.one('#form-error').hidden, false);
  assert.equal(person(app).org, '오브 스튜디오');
  app.set('#review-value', '확인한 회사');
  app.submit('#review-form');
  const result = app.state();
  const review = result.reviews.find(item => item.id === 'review-1');
  assert.equal(review.status, 'edited_accepted');
  assert.equal(review.after, '확인한 회사');
  assert.equal(person(app).org, '확인한 회사');
  assert.equal(result.sources[review.source].priorId, 'review-minji');
  assert.equal(result.sources[review.source].title, '리뷰에서 직접 정정');
});

test('리뷰 추가 확인은 미처리로 유지되며 다시 반영 가능', () => {
  const app = load('reviews.html');
  app.click('[data-action="review-clarify"][data-id="review-1"]');
  assert.equal(app.state().reviews[0].status, 'needs_clarification');
  assert.equal(person(app).org, '오브 스튜디오');
  assert.equal(app.one('[data-review-count]').textContent, '3');
  assert.equal(app.one('[data-action="review-clarify"]').disabled, true);
  app.click('[data-action="review-accept"][data-id="review-1"]');
  assert.equal(app.state().reviews[0].status, 'accepted');
});

for (const [action, status, label] of [['review-reject', 'rejected', '거절됨'], ['review-archive', 'archived', '보관됨']]) {
  test(`리뷰 ${label}: 기존 인물/관계/출처 유지와 처리 목록`, () => {
    const app = load('reviews.html');
    const before = app.state();
    app.click(`[data-action="${action}"][data-id="review-1"]`);
    assert.equal(app.state().reviews[0].status, status);
    for (const field of ['people', 'edges', 'sources']) assert.deepEqual(app.state()[field], before[field]);
    app.click('[data-action="review-filter"][data-value="processed"]');
    assert.match(app.one('.review-detail').textContent, new RegExp(label));
  });
}

test('친구 관계 반영 후 동료/친구 병존과 각 목록 필터/그래프 일치', () => {
  const app = load('reviews.html');
  selectReview(app, 'review-2');
  app.click('[data-action="review-accept"][data-id="review-2"]');
  const edges = app.state().edges.filter(edge => edge.a === 'self' && edge.b === 'seojun');
  assert.deepEqual(edges.map(edge => edge.type).sort(), ['coworker', 'friend']);
  const people = load('people.html', app.saved());
  for (const relation of ['coworker', 'friend']) {
    people.click(`[data-action="people-filter"][data-value="${relation}"]`);
    assert.ok(ids(people).includes('seojun'));
    assert.match(people.one('[data-id="seojun"] .relation-tags').textContent, /직장 동료.*친구/);
  }
  const graph = load('graph.html', app.saved());
  const paths = edges.map(edge => graph.one(`.edge-group[data-id="${edge.id}"] .graph-edge`).getAttribute('d'));
  assert.equal(new Set(paths).size, 2, 'parallel relations must have distinct paths');
});

test('소통 맥락 리뷰 반영 시 출처와 AI 사용 범위 보존', () => {
  const app = load('reviews.html');
  selectReview(app, 'review-3');
  app.click('[data-action="review-accept"][data-id="review-3"]');
  const context = person(app, 'seoyeon').contexts.find(item => item.id === 'accepted-review-3');
  assert.equal(context.type, 'communication_preference');
  assert.equal(context.policy, 'ask_before_use');
  assert.equal(context.text, '통화 전 메시지로 시간 확인');
  assert.equal(app.state().sources[context.source].priorId, 'review-seoyeon');
});

test('그래프 관계 필터와 중심 인물 변경', () => {
  const app = load('graph.html');
  app.set('#graph-relation', 'family', 'change');
  assert.deepEqual(app.all('.edge-group').map(element => element.dataset.id), ['edge-eunhee', 'edge-haneul']);
  assert.equal(app.all('.graph-node').length, 3);
  app.set('#graph-relation', 'all', 'change');
  app.set('#graph-focal', 'minji', 'change');
  assert.match(app.one('.graph-caption h2').textContent, /김민지/);
  assert.deepEqual(app.all('.edge-group').map(element => element.dataset.id), ['edge-minji', 'edge-team']);
  assert.equal(app.one('#graph-inspector h2').textContent, '김민지');
});

test('그래프 노드 키보드 선택과 관계 선택의 출처 표시', () => {
  const app = load('graph.html');
  app.key('.graph-node[data-id="jiho"]', 'Enter');
  assert.equal(app.one('#graph-inspector h2').textContent, '이지호');
  assert.equal(app.one('.graph-node[data-id="jiho"]').getAttribute('aria-pressed'), 'true');
  app.key('.edge-group[data-id="edge-minji"]', ' ');
  assert.match(app.one('#graph-inspector').textContent, /선택한 관계/);
  assert.match(app.one('#graph-inspector').textContent, /직장 동료/);
  app.click('#graph-inspector [data-action="source"]');
  assert.ok(app.one('#modal').textContent.includes(app.state().sources['minji-work'].excerpt));
});

test('모바일 관계 목록의 관계명과 edge 선택/선택 상태 동기화', () => {
  const app = load('graph.html', null, 390);
  const rows = app.all('.graph-mobile-list button');
  assert.equal(rows.length, 8);
  for (const row of rows) {
    assert.equal(row.dataset.action, 'graph-edge');
    const edge = app.state().edges.find(item => item.id === row.dataset.id);
    assert.equal(row.querySelector('small').textContent, app.window.KinlayerDemo.relations[edge.type]);
  }
  app.click('.graph-mobile-list [data-id="edge-seojun"]');
  assert.equal(app.one('#graph-inspector h2').textContent, '박서준');
  assert.match(app.one('#graph-inspector').textContent, /선택한 관계/);
  assert.equal(app.one('.graph-mobile-list [data-id="edge-seojun"]').getAttribute('aria-pressed'), 'true');
  assert.equal(app.one('.edge-group[data-id="edge-seojun"]').getAttribute('aria-pressed'), 'true');
  app.click('.graph-node[data-id="minji"]');
  assert.equal(app.one('.graph-mobile-list [data-id="edge-seojun"]').getAttribute('aria-pressed'), 'false');
});

test('그래프 확대/축소 한계, 전체 맞춤, 보기 초기화', () => {
  const app = load('graph.html');
  for (let i = 0; i < 10; i++) app.click('[data-action="zoom"][data-value="in"]');
  assert.equal(app.one('#zoom-level').textContent, '180%');
  for (let i = 0; i < 10; i++) app.click('[data-action="zoom"][data-value="out"]');
  assert.equal(app.one('#zoom-level').textContent, '60%');
  app.click('[data-action="fit-graph"]');
  assert.equal(app.one('#zoom-level').textContent, '100%');
  assert.match(app.one('#graph-scene').getAttribute('transform'), /scale\(1\)/);
  app.set('#graph-focal', 'minji', 'change');
  app.set('#graph-relation', 'coworker', 'change');
  app.click('[data-action="zoom"][data-value="in"]');
  app.click('[data-action="reset-graph"]');
  assert.equal(app.one('#graph-focal').value, 'self');
  assert.equal(app.one('#graph-relation').value, 'all');
  assert.equal(app.one('#zoom-level').textContent, '100%');
  assert.equal(app.all('.graph-node').length, 9);
});

test('9번째 사람 등록 후 그래프 노드 좌표 중복 없음', () => {
  const app = load();
  addPerson(app, '추가된 아홉 번째 사람');
  const graph = load('graph.html', app.saved());
  const positions = graph.all('.graph-node').map(element => element.getAttribute('transform'));
  assert.equal(positions.length, 10);
  assert.equal(new Set(positions).size, 10);
});

test('목업 초기화 확인 취소는 보존, 확정은 데모 상태 복원', () => {
  const app = load();
  addPerson(app);
  app.click('[data-action="about"]');
  app.click('[data-action="reset-confirm"]');
  app.click('#modal [data-action="close-modal"]');
  assert.equal(app.state().people.length, 9);
  app.click('[data-action="about"]');
  app.click('[data-action="reset-confirm"]');
  app.click('[data-action="reset-demo"]');
  assert.equal(app.state().people.length, 8);
  assert.equal(ids(app).length, 8);
});

(async () => {
  let passed = 0;
  for (const { name, run } of tests) {
    openApps = [];
    try {
      await run();
      // Let zero-delay focus callbacks execute and capture any runtime errors.
      await new Promise(resolve => setTimeout(resolve, 5));
      for (const app of openApps) assert.deepEqual(app.errors, [], 'Unexpected jsdom runtime errors');
      passed++;
      console.log(`PASS ${name}`);
    } catch (error) {
      console.error(`FAIL ${name}\n${error.stack}`);
      process.exitCode = 1;
    } finally {
      for (const app of openApps) app.dom.window.close();
    }
  }
  console.log(`\n${passed}/${tests.length} checks passed (DOM/events/localStorage; no visual layout verification).`);
})();
