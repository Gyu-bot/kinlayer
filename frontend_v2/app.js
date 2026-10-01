(() => {
  'use strict';
  const seed=window.KinlayerDemo, storageKey='kinlayer-v2-demo-1';
  const clone=value=>JSON.parse(JSON.stringify(value));
  let state=clone(seed), storageAvailable=true;
  try{const saved=JSON.parse(localStorage.getItem(storageKey));if(saved?.version===1&&Array.isArray(saved.people)&&Array.isArray(saved.edges)&&Array.isArray(saved.reviews)&&saved.sources)state=saved;}catch{storageAvailable=false;}
  const page=document.body.dataset.page;
  const params=new URLSearchParams(location.search);
  const ui={filter:'all',query:'',sort:'recent',view:'list',selected:'minji',tab:'overview',reviewFilter:'pending',reviewSelected:null,focal:params.get('focal')||'self',relation:'all',graphSelected:'minji',edgeSelected:null,zoom:1,panX:0,panY:0};
  let toastTimer, returnFocus, sourceControlIndex=0;
  const escapeHTML=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const e=escapeHTML;
  const person=id=>id==='self'?{id:'self',name:'나',aliases:['내 기준 인물'],org:'내 관계 공간',role:'관계의 중심',policy:'cautious_use',note:'나를 중심으로 저장된 사람과 직접 연결된 관계를 확인해요.',facts:[],contexts:[],shade:90,relation:'knows',referenced:'오늘'}:state.people.find(p=>p.id===id);
  const currentPerson=()=>person(params.get('person'))||person('minji')||state.people[0];
  const unresolved=r=>['pending','needs_clarification'].includes(r.status);
  const reviewCount=()=>state.reviews.filter(unresolved).length;
  const rel=value=>seed.relations[value]||'아는 사이';
  const personRelations=p=>[...new Set(state.edges.filter(edge=>(edge.a==='self'&&edge.b===p.id)||(edge.b==='self'&&edge.a===p.id)).map(edge=>edge.type))];
  const relationText=p=>(personRelations(p).length?personRelations(p):[p.relation]).map(rel).join(' · ');
  const policy=value=>seed.policies[value]||seed.policies.cautious_use;
  const shortDate=date=>{const parts=String(date).split('-');return parts.length===3?`${Number(parts[1])}월 ${Number(parts[2])}일`:date;};
  const paths={people:'people.html',person:'person.html',graph:'graph.html',reviews:'reviews.html'};
  const personUrl=id=>`person.html?person=${encodeURIComponent(id)}`;
  const icons={
    people:'<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M22 21v-2a4 4 0 0 0-3-3.87"/><circle cx="9" cy="7" r="4"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    graph:'<circle cx="5" cy="6" r="3"/><circle cx="19" cy="5" r="3"/><circle cx="12" cy="19" r="3"/><path d="m8 6 8-1M6.5 9l4 7m7-8-4 8"/>',
    review:'<rect x="4" y="3" width="16" height="18" rx="3"/><path d="m8 12 3 3 5-6M9 3v2h6V3"/>',
    plus:'<path d="M12 5v14M5 12h14"/>',search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
    arrow:'<path d="M5 12h14m-5-5 5 5-5 5"/>',chevron:'<path d="m9 5 7 7-7 7"/>',down:'<path d="m6 9 6 6 6-6"/>',
    grid:'<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    list:'<path d="M9 6h12M9 12h12M9 18h12M3 6h1M3 12h1M3 18h1"/>',
    source:'<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M8 13h8M8 17h5"/>',
    lock:'<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3"/>',
    shield:'<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6z"/><path d="m8 12 3 3 5-5"/>',
    check:'<path d="m5 12 4 4L19 6"/>',close:'<path d="m6 6 12 12M6 18 18 6"/>',
    edit:'<path d="m15 4 5 5M4 20l5-1L20 8a2 2 0 0 0-5-5L4 14z"/>',
    info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7h.01"/>',
    reset:'<path d="M3 10a9 9 0 1 1 2 8M3 4v6h6"/>',minus:'<path d="M5 12h14"/>',
    fit:'<path d="M9 3H3v6m12-6h6v6M3 15v6h6m12-6v6h-6"/>',
    archive:'<rect x="3" y="3" width="18" height="5" rx="1"/><path d="M5 8v13h14V8M9 12h6"/>',
    clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    home:'<path d="m3 10 9-7 9 7v11h-7v-7h-4v7H3z"/>',
    layers:'<path d="m12 3 10 5-10 5L2 8zM2 12l10 5 10-5M2 16l10 5 10-5"/>',
    external:'<path d="M14 3h7v7m0-7L10 14M10 3H4a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h16a1 1 0 0 0 1-1v-6"/>'
  };
  const icon=(name,cls='')=>`<svg class="icon ${cls}" viewBox="0 0 24 24" aria-hidden="true">${icons[name]||icons.info}</svg>`;
  const avatar=(p,size='')=>`<span class="avatar ${size}" style="--avatar-bg:oklch(${Number(p.shade)||93}% .01 250)" aria-hidden="true">${e(p.id==='self'?'나':p.name.slice(-2))}</span>`;
  const badge=(text,kind='')=>`<span class="pill ${kind}">${kind?'<i class="dot"></i>':''}${e(text)}</span>`;
  const sourceButton=(id,label='출처 보기')=>`<button class="text-link" data-action="source" data-id="${e(id)}" data-od-id="source-${e(id)}-${++sourceControlIndex}">${icon('source')}${e(label)}</button>`;
  const relationEdges=id=>state.edges.filter(edge=>edge.a===id||edge.b===id);
  function save(){try{localStorage.setItem(storageKey,JSON.stringify(state));}catch{storageAvailable=false;}}
  function shell(){
    const active=page==='person'?'people':page;
    const names={people:'사람',person:'사람',graph:'관계 그래프',reviews:'리뷰'};
    document.getElementById('app').innerHTML=`
    <aside class="sidebar" data-od-id="sidebar">
      <a class="brand" href="people.html" aria-label="Kinlayer 사람 화면" data-od-id="brand"><svg class="brand-mark" viewBox="0 0 32 32" aria-hidden="true"><path d="M7 6v20M7 16 24 6M7 16l17 10" fill="none" stroke="currentColor" stroke-width="2.4"/><circle cx="7" cy="6" r="3.2" fill="currentColor"/><circle cx="7" cy="26" r="3.2" fill="currentColor"/><circle cx="24" cy="6" r="3.2" fill="currentColor"/><circle cx="24" cy="26" r="3.2" fill="currentColor"/></svg>Kinlayer</a>
      <div class="workspace-name">${icon('lock')}개인 워크스페이스</div>
      <div class="nav-label">나의 관계 공간</div>
      <nav class="navigation" aria-label="주요 탐색" data-od-id="primary-navigation">${[['people','사람','people'],['graph','관계 그래프','graph'],['reviews','리뷰','review']].map(([key,label,symbol])=>`<a href="${paths[key]}" class="nav-item ${active===key?'active':''}" ${active===key?'aria-current="page"':''} data-od-id="nav-${key}">${icon(symbol)}<span>${label}</span>${key==='people'?`<span class="badge-number" data-people-count>${state.people.length}</span>`:key==='reviews'?`<span class="badge-number" data-review-count>${reviewCount()}</span>`:''}</a>`).join('')}</nav>
      <div class="sidebar-bottom"><div class="sidebar-note">${icon('layers')}기억은 쌓이고,<br>맥락은 더 선명해져요.</div><button class="nav-item" data-action="about" data-od-id="about-prototype">${icon('info')}목업 안내</button><div class="local-profile"><div class="self-icon">나</div><div><strong>나의 Kinlayer</strong><span>로컬 데모 공간</span></div></div></div>
    </aside>
    <div class="app-frame"><header class="topbar" data-od-id="topbar"><div class="breadcrumbs"><a href="people.html">${icon('home')}내 관계 공간</a>${icon('chevron')}<a class="${page!=='person'?'current':''}" href="${paths[active]}">${names[page]}</a>${page==='person'?`${icon('chevron')}<span class="current" id="breadcrumb-person">${e(currentPerson().name)}</span>`:''}</div><button class="demo-label" data-action="about" aria-label="가상 데이터 목업 안내" data-od-id="demo-disclosure">${badge('목업')}<span>가상 데이터로 둘러보는 중</span></button></header><main class="main" id="main" data-od-id="${page}-screen"></main></div>
    <dialog class="modal" id="modal" aria-labelledby="modal-title" data-od-id="dialog"></dialog><div class="toast" id="toast" role="status" aria-live="polite" hidden></div>`;
    renderPage();
  }
  const footer=()=>`<footer class="page-footer" data-od-id="page-footer"><span class="row">${icon('lock')}가상 인물과 기록을 사용한 인터랙티브 목업</span><span>사람을 기억하고, 맥락을 연결하는 공간</span></footer>`;
  function renderPage(){
    const focused=document.activeElement,focusId=focused?.dataset.odId;sourceControlIndex=0;
    const main=document.getElementById('main');
    if(page==='people')renderPeople(main);
    else if(page==='person')renderPerson(main);
    else if(page==='graph')renderGraph(main);
    else renderReviews(main);
    document.querySelectorAll('[data-review-count]').forEach(el=>el.textContent=reviewCount());
    document.querySelectorAll('[data-people-count]').forEach(el=>el.textContent=state.people.length);
    if(focusId&&focusId!=='accept-review'){const replacement=[...document.querySelectorAll('[data-od-id]')].find(el=>el.dataset.odId===focusId);replacement?.focus({preventScroll:true});}
  }
  function tabs(items,current,action){return items.map(([value,label,count])=>`<button class="filter-tab ${current===value?'active':''}" data-action="${action}" data-value="${value}" aria-pressed="${current===value}" data-od-id="${action}-${value}">${e(label)}${count!==undefined?`<span>${count}</span>`:''}</button>`).join('');}
  function filteredPeople(){
    const query=ui.query.trim().toLocaleLowerCase('ko');
    return state.people.filter(p=>(ui.filter==='all'||personRelations(p).includes(ui.filter))&&(!query||[p.name,...p.aliases].join(' ').toLocaleLowerCase('ko').includes(query))).sort(ui.sort==='name'?(a,b)=>a.name.localeCompare(b.name,'ko'):(a,b)=>b.date.localeCompare(a.date));
  }
  function renderPeople(main){
    const p=person(ui.selected)||state.people[0];
    main.innerHTML=`<div class="page-heading"><div><div class="title-with-count"><h1 data-od-id="people-title">사람</h1><span id="total-people">${state.people.length}</span></div><p>소중한 사람들, 그리고 함께 쌓아온 맥락.</p></div><button class="button primary" data-action="new-person" data-od-id="add-person">${icon('plus')}사람 추가</button></div>
    <div class="people-layout"><section class="people-primary" data-od-id="people-directory"><div class="filter-tabs" aria-label="관계별 사람 필터">${tabs([['all','모든 사람',state.people.length],['coworker','동료',state.people.filter(p=>personRelations(p).includes('coworker')).length],['friend','친구',state.people.filter(p=>personRelations(p).includes('friend')).length],['family','가족',state.people.filter(p=>personRelations(p).includes('family')).length]],ui.filter,'people-filter')}</div>
    <div class="list-toolbar"><label class="search-field">${icon('search')}<input id="people-search" type="search" placeholder="이름이나 별칭으로 검색" value="${e(ui.query)}" aria-label="이름이나 별칭으로 사람 검색" data-od-id="people-search" autocomplete="off"><kbd aria-hidden="true">/</kbd></label><div class="toolbar-end"><select class="select" id="people-sort" aria-label="사람 정렬" data-od-id="people-sort"><option value="recent" ${ui.sort==='recent'?'selected':''}>최근 참조순</option><option value="name" ${ui.sort==='name'?'selected':''}>이름순</option></select><div class="view-toggle" aria-label="목록 보기 방식"><button class="icon-button ${ui.view==='list'?'active':''}" data-action="view" data-value="list" aria-label="목록 보기" aria-pressed="${ui.view==='list'}" data-od-id="list-view">${icon('list')}</button><button class="icon-button ${ui.view==='cards'?'active':''}" data-action="view" data-value="cards" aria-label="카드 보기" aria-pressed="${ui.view==='cards'}" data-od-id="card-view">${icon('grid')}</button></div></div></div><div id="people-results" aria-live="polite"></div></section>
    <aside class="people-rail" data-od-id="person-preview"><div id="preview">${preview(p)}</div><p class="rail-footnote">${icon('info')}인물을 선택하면 저장된 맥락을<br>빠르게 확인할 수 있어요.</p></aside></div>${footer()}`;
    renderPeopleResults();
  }
  function renderPeopleResults(){
    const matches=filteredPeople(),target=document.getElementById('people-results');
    target.innerHTML=`<div class="people-table ${ui.view==='cards'?'cards':''}" role="list" aria-label="등록된 사람"><div class="table-head" aria-hidden="true"><span>이름 · 별칭</span><span>나와의 관계</span><span>소속 · 역할</span><span>최근 참조</span><span></span></div>${matches.length?matches.map(p=>`<article class="person-row ${ui.selected===p.id?'selected':''}" role="listitem" tabindex="0" data-action="select-person" data-id="${e(p.id)}" aria-label="${e(p.name)} 요약 보기" data-od-id="person-card-${e(p.id)}"><div class="person-identity">${avatar(p)}<div><a href="${personUrl(p.id)}" class="person-name" data-od-id="open-${e(p.id)}">${e(p.name)}</a><div class="person-alias">${e(p.aliases.join(' · ')||'등록된 별칭 없음')}</div></div></div><div class="relation-tags">${(personRelations(p).length?personRelations(p):[p.relation]).map(type=>`<span class="relation-label">${e(rel(type))}</span>`).join('')}</div><div class="person-org">${e(p.org)}<small>${e(p.role)}</small></div><span class="referenced">${e(p.referenced)}</span><a class="row-open" href="${personUrl(p.id)}" aria-label="${e(p.name)} 상세 보기">${icon('chevron')}</a></article>`).join(''):`<div class="empty-state">${icon('search')}<h3>일치하는 사람이 없어요</h3><p>다른 이름이나 별칭으로 검색해 보세요.</p><button class="text-link" data-action="clear-search">검색과 필터 초기화</button></div>`}</div><div class="table-footer"><span>${state.people.length}명 중 ${matches.length}명 표시</span><span>${icon('clock')}최근 참조는 AI가 이 인물을 참고한 시점이에요</span></div>`;
  }
  function preview(p,graph=false){
    const edge=ui.edgeSelected?state.edges.find(x=>x.id===ui.edgeSelected):null;
    return `<section class="panel preview-panel" data-od-id="selected-person-panel"><div class="panel-kicker"><span>${graph?(edge?'선택한 관계':'선택한 인물'):'인물 미리보기'}</span>${icon(graph?'graph':'people')}</div><div class="preview-body">${avatar(p,'large')}<div class="preview-name"><h2 data-od-id="preview-name">${e(p.name)}</h2>${p.id!=='self'?badge('확인됨','success'):badge('기준 인물')}</div><p class="preview-subtitle">${e(p.id==='self'?'내 관계의 중심':`${relationText(p)} · ${p.org}`)}</p><div class="inline-info">${badge(policy(p.policy).label)}</div>
    ${edge?`<dl class="mini-facts"><div><dt>연결된 인물</dt><dd>${e(person(edge.a).name)} ↔ ${e(person(edge.b).name)}</dd></div><div><dt>관계</dt><dd>${e(rel(edge.type))}</dd></div><div><dt>상태</dt><dd>활성 · 사용자 발언 근거</dd></div></dl><div class="preview-section"><span class="eyebrow">관계의 근거</span><p>${e(state.sources[edge.source]?.excerpt||'직접 등록한 관계예요.')}</p>${sourceButton(edge.source)}</div>`:`<dl class="mini-facts"><div><dt>별칭</dt><dd>${e(p.aliases.join(', ')||'등록되지 않음')}</dd></div><div><dt>최근 참조</dt><dd>${e(p.referenced)}</dd></div></dl><div class="preview-section"><span class="eyebrow">기억하고 있는 맥락</span><p>${e(p.note||'아직 등록된 맥락이 없어요.')}</p><div class="source-caption">${icon('source')}${p.contexts.length}개의 맥락 · ${relationEdges(p.id).length}개의 관계</div></div>`}
    ${!graph?`<div class="preview-section"><span class="eyebrow">나와의 연결</span><div class="mini-network" aria-label="나와 ${e(p.name)}의 ${e(rel(p.relation))} 관계"><div class="mini-network-node">${avatar(person('self'))}나</div><div class="mini-edge">${e(rel(p.relation))}</div><div class="mini-network-node">${avatar(p)}${e(p.name)}</div></div></div>`:''}</div><div class="preview-actions" style="${graph?'padding:0 21px 21px':''}">${p.id!=='self'?`<a class="button ${graph?'primary':''}" href="${personUrl(p.id)}" data-od-id="preview-open-profile">프로필 보기${icon('arrow')}</a>`:''}${!graph?`<a class="button ghost" href="graph.html?focal=${e(p.id)}" data-od-id="preview-open-graph">관계 그래프로 보기${icon('external')}</a>`:''}</div></section>`;
  }
  function renderPerson(main){
    const p=currentPerson();document.title=`${p.name} · Kinlayer`;document.getElementById('breadcrumb-person').textContent=p.name;
    main.innerHTML=`<section class="person-hero" data-od-id="person-hero">${avatar(p,'large xlarge')}<div><div class="hero-name"><h1 data-od-id="person-name">${e(p.name)}</h1>${badge('확인된 인물','success')}</div><p class="hero-description">${e([relationText(p),p.org,p.role].filter(v=>!v.includes('미등록')).join(' · '))}</p><p class="small muted" style="margin-top:4px">${e(p.aliases.join(' · ')||'별칭 없음')}</p></div><div class="hero-actions"><a class="button ghost" href="graph.html?focal=${e(p.id)}" data-od-id="person-graph-link">${icon('graph')}관계 보기</a><button class="button primary" data-action="edit-person" data-id="${e(p.id)}" data-od-id="edit-profile">${icon('edit')}프로필 편집</button></div></section>
    <div class="filter-tabs" aria-label="인물 상세 보기">${tabs([['overview','개요'],['profile','프로필'],['relations','관계',relationEdges(p.id).length],['sources','출처',personSources(p).length]],ui.tab,'person-tab')}</div><div class="detail-layout"><div class="stack" id="person-tab-content" data-od-id="person-detail-content">${personContent(p)}</div><aside class="stack detail-rail" data-od-id="person-context-rail"><section class="panel policy-card" data-od-id="ai-policy"><div class="row between"><h2>AI 사용 범위</h2><button class="text-link" data-action="policy" data-id="${e(p.id)}" data-od-id="change-ai-policy">변경</button></div><div class="policy-value">${icon('shield')}${e(policy(p.policy).label)}</div><p>${e(policy(p.policy).description)}</p><div class="policy-note">개별 기억에 설정된 사용 범위도 함께 적용돼요.</div></section><section class="panel content-panel" data-od-id="person-relationships"><div class="section-heading"><h2>연결된 관계</h2><span class="small muted">${relationEdges(p.id).length}</span></div>${relationshipList(p)}<a class="text-link" href="graph.html?focal=${e(p.id)}">그래프에서 살펴보기${icon('arrow')}</a></section><div class="rail-footnote">${icon('clock')}최근 참조 ${e(p.referenced)}<br>정보가 달라졌다면 언제든 수정하세요.</div></aside></div>${footer()}`;
  }
  function personSources(p){return [...new Set([...p.facts.map(f=>f.source),...p.contexts.map(c=>c.source),...relationEdges(p.id).map(edge=>edge.source)])].filter(id=>state.sources[id]);}
  function factsPanel(p){return `<section class="panel content-panel" data-od-id="profile-facts"><div class="section-heading"><h2>기본 정보</h2><button class="text-link" data-action="edit-person" data-id="${e(p.id)}">편집</button></div><dl class="fact-grid"><div class="fact"><dt>이름</dt><dd>${e(p.name)}</dd></div><div class="fact"><dt>별칭</dt><dd>${e(p.aliases.join(', ')||'등록되지 않음')}</dd></div>${['organization','role'].map(type=>{const f=p.facts.find(x=>x.type===type);return `<div class="fact"><dt>${type==='organization'?'소속':'역할'}</dt><dd>${e(f?.value||'등록되지 않음')}${f?`<div class="context-meta">사용자 발언${sourceButton(f.source,'근거')}</div>`:''}</dd></div>`;}).join('')}</dl></section>`;}
  function personContent(p){
    if(ui.tab==='profile')return `${factsPanel(p)}<section class="panel content-panel"><div class="section-heading"><h2>인물 메모</h2><button class="text-link" data-action="edit-person" data-id="${e(p.id)}">편집</button></div><p style="font-size:14px;line-height:1.9">${e(p.note||'아직 등록된 메모가 없어요.')}</p></section>`;
    if(ui.tab==='relations')return `<section class="panel content-panel" data-od-id="relationships-content"><div class="section-heading"><h2>직접 연결된 관계</h2><a class="text-link" href="graph.html?focal=${e(p.id)}">그래프 보기${icon('arrow')}</a></div>${relationshipList(p,true)}</section>`;
    if(ui.tab==='sources')return `<section class="panel content-panel" data-od-id="sources-content"><div class="section-heading"><h2>기억의 출처</h2><span class="small muted">필요한 발췌만 보관해요</span></div><div class="stack">${personSources(p).map(id=>evidence(id)).join('')||'<p class="muted">아직 연결된 출처가 없어요.</p>'}</div></section>`;
    const communications=p.contexts.filter(c=>c.type==='communication_preference');
    const recent=p.contexts.filter(c=>c.type!=='communication_preference').slice().sort((a,b)=>b.date.localeCompare(a.date));
    return `${factsPanel(p)}<section class="panel content-panel" data-od-id="communication-context"><div class="section-heading"><h2>소통할 때 기억할 것</h2><span class="small muted">소통 맥락</span></div>${communications.length?communications.map(c=>contextItem(p,c)).join(''):'<p class="muted small">아직 기록된 소통 선호가 없어요.</p>'}</section><section class="panel content-panel" data-od-id="recent-context"><div class="section-heading"><h2>최근 맥락</h2><span class="small muted">대화에서 남긴 기억</span></div>${recent.length?recent.map(c=>`<article class="timeline-item" data-od-id="context-${e(c.id)}"><div class="timeline-date">${Number(c.date.split('-')[1])}월<strong>${Number(c.date.split('-')[2])}</strong></div><div class="timeline-content"><h3>${e(c.title)}</h3><p>${e(c.text)}</p><div class="context-meta">${e(policy(c.policy).label)}${sourceButton(c.source)}<button class="text-link context-edit" data-action="edit-context" data-person="${e(p.id)}" data-id="${e(c.id)}">수정</button></div></div></article>`).join(''):'<p class="muted small">아직 기록된 최근 맥락이 없어요.</p>'}</section>`;
  }
  function contextItem(p,c){return `<article class="context-item" data-od-id="context-${e(c.id)}"><div class="context-heading"><h3>${e(c.title)}</h3></div><p>${e(c.text)}</p><div class="context-meta"><span>${e(policy(c.policy).label)}</span><span>·</span><span>${shortDate(c.date)}</span>${sourceButton(c.source)}<button class="text-link context-edit" data-action="edit-context" data-person="${e(p.id)}" data-id="${e(c.id)}">수정</button></div></article>`;}
  function relationshipList(p,full=false){return relationEdges(p.id).map(edge=>{const other=person(edge.a===p.id?edge.b:edge.a);return `<div class="relationship-item" data-od-id="relationship-${e(edge.id)}">${avatar(other)}<div>${other.id==='self'?'<span class="person-name">나</span>':`<a href="${personUrl(other.id)}" class="person-name">${e(other.name)}</a>`}${full?`<div class="small muted">${sourceButton(edge.source)}</div>`:''}</div><span class="relation-label">${e(rel(edge.type))}</span></div>`;}).join('')||'<p class="small muted">아직 연결된 관계가 없어요.</p>';}
  function evidence(id){const s=state.sources[id];return s?`<article class="evidence-card" data-od-id="evidence-${e(id)}"><div class="row between"><div class="row small medium">${icon('source')}${e(s.title)}</div>${badge(s.actor)}</div><blockquote>“${e(s.excerpt)}”</blockquote><div class="evidence-meta">${e(s.date)} · ${s.actor==='목업에서 직접 수정'?'브라우저 내 수정 기록':'가상 대화 발췌'} · 원문 전체는 보관하지 않아요</div></article>`:'<p class="small muted">연결된 출처가 없어요.</p>';}
  function graphData(){
    const edges=relationEdges(ui.focal).filter(edge=>ui.relation==='all'||edge.type===ui.relation);
    return {edges,nodes:[...new Set([ui.focal,...edges.flatMap(edge=>[edge.a,edge.b])])]};
  }
  function renderGraph(main){
    if(!person(ui.focal))ui.focal='self';
    const data=graphData();if(!data.nodes.includes(ui.graphSelected))ui.graphSelected=ui.focal;
    if(ui.edgeSelected&&!data.edges.some(edge=>edge.id===ui.edgeSelected))ui.edgeSelected=null;
    main.innerHTML=`<div class="page-heading"><div><h1 data-od-id="graph-title">관계 그래프</h1><p>한 사람을 중심으로, 연결된 관계와 그 맥락을 살펴보세요.</p></div><a href="people.html" class="button ghost" data-od-id="graph-to-people">${icon('list')}목록으로 보기</a></div><div class="graph-toolbar" data-od-id="graph-filters"><label class="field-inline">중심 인물<select class="select" id="graph-focal" data-od-id="focal-person"><option value="self" ${ui.focal==='self'?'selected':''}>나</option>${state.people.map(p=>`<option value="${e(p.id)}" ${ui.focal===p.id?'selected':''}>${e(p.name)}</option>`).join('')}</select></label><label class="field-inline">관계 유형<select class="select" id="graph-relation" data-od-id="relationship-filter"><option value="all">모든 관계</option>${Object.entries(seed.relations).map(([v,l])=>`<option value="${v}" ${ui.relation===v?'selected':''}>${l}</option>`).join('')}</select></label><button class="button ghost" data-action="reset-graph" data-od-id="reset-graph">${icon('reset')}보기 초기화</button></div>
    <div class="graph-layout"><section data-od-id="graph-canvas-region"><div class="graph-board"><div class="graph-caption"><h2>${e(ui.focal==='self'?'나':person(ui.focal).name)}의 관계</h2><p>직접 연결된 ${data.nodes.length-1}명 · 1단계 관계</p></div><svg class="graph-svg" id="graph-svg" viewBox="0 0 820 600" aria-label="${e(person(ui.focal).name)}를 중심으로 한 직접 관계 그래프"><g id="graph-scene">${graphSVG(data)}</g></svg><div class="graph-controls" data-od-id="graph-zoom"><button class="icon-button" data-action="zoom" data-value="out" aria-label="그래프 축소">${icon('minus')}</button><span id="zoom-level" aria-live="polite">${Math.round(ui.zoom*100)}%</span><button class="icon-button" data-action="zoom" data-value="in" aria-label="그래프 확대">${icon('plus')}</button><button class="icon-button" data-action="fit-graph" aria-label="그래프 전체 맞춤">${icon('fit')}</button></div><span class="graph-hint">인물이나 연결선을 선택해 보세요</span></div><div class="graph-mobile-list" aria-label="연결된 인물 목록">${data.nodes.filter(id=>id!==ui.focal).map(id=>`<button data-action="graph-node" data-id="${e(id)}">${avatar(person(id))}${e(person(id).name)}</button>`).join('')}</div></section><aside class="graph-rail" id="graph-inspector" data-od-id="graph-inspector">${preview(person(ui.graphSelected),true)}</aside></div>${footer()}`;
    transformGraph();bindGraphDrag();
  }
  function graphSVG(data){
    const positions={[ui.focal]:[410,288]}, neighbors=data.nodes.filter(id=>id!==ui.focal);
    const presets=[[238,136],[553,126],[658,263],[577,426],[398,456],[217,425],[148,266],[376,103]];
    neighbors.forEach((id,i)=>{positions[id]=neighbors.length>8?[410+310*Math.cos(-Math.PI/2+i*2*Math.PI/neighbors.length),290+205*Math.sin(-Math.PI/2+i*2*Math.PI/neighbors.length)]:neighbors.length>5?presets[i]:[410+224*Math.cos(-Math.PI/2+i*2*Math.PI/neighbors.length),285+177*Math.sin(-Math.PI/2+i*2*Math.PI/neighbors.length)];});
    return `${data.edges.map(edge=>{const a=positions[edge.a],b=positions[edge.b],parallel=data.edges.filter(item=>(item.a===edge.a&&item.b===edge.b)||(item.a===edge.b&&item.b===edge.a)),order=parallel.indexOf(edge),offset=(order-(parallel.length-1)/2)*100,dx=b[0]-a[0],dy=b[1]-a[1],len=Math.hypot(dx,dy)||1,control=[(a[0]+b[0])/2-dy/len*offset,(a[1]+b[1])/2+dx/len*offset],mid=[a[0]*.25+control[0]*.5+b[0]*.25,a[1]*.25+control[1]*.5+b[1]*.25],path=`M${a[0]},${a[1]}Q${control[0]},${control[1]} ${b[0]},${b[1]}`;return `<g class="edge-group" tabindex="0" role="button" aria-label="${e(person(edge.a).name)}와 ${e(person(edge.b).name)}의 ${e(rel(edge.type))} 관계" data-action="graph-edge" data-id="${e(edge.id)}" data-od-id="graph-${e(edge.id)}"><path class="graph-edge" d="${path}"/><path class="edge-hit" d="${path}"/><rect x="${mid[0]-29}" y="${mid[1]-10}" width="58" height="20" rx="4" fill="var(--surface)"/><text class="edge-label" x="${mid[0]}" y="${mid[1]+4}" text-anchor="middle">${e(rel(edge.type))}</text></g>`;}).join('')}${data.nodes.map(id=>{const p=person(id),pos=positions[id],focal=id===ui.focal;return `<g class="graph-node ${id===ui.graphSelected?'selected':''} ${focal?'self':''}" transform="translate(${pos[0]},${pos[1]})" tabindex="0" role="button" aria-label="${e(p.name)} 인물 선택" aria-pressed="${id===ui.graphSelected}" data-action="graph-node" data-id="${e(id)}" data-od-id="graph-node-${e(id)}"><circle class="node-circle" r="${focal?38:29}"/><text class="node-letter" text-anchor="middle" y="6">${e(id==='self'?'나':p.name.slice(-2))}</text><text class="node-name" text-anchor="middle" y="${focal?61:51}">${e(p.name)}</text><text class="node-sub" text-anchor="middle" y="${focal?79:67}">${focal?'관계의 중심':e(p.role.includes('미등록')?rel(p.relation):p.role)}</text></g>`;}).join('')}`;
  }
  function transformGraph(){document.getElementById('graph-scene')?.setAttribute('transform',`translate(${410+ui.panX} ${300+ui.panY}) scale(${ui.zoom}) translate(-410 -300)`);const z=document.getElementById('zoom-level');if(z)z.textContent=`${Math.round(ui.zoom*100)}%`;}
  function bindGraphDrag(){
    const svg=document.getElementById('graph-svg');let start=null;
    svg.addEventListener('pointerdown',event=>{if(event.target.closest('[data-action]'))return;start={x:event.clientX,y:event.clientY,panX:ui.panX,panY:ui.panY};svg.setPointerCapture?.(event.pointerId);svg.classList.add('dragging');});
    svg.addEventListener('pointermove',event=>{if(!start)return;const bounds=svg.getBoundingClientRect(),scale=820/bounds.width;ui.panX=start.panX+(event.clientX-start.x)*scale;ui.panY=start.panY+(event.clientY-start.y)*scale;transformGraph();});
    ['pointerup','pointercancel','lostpointercapture'].forEach(type=>svg.addEventListener(type,()=>{start=null;svg.classList.remove('dragging');}));
  }
  function renderReviews(main){
    const filtered=state.reviews.filter(r=>ui.reviewFilter==='pending'?unresolved(r):!unresolved(r));
    if(!filtered.some(r=>r.id===ui.reviewSelected))ui.reviewSelected=filtered[0]?.id||null;
    const r=filtered.find(r=>r.id===ui.reviewSelected);
    main.innerHTML=`<div class="page-heading"><div><div class="title-with-count"><h1 data-od-id="reviews-title">리뷰</h1><span>${reviewCount()}</span></div><p>쌓인 기억 중 확인이 필요한 맥락만 모았어요.</p></div><span class="pill">내가 결정하는 기억</span></div><div class="filter-tabs review-tabs" aria-label="리뷰 상태 필터">${tabs([['pending','확인 필요',reviewCount()],['processed','처리됨',state.reviews.length-reviewCount()]],ui.reviewFilter,'review-filter')}</div>
    ${r?`<div class="review-layout"><aside data-od-id="review-inbox"><div class="review-list">${filtered.map(item=>{const p=person(item.person);return `<button class="review-list-item ${r.id===item.id?'active':''}" data-action="select-review" data-id="${item.id}" aria-pressed="${r.id===item.id}" data-od-id="review-card-${item.id}"><div class="row">${avatar(p)}<span class="person-name">${e(p.name)}</span></div><h3>${e(p.name)} · ${e(item.label)}</h3><p>${e(item.summary)}</p><div class="review-meta"><span>${item.status==='needs_clarification'?'추가 확인 중':e(item.label)}</span><span>${shortDate(item.date)}</span></div></button>`;}).join('')}</div><p class="review-help">${icon('info')}모든 기억을 승인할 필요는 없어요.<br>확인이 필요한 항목만 살펴보세요.</p></aside><section class="panel review-detail" data-od-id="review-detail">${reviewDetail(r)}</section></div>`:`<section class="panel empty-state" data-od-id="review-empty">${icon('check')}<h3>${ui.reviewFilter==='pending'?'확인이 필요한 기억을 모두 살펴봤어요':'아직 처리한 항목이 없어요'}</h3><p>${ui.reviewFilter==='pending'?'반영한 정보는 인물 프로필에서 다시 확인할 수 있어요.':'확인 필요 탭에서 맥락과 출처를 살펴보세요.'}</p><a href="people.html" class="text-link">사람 목록으로${icon('arrow')}</a></section>`}${footer()}`;
  }
  const statusLabel=status=>({accepted:'반영 완료',edited_accepted:'수정 후 반영',rejected:'거절됨',archived:'보관됨',needs_clarification:'추가 확인 중',pending:'확인 필요'}[status]||status);
  function reviewDetail(r){
    const pending=unresolved(r),p=person(r.person);
    return `<div class="row between">${badge(statusLabel(r.status),pending?'warning':['accepted','edited_accepted'].includes(r.status)?'success':'')}<a class="text-link" href="${personUrl(p.id)}">${e(p.name)} 프로필${icon('external')}</a></div><h2>${e(r.title)}</h2><p class="review-description">${e(r.reason)}</p><div class="compare-grid"><div class="compare-card"><span class="eyebrow">기존에 저장된 정보</span><strong>${e(r.before)}</strong></div>${icon('arrow','compare-arrow')}<div class="compare-card proposed"><span class="eyebrow">${r.type==='edge'?'추가할 관계':'확인이 필요한 정보'}</span><strong>${e(r.after)}</strong></div></div><h3 class="review-section-title">이 기억은 어디에서 왔나요?</h3>${evidence(r.source)}<div class="review-policy">${icon('shield')}<div><h3>${e(policy(r.policy).label)}</h3><p>${e(policy(r.policy).description)}</p></div></div>
    ${pending?`${r.status==='needs_clarification'?'<div class="processed-banner warning">추가 확인이 필요한 상태로 남겨두었어요. 내용을 확인한 후 다시 반영할 수 있어요.</div>':''}<div class="review-actions"><button class="button primary" data-action="review-accept" data-id="${r.id}" data-od-id="accept-review">${icon('check')}${r.type==='profile_field'?'현재 정보로 반영':'확인하고 반영'}</button><button class="button" data-action="review-edit" data-id="${r.id}" data-od-id="edit-accept-review">수정 후 반영</button><span class="spacer"></span><button class="button ghost" data-action="review-archive" data-id="${r.id}" data-od-id="archive-review">${icon('archive')}보관</button></div><div class="review-more"><button class="text-link" data-action="review-clarify" data-id="${r.id}" ${r.status==='needs_clarification'?'disabled':''}>추가 확인이 필요해요</button><button class="text-link" data-action="review-reject" data-id="${r.id}">이 제안 거절하기</button></div>`:`<div class="processed-banner ${['accepted','edited_accepted'].includes(r.status)?'':'neutral'}">${e(statusLabel(r.status))} · ${e(r.processedDate||'오늘')}<p style="font-size:11px;margin-top:4px">${['accepted','edited_accepted'].includes(r.status)?'변경된 맥락을 인물 프로필에 반영했어요.':'기존 인물 정보는 유지했어요.'}</p></div>`}`;
  }
  function openModal(title,body,footerContent=''){
    const modal=document.getElementById('modal');returnFocus=document.activeElement;
    modal.innerHTML=`<div class="modal-header"><h2 id="modal-title">${e(title)}</h2><button class="icon-button" data-action="close-modal" aria-label="창 닫기">${icon('close')}</button></div>${body}${footerContent?`<div class="modal-footer">${footerContent}</div>`:''}`;
    if(!modal.open)modal.showModal();
    const focusTarget=modal.querySelector('input:not([type=radio]),textarea,select');if(focusTarget)setTimeout(()=>focusTarget.focus(),0);
  }
  function closeModal(){const modal=document.getElementById('modal');if(modal.open)modal.close();}
  function notify(message){const toast=document.getElementById('toast');toast.innerHTML=`${icon('check')}<span>${e(message)}</span>`;toast.hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>toast.hidden=true,4500);}
  function openPersonForm(id){
    const p=person(id),isNew=!p;
    openModal(isNew?'새로운 사람 추가':'프로필 편집',`<form id="person-form" data-person="${e(id||'')}" novalidate><div class="modal-body"><p class="modal-intro">${isNew?'기억하고 싶은 사람과 기본 맥락을 남겨보세요.':'달라진 정보는 바로 수정할 수 있어요.'} 변경은 이 목업에만 저장돼요.</p><p class="form-error" id="form-error" role="alert" hidden></p><div class="field-grid"><div class="field"><label for="person-name-input">이름 <span aria-hidden="true">*</span></label><input id="person-name-input" name="name" value="${e(p?.name||'')}" required maxlength="60" autocomplete="off"></div><div class="field"><label for="person-alias-input">별칭</label><input id="person-alias-input" name="aliases" value="${e(p?.aliases.join(', ')||'')}" maxlength="160"><small>여러 별칭은 쉼표로 구분해 주세요.</small></div></div><div class="field-grid"><div class="field"><label for="person-org-input">소속</label><input id="person-org-input" name="org" value="${e(p?.org==='소속 미등록'?'':p?.org||'')}" maxlength="100"></div><div class="field"><label for="person-role-input">역할</label><input id="person-role-input" name="role" value="${e(p?.role==='역할 미등록'?'':p?.role||'')}" maxlength="100"></div></div>${isNew?`<div class="field"><label for="new-relation">나와의 관계</label><select name="relation" id="new-relation">${Object.entries(seed.relations).map(([v,l])=>`<option value="${v}" ${v==='knows'?'selected':''}>${l}</option>`).join('')}</select></div>`:''}<div class="field"><label for="person-note-input">인물 메모</label><textarea id="person-note-input" name="note" maxlength="500">${e(p?.note||'')}</textarea></div></div><div class="modal-footer"><button type="button" class="button ghost" data-action="close-modal">취소</button><button type="submit" class="button primary" data-od-id="save-person">${isNew?'사람 추가':'변경사항 저장'}</button></div></form>`);
  }
  function openPolicyForm(id){const p=person(id);openModal('AI 사용 범위',`<form id="policy-form" data-person="${e(id)}"><div class="modal-body"><p class="modal-intro">${e(p.name)}에 대한 기억을 AI가 어떻게 활용할지 정해 주세요.</p>${Object.entries(seed.policies).map(([v,value])=>`<label class="policy-option"><input type="radio" name="policy" value="${v}" ${p.policy===v?'checked':''}><span><strong>${value.label}</strong><small>${value.description}</small></span></label>`).join('')}</div><div class="modal-footer"><button type="button" class="button ghost" data-action="close-modal">취소</button><button class="button primary" type="submit" data-od-id="save-policy">사용 범위 저장</button></div></form>`);}
  function openContextForm(personId,contextId){const p=person(personId),c=p.contexts.find(item=>item.id===contextId);if(!c)return;openModal('기억 수정',`<form id="context-form" data-person="${e(personId)}" data-context="${e(contextId)}" novalidate><div class="modal-body"><p class="modal-intro">${e(p.name)}의 맥락을 바로잡아요. 기존 출처는 수정 기록에 함께 남겨요.</p><p class="form-error" id="form-error" role="alert" hidden></p><div class="field"><label for="context-title">제목</label><input id="context-title" name="title" value="${e(c.title)}" maxlength="100" required></div><div class="field"><label for="context-text">기억하고 있는 맥락</label><textarea id="context-text" name="text" maxlength="800" required>${e(c.text)}</textarea></div><div class="field"><label for="context-policy">AI 사용 범위</label><select id="context-policy" name="policy">${Object.entries(seed.policies).map(([v,item])=>`<option value="${v}" ${c.policy===v?'selected':''}>${item.label}</option>`).join('')}</select></div></div><div class="modal-footer"><button type="button" class="button ghost" data-action="close-modal">취소</button><button class="button primary" type="submit" data-od-id="save-context">수정사항 저장</button></div></form>`);}
  function openReviewEdit(id){const r=state.reviews.find(item=>item.id===id);if(!r||!unresolved(r))return;openModal('내용을 수정하고 반영',`<form id="review-form" data-review="${e(id)}" novalidate><div class="modal-body"><p class="modal-intro">${e(person(r.person).name)}의 ${e(r.label)} 내용을 수정해 주세요.</p><p class="form-error" id="form-error" role="alert" hidden></p><div class="field"><label for="review-value">반영할 내용</label>${r.type==='edge'?`<select id="review-value" name="value">${Object.entries(seed.relations).map(([v,label])=>`<option value="${v}" ${rel(v)===r.after?'selected':''}>${label}</option>`).join('')}</select>`:`<textarea id="review-value" name="value" required maxlength="400">${e(r.after)}</textarea>`}</div>${evidence(r.source)}</div><div class="modal-footer"><button type="button" class="button ghost" data-action="close-modal">취소</button><button class="button primary" type="submit" data-od-id="save-review-edit">수정하고 반영</button></div></form>`);}
  function applyReview(r,value,edited=false){
    if(!unresolved(r))return;
    const p=person(r.person);
    const normalized=r.type==='edge'&&seed.relations[value]?rel(value):value;
    r.source=manualSource(edited?'리뷰에서 직접 정정':'리뷰에서 직접 확인',`${p.name}의 ${r.label}: ${normalized}`,r.source);
    if(r.type==='profile_field'){
      p.org=value;let f=p.facts.find(item=>item.type===r.field);if(!f){f={type:r.field,label:'소속'};p.facts.push(f);}f.previous={value:f.value,source:f.source};f.value=value;f.source=r.source;
    }else if(r.type==='edge'){
      const type=Object.keys(seed.relations).includes(value)?value:Object.keys(seed.relations).find(key=>rel(key)===value)||'friend';
      if(!state.edges.some(edge=>((edge.a==='self'&&edge.b===p.id)||(edge.a===p.id&&edge.b==='self'))&&edge.type===type))state.edges.push({id:`accepted-${r.id}`,a:'self',b:p.id,type,source:r.source});value=rel(type);
    }else if(r.type==='observation'){p.contexts.push({id:`accepted-${r.id}`,type:'communication_preference',title:value,text:value,date:'2026-10-01',policy:r.policy,source:r.source});}
    r.after=value;r.status=edited?'edited_accepted':'accepted';r.processedDate=new Date().toLocaleDateString('ko-KR');save();closeModal();renderPage();notify(`${p.name}의 ${r.label} 내용을 반영했어요.`);
  }
  function manualSource(title,excerpt,priorId){const id=`manual-${Date.now()}-${Math.random().toString(36).slice(2,7)}`;state.sources[id]={title,date:new Date().toLocaleDateString('ko-KR'),actor:'목업에서 직접 수정',excerpt,priorId:priorId||null};return id;}
  function formError(text){const target=document.getElementById('form-error');target.textContent=text;target.hidden=false;}
  document.addEventListener('submit',event=>{
    const form=event.target;if(!['person-form','policy-form','context-form','review-form'].includes(form.id))return;event.preventDefault();const data=new FormData(form);
    if(form.id==='person-form'){
      const name=String(data.get('name')||'').trim();if(!name){formError('이름을 입력해 주세요.');form.elements.name.focus();return;}
      const aliases=[...new Set(String(data.get('aliases')||'').split(',').map(v=>v.trim()).filter(Boolean))];
      const org=String(data.get('org')||'').trim()||'소속 미등록',role=String(data.get('role')||'').trim()||'역할 미등록',note=String(data.get('note')||'').trim();
      let p=person(form.dataset.person);const isNew=!p;
      if(!p){p={id:`person-${Date.now()}`,name,aliases,relation:data.get('relation'),org,role,note,policy:'cautious_use',shade:93,status:'active',confirmation:'confirmed',referenced:'아직 없음',date:new Date().toISOString().slice(0,10),facts:[],contexts:[]};state.people.push(p);const source=manualSource('새 인물 직접 등록',`${name} · ${rel(p.relation)}`);state.edges.push({id:`edge-${p.id}`,a:'self',b:p.id,type:p.relation,source});}
      for(const [type,value,label] of [['organization',org,'소속'],['role',role,'역할']]){
        const old=p.facts.find(f=>f.type===type);
        if(value.endsWith('미등록')){p.facts=p.facts.filter(f=>f.type!==type);continue;}
        if(old?.value===value)continue;
        const source=manualSource(`${label} 직접 수정`,`${name}의 ${label}: ${value}`,old?.source);
        if(old){old.previous={value:old.value,source:old.source};old.value=value;old.source=source;}else p.facts.push({type,label,value,source});
      }
      Object.assign(p,{name,aliases,org,role,note});ui.selected=p.id;save();closeModal();renderPage();notify(isNew?`${name} 님을 추가했어요.`:'프로필 변경사항을 저장했어요.');
    }else if(form.id==='policy-form'){
      const p=person(form.dataset.person),value=data.get('policy');if(!seed.policies[value])return;p.policy=value;save();closeModal();renderPage();notify('AI 사용 범위를 저장했어요.');
    }else if(form.id==='context-form'){
      const title=String(data.get('title')||'').trim(),text=String(data.get('text')||'').trim();if(!title||!text){formError('제목과 맥락을 모두 입력해 주세요.');return;}
      const p=person(form.dataset.person),c=p.contexts.find(item=>item.id===form.dataset.context);const source=manualSource('맥락 직접 정정',text,c.source);c.previous={text:c.text,source:c.source};Object.assign(c,{title,text,policy:data.get('policy'),source});save();closeModal();renderPage();notify('기억을 수정하고 출처를 남겼어요.');
    }else{
      const value=String(data.get('value')||'').trim();if(!value){formError('반영할 내용을 입력해 주세요.');return;}const r=state.reviews.find(item=>item.id===form.dataset.review);if(r)applyReview(r,value,true);
    }
  });
  document.addEventListener('click',event=>{
    const target=event.target.closest('[data-action]');if(!target||target.disabled)return;
    if(event.target.closest('a')&&target.dataset.action==='select-person')return;
    const {action,id,value}=target.dataset;
    if(action==='select-person'){ui.selected=id;renderPeopleResults();const panel=document.getElementById('preview');if(panel)panel.innerHTML=preview(person(id));}
    else if(action==='people-filter'){ui.filter=value;renderPage();}
    else if(action==='view'){ui.view=value;renderPage();}
    else if(action==='clear-search'){ui.query='';ui.filter='all';renderPage();}
    else if(action==='new-person')openPersonForm();
    else if(action==='edit-person')openPersonForm(id);
    else if(action==='person-tab'){ui.tab=value;renderPage();}
    else if(action==='policy')openPolicyForm(id);
    else if(action==='edit-context')openContextForm(target.dataset.person,id);
    else if(action==='source'){
      const source=state.sources[id];openModal('기억의 출처',`<div class="modal-body"><p class="modal-intro">이 기록을 뒷받침하는 짧은 발췌예요.</p>${evidence(id)}${source?.priorId?`<h3 class="review-section-title">수정 이전의 출처</h3>${evidence(source.priorId)}`:''}</div>`,`<button class="button" data-action="close-modal">닫기</button>`);
    }
    else if(action==='close-modal')closeModal();
    else if(action==='graph-node'){ui.graphSelected=id;ui.edgeSelected=null;updateGraphSelection();}
    else if(action==='graph-edge'){const edge=state.edges.find(item=>item.id===id);ui.edgeSelected=id;ui.graphSelected=edge.a===ui.focal?edge.b:edge.a;updateGraphSelection();}
    else if(action==='zoom'){ui.zoom=Math.max(.6,Math.min(1.8,Math.round((ui.zoom+(value==='in'?.2:-.2))*10)/10));transformGraph();}
    else if(action==='fit-graph'){ui.zoom=1;ui.panX=0;ui.panY=0;transformGraph();}
    else if(action==='reset-graph'){Object.assign(ui,{focal:'self',relation:'all',zoom:1,panX:0,panY:0,graphSelected:'minji',edgeSelected:null});renderPage();}
    else if(action==='review-filter'){ui.reviewFilter=value;ui.reviewSelected=null;renderPage();}
    else if(action==='select-review'){ui.reviewSelected=id;renderPage();}
    else if(action==='review-edit')openReviewEdit(id);
    else if(action==='review-accept'){const r=state.reviews.find(item=>item.id===id);if(r)applyReview(r,r.after);}
    else if(['review-archive','review-reject','review-clarify'].includes(action)){
      const r=state.reviews.find(item=>item.id===id);if(!r||!unresolved(r))return;r.status={'review-archive':'archived','review-reject':'rejected','review-clarify':'needs_clarification'}[action];r.processedDate=action==='review-clarify'?null:new Date().toLocaleDateString('ko-KR');save();renderPage();notify(action==='review-clarify'?'추가 확인이 필요한 항목으로 남겼어요.':action==='review-reject'?'제안을 거절했어요. 기존 정보는 유지돼요.':'리뷰를 보관했어요. 기존 정보는 유지돼요.');
    }else if(action==='about')openModal('Kinlayer 목업 안내',`<div class="modal-body"><p>사람과 관계에 대한 AI의 기억을 살펴보고, 필요할 때 직접 바로잡는 공간이에요.</p><ul class="about-list"><li>등장하는 인물과 기록은 모두 가상 데이터예요.</li><li>검색·편집·그래프·리뷰 흐름을 체험할 수 있어요.</li><li>실제 Kinlayer 서비스에는 연결하지 않았어요.</li><li>${storageAvailable?'변경사항은 이 브라우저에만 저장돼요.':'브라우저 저장소를 사용할 수 없어, 현재 페이지에서만 변경이 유지돼요.'}</li></ul><button class="text-link" data-action="reset-confirm">데모 변경사항 초기화</button></div>`,`<button class="button" data-action="close-modal">확인</button>`);
    else if(action==='reset-confirm')openModal('데모를 초기화할까요?',`<div class="modal-body"><p>이 브라우저에서 수정한 가상 인물과 리뷰를 처음 상태로 되돌려요.</p></div>`,`<button class="button ghost" data-action="close-modal">취소</button><button class="button danger" data-action="reset-demo">데모 초기화</button>`);
    else if(action==='reset-demo'){state=clone(seed);save();ui.selected='minji';ui.reviewSelected=null;closeModal();renderPage();notify('데모를 처음 상태로 되돌렸어요.');}
  });
  function updateGraphSelection(){
    document.querySelectorAll('.graph-node').forEach(node=>{const selected=node.dataset.id===ui.graphSelected;node.classList.toggle('selected',selected);node.setAttribute('aria-pressed',String(selected));});
    document.getElementById('graph-inspector').innerHTML=preview(person(ui.graphSelected),true);
  }
  document.addEventListener('input',event=>{if(event.target.id==='people-search'){ui.query=event.target.value;renderPeopleResults();}});
  document.addEventListener('change',event=>{
    if(event.target.id==='people-sort'){ui.sort=event.target.value;renderPeopleResults();}
    if(event.target.id==='graph-focal'){ui.focal=event.target.value;ui.graphSelected=ui.focal;ui.edgeSelected=null;ui.zoom=1;ui.panX=ui.panY=0;renderPage();}
    if(event.target.id==='graph-relation'){ui.relation=event.target.value;renderPage();}
  });
  document.addEventListener('keydown',event=>{
    if(event.key==='/'&&!event.target.closest('input,textarea,select,dialog')){const input=document.getElementById('people-search');if(input){event.preventDefault();input.focus();}}
    if((event.key==='Enter'||event.key===' ')&&event.target.matches('[tabindex="0"][data-action]')){event.preventDefault();event.target.dispatchEvent(new MouseEvent('click',{bubbles:true}));}
  });
  shell();
  const modal=document.getElementById('modal');
  modal.addEventListener('click',event=>{if(event.target===modal){const r=modal.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)closeModal();}});
  modal.addEventListener('close',()=>{if(returnFocus?.isConnected)returnFocus.focus();});
})();
