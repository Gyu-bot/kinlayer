/* 모든 인물, 소속, 발췌, 날짜는 UI 시연을 위한 가상 데이터입니다. */
window.KinlayerDemo = {
  version: 1,
  policies: {
    freely_use: {label:'자유롭게 활용',description:'AI가 대화의 맥락에 맞게 이 정보를 활용할 수 있어요.'},
    cautious_use: {label:'신중하게 활용',description:'맥락과 출처를 살피고, 필요한 상황에서 신중하게 활용해요.'},
    ask_before_use: {label:'사용 전 확인',description:'이 정보를 활용하기 전에 사용자에게 먼저 확인해요.'},
    never_surface: {label:'응답에 노출하지 않음',description:'AI 응답에 이 정보가 직접 드러나지 않도록 제한해요.'}
  },
  relations: {coworker:'직장 동료',friend:'친구',family:'가족',former_coworker:'이전 동료',knows:'아는 사이',collaborated_with:'협업한 사이'},
  people: [
    {id:'minji',name:'김민지',aliases:['민지','민지 님'],relation:'coworker',org:'오브 스튜디오',role:'프로덕트 디자이너',policy:'cautious_use',status:'active',confirmation:'confirmed',referenced:'오늘',date:'2026-10-01',note:'복잡한 문제를 함께 정리하는 동료. 새로운 아이디어는 글로 먼저 공유하는 편을 좋아해요.',shade:93,
      facts:[{type:'organization',label:'소속',value:'오브 스튜디오',source:'minji-work'},{type:'role',label:'역할',value:'프로덕트 디자이너',source:'minji-work'}],
      contexts:[{id:'minji-comms',type:'communication_preference',title:'아이디어는 글로 먼저 공유',text:'회의 전에 간단한 문서로 생각을 공유하면, 충분히 검토한 뒤 의견을 나누기 편하다고 했어요.',date:'2026-09-26',policy:'cautious_use',source:'minji-comms'},{id:'minji-recent',type:'recent_interaction',title:'새 프로젝트의 방향을 함께 논의',text:'리서치 결과를 정리하며 다음 프로젝트의 초기 방향을 함께 이야기했어요.',date:'2026-09-29',policy:'freely_use',source:'minji-recent'}]},
    {id:'seojun',name:'박서준',aliases:['서준','준'],relation:'coworker',org:'오브 스튜디오',role:'프론트엔드 개발자',policy:'cautious_use',status:'active',confirmation:'confirmed',referenced:'오늘',date:'2026-10-01',note:'제품을 함께 만드는 동료. 구체적인 화면을 보면서 이야기하는 것을 선호해요.',shade:90,
      facts:[{type:'organization',label:'소속',value:'오브 스튜디오',source:'seojun-work'},{type:'role',label:'역할',value:'프론트엔드 개발자',source:'seojun-work'}],
      contexts:[{id:'seojun-context',type:'communication_preference',title:'화면을 보며 구체적으로 이야기',text:'제품 아이디어를 설명할 때 문서만 공유하기보다 화면 예시를 함께 보는 편을 좋아해요.',date:'2026-09-28',policy:'cautious_use',source:'seojun-work'}]},
    {id:'jiho',name:'이지호',aliases:['지호'],relation:'friend',org:'라운드',role:'브랜드 디자이너',policy:'freely_use',status:'active',confirmation:'confirmed',referenced:'어제',date:'2026-09-30',note:'전시와 사진 이야기를 자주 나누는 친구. 주말에는 작은 전시 공간을 찾아다녀요.',shade:95,
      facts:[{type:'organization',label:'소속',value:'라운드',source:'jiho-context'},{type:'role',label:'역할',value:'브랜드 디자이너',source:'jiho-context'}],
      contexts:[{id:'jiho-context',type:'recent_interaction',title:'주말 전시 이야기',text:'다음에 시간이 맞으면 함께 사진전을 보러 가기로 이야기했어요.',date:'2026-09-30',policy:'freely_use',source:'jiho-context'}]},
    {id:'sujin',name:'최수진',aliases:['수진'],relation:'friend',org:'모노랩',role:'서비스 기획자',policy:'cautious_use',status:'active',confirmation:'confirmed',referenced:'9월 29일',date:'2026-09-29',note:'대학 때부터 알고 지낸 친구. 최근 새로운 팀에 합류했어요.',shade:91,
      facts:[{type:'organization',label:'소속',value:'모노랩',source:'sujin-context'},{type:'role',label:'역할',value:'서비스 기획자',source:'sujin-context'}],
      contexts:[{id:'sujin-context',type:'recent_interaction',title:'새로운 팀에 적응하는 중',text:'새 팀의 일하는 방식에 익숙해지는 중이라고 이야기했어요.',date:'2026-09-29',policy:'cautious_use',source:'sujin-context'}]},
    {id:'doyun',name:'정도윤',aliases:['도윤','도윤 님'],relation:'coworker',org:'오브 스튜디오',role:'프로덕트 매니저',policy:'cautious_use',status:'active',confirmation:'confirmed',referenced:'9월 28일',date:'2026-09-28',note:'프로젝트의 우선순위를 함께 조율해요. 결정의 배경과 근거를 중요하게 생각해요.',shade:94,
      facts:[{type:'organization',label:'소속',value:'오브 스튜디오',source:'doyun-context'},{type:'role',label:'역할',value:'프로덕트 매니저',source:'doyun-context'}],
      contexts:[{id:'doyun-context',type:'communication_preference',title:'결정의 배경과 근거를 함께 공유',text:'제안을 할 때 문제의 배경과 참고한 자료를 함께 전달하는 것을 선호해요.',date:'2026-09-28',policy:'cautious_use',source:'doyun-context'}]},
    {id:'seoyeon',name:'윤서연',aliases:['서연'],relation:'friend',org:'소속 미등록',role:'역할 미등록',policy:'ask_before_use',status:'active',confirmation:'confirmed',referenced:'9월 26일',date:'2026-09-26',note:'오래 알고 지낸 친구. 일상과 책 이야기를 편하게 나누는 사이예요.',shade:92,
      facts:[],contexts:[{id:'seoyeon-context',type:'recent_interaction',title:'함께 읽은 책에 대한 대화',text:'최근 읽은 에세이를 이야기하며 다음에 빌려주기로 했어요.',date:'2026-09-26',policy:'ask_before_use',source:'seoyeon-context'}]},
    {id:'eunhee',name:'김은희',aliases:['엄마'],relation:'family',org:'소속 미등록',role:'역할 미등록',policy:'cautious_use',status:'active',confirmation:'confirmed',referenced:'9월 24일',date:'2026-09-24',note:'어머니. 주말에 함께 식사하면서 근황을 나누곤 해요.',shade:90,
      facts:[],contexts:[{id:'eunhee-context',type:'recent_interaction',title:'주말 식사 약속',text:'이번 주말에 함께 점심을 먹기로 이야기했어요.',date:'2026-09-24',policy:'cautious_use',source:'eunhee-context'}]},
    {id:'haneul',name:'이하늘',aliases:['하늘','동생'],relation:'family',org:'소속 미등록',role:'역할 미등록',policy:'cautious_use',status:'active',confirmation:'confirmed',referenced:'9월 22일',date:'2026-09-22',note:'동생. 요즘 사진 찍는 취미에 푹 빠져 있어요.',shade:95,
      facts:[],contexts:[{id:'haneul-context',type:'recent_interaction',title:'새로 시작한 사진 취미',text:'사진 수업을 듣기 시작했고, 주말마다 카메라를 들고 산책한다고 했어요.',date:'2026-09-22',policy:'cautious_use',source:'haneul-context'}]}
  ],
  edges:[
    {id:'edge-minji',a:'self',b:'minji',type:'coworker',source:'minji-work'},
    {id:'edge-seojun',a:'self',b:'seojun',type:'coworker',source:'seojun-work'},
    {id:'edge-jiho',a:'self',b:'jiho',type:'friend',source:'jiho-context'},
    {id:'edge-sujin',a:'self',b:'sujin',type:'friend',source:'sujin-context'},
    {id:'edge-doyun',a:'self',b:'doyun',type:'coworker',source:'doyun-context'},
    {id:'edge-seoyeon',a:'self',b:'seoyeon',type:'friend',source:'seoyeon-context'},
    {id:'edge-eunhee',a:'self',b:'eunhee',type:'family',source:'eunhee-context'},
    {id:'edge-haneul',a:'self',b:'haneul',type:'family',source:'haneul-context'},
    {id:'edge-team',a:'minji',b:'doyun',type:'coworker',source:'minji-work'}
  ],
  sources:{
    'minji-work':{title:'함께 일하는 사람에 대한 대화',date:'2026년 9월 18일',actor:'사용자 발언',excerpt:'민지는 오브 스튜디오에서 같이 일하는 동료야. 프로덕트 디자이너고, 도윤이랑 같은 프로젝트를 하고 있어.'},
    'minji-comms':{title:'협업 방식에 대한 대화',date:'2026년 9월 26일',actor:'사용자 발언',excerpt:'민지가 회의 전에 아이디어를 글로 먼저 보내주면 좋겠대. 미리 읽어보고 생각을 정리하고 싶다고 하더라.'},
    'minji-recent':{title:'프로젝트 근황에 대한 대화',date:'2026년 9월 29일',actor:'사용자 발언',excerpt:'오늘 민지랑 리서치 결과를 보면서 새 프로젝트를 어느 방향으로 시작하면 좋을지 이야기했어.'},
    'seojun-work':{title:'제품 협업에 대한 대화',date:'2026년 9월 28일',actor:'사용자 발언',excerpt:'오브 스튜디오에서 프론트엔드 개발하는 서준이랑 얘기했어. 구체적인 화면 예시를 보여주니 의견을 나누기 훨씬 편하더라.'},
    'jiho-context':{title:'친구와 주말 계획에 대한 대화',date:'2026년 9월 30일',actor:'사용자 발언',excerpt:'라운드에서 브랜드 디자인하는 내 친구 지호랑 사진전 얘기를 했어. 다음에 시간 맞춰서 같이 가려고.'},
    'sujin-context':{title:'친구의 근황에 대한 대화',date:'2026년 9월 29일',actor:'사용자 발언',excerpt:'대학 친구 수진이가 모노랩 서비스 기획팀으로 옮겼어. 아직 새 팀에 적응하는 중이래.'},
    'doyun-context':{title:'팀의 소통 방식에 대한 대화',date:'2026년 9월 28일',actor:'사용자 발언',excerpt:'오브 스튜디오의 프로덕트 매니저 도윤이는 제안을 할 때 배경이랑 참고한 자료를 같이 보는 걸 좋아해.'},
    'seoyeon-context':{title:'친구와 책에 대한 대화',date:'2026년 9월 26일',actor:'사용자 발언',excerpt:'서연이랑 최근 읽은 에세이 이야기를 했어. 다음에 만나면 그 책을 빌려주기로 했어.'},
    'eunhee-context':{title:'가족과의 약속에 대한 대화',date:'2026년 9월 24일',actor:'사용자 발언',excerpt:'엄마 김은희랑 이번 주말에 점심 먹기로 했어.'},
    'haneul-context':{title:'동생의 근황에 대한 대화',date:'2026년 9월 22일',actor:'사용자 발언',excerpt:'동생 하늘이가 사진 수업을 듣기 시작했대. 주말마다 카메라 들고 산책하러 나간다고 하더라.'},
    'review-minji':{title:'새로 전해 들은 이직 소식',date:'2026년 10월 1일',actor:'사용자 발언',excerpt:'민지가 다음 달부터 모노랩에서 일한다고 했던 것 같아. 아직 옮긴 건지, 옮길 예정인지는 다시 확인해봐야겠네.'},
    'review-seojun':{title:'서준과의 관계에 대한 대화',date:'2026년 10월 1일',actor:'사용자 발언',excerpt:'서준이는 회사에서 만난 게 아니라 원래 알고 지낸 친구야. 지금은 우연히 같은 회사에 다니는 거고.'},
    'review-seoyeon':{title:'연락 방식에 대한 대화',date:'2026년 9월 30일',actor:'사용자 발언',excerpt:'서연이는 갑자기 전화하기보다는 미리 메시지로 시간 괜찮은지 물어보는 게 좋겠더라.'}
  },
  reviews:[
    {id:'review-1',person:'minji',type:'profile_field',label:'소속 확인',title:'김민지의 소속을 확인해 주세요',summary:'현재 소속과 이직 소식이 달라요.',field:'organization',before:'오브 스튜디오',after:'모노랩',reason:'이직에 대한 언급이 있지만, 적용 시점은 분명하지 않아요. 현재 소속을 확인한 뒤 반영할 수 있어요.',source:'review-minji',status:'pending',date:'2026-10-01',policy:'cautious_use'},
    {id:'review-2',person:'seojun',type:'edge',label:'관계 확인',title:'박서준과의 관계를 확인해 주세요',summary:'동료이기 전에 알고 지낸 친구예요.',field:'relation',before:'직장 동료',after:'친구',reason:'기존 직장 동료 관계는 유지하고, 사용자 발언을 근거로 친구 관계를 추가하는 제안이에요.',source:'review-seojun',status:'pending',date:'2026-10-01',policy:'cautious_use'},
    {id:'review-3',person:'seoyeon',type:'observation',label:'소통 방식',title:'윤서연의 연락 선호를 확인해 주세요',summary:'통화 전 메시지로 먼저 확인해요.',field:'communication_preference',before:'등록된 소통 선호 없음',after:'통화 전 메시지로 시간 확인',reason:'사용자가 전한 경험을 소통 맥락으로 정리했어요. 상대가 직접 밝힌 선호인지는 확인되지 않았어요.',source:'review-seoyeon',status:'pending',date:'2026-09-30',policy:'ask_before_use'}
  ]
};
