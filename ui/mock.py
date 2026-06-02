"""목 데이터(mock) — 외부 호출/네트워크 0개로 완전한 SimState dict 생성.

목적:
- OpenAI 키가 없거나, 발표 도중 네트워크가 끊겨도 모든 탭이 똑같이 돈다.
- 탭/뷰모델 입장에서 mock vs 실데이터를 구분할 필요가 없도록,
  load_personas() / react_node() / aggregate_node() 가 만들어내는 키 형태와
  '완전히 동일한' 구조를 손으로 채운다.

핵심 계약(state.py):
- Persona: id,name,description,sources,demographics,persona_text,signals,meta
- Reaction: persona_id,stance('support'|'oppose'|'mixed'),text,evidence,scores(5축),actions,grounded
- Interaction: round,from_id,to_id,text,stance_shift
- edges: {'from','to','round'}
- metrics: 정책수용도/사회혼란도/신청의향지수/axis_means/세그먼트 등
- improvements: {'easy_text': str, 'policy_fixes': [str,...]}

결정론적: 난수를 쓰는 부분은 seed 고정. (사실상 손으로 다 적어서 난수 거의 불필요)
"""
from __future__ import annotations

import random
from sample_policies import DEFAULT_POLICY


# ---------------------------------------------------------------------------
# 5축 점수 헬퍼: 항상 int·0~100 범위로 clamp 해서 계약(Scores)을 보장한다.
# ---------------------------------------------------------------------------
def _scores(understanding, benefit, intent, dissatisfaction, shareability) -> dict:
    """5축 점수를 0~100 정수로 클램프해 Scores dict 를 만든다."""
    def c(v):
        return int(max(0, min(100, round(v))))
    return {
        "understanding": c(understanding),
        "benefit": c(benefit),
        "intent": c(intent),
        "dissatisfaction": c(dissatisfaction),
        "shareability": c(shareability),
    }


# ---------------------------------------------------------------------------
# 손으로 작성한 ~12명 페르소나.
# 연령/지역/직업/학력/가구형태/디지털 리터러시를 일부러 다양하게 분포시켰다.
# id 는 'p01'~'p12' 로 고정 → 결정론적이고, reactions/interactions 가 참조하기 쉽다.
# ---------------------------------------------------------------------------
def _personas() -> list:
    """발표용 12인 가상 시민. 계약(Persona)의 모든 키를 채운다."""
    raw = [
        # (id, name, desc, sex, age, marital, family, housing, edu, occ, district, province,
        #  digital_literacy, income_level, government_trust, social_network, persona_text)
        ("p01", "김복순", "76세 여성 · 독거 · 무직 · 서울 서초구",
         "여성", 76, "사별", "1인 가구", "자가(노후 주택)", "초등학교 졸업", "무직",
         "서초구", "서울특별시",
         0.10, "저소득", 0.55, ["복지관 어르신 모임", "옆집 이웃"],
         "혼자 사는 76세 어르신. 스마트폰은 전화와 가족 영상통화 정도만 쓴다. "
         "은행 앱이나 키오스크는 무서워서 늘 창구를 찾는다. 무릎이 안 좋아 멀리 못 다닌다."),

        ("p02", "이준호", "28세 남성 · 미혼 · 사무직 · 서울 관악구 원룸",
         "남성", 28, "미혼", "1인 가구", "월세(원룸)", "대학교 졸업", "사무직",
         "관악구", "서울특별시",
         0.92, "중간소득", 0.45, ["직장 동료 단톡방", "대학 친구 모임", "인스타 팔로워"],
         "혼자 자취하는 28세 직장인. 월세 부담이 가장 큰 고민이다. "
         "정보는 거의 다 스마트폰으로 찾고, 복지 정책도 앱으로 신청하는 걸 당연하게 여긴다."),

        ("p03", "박상철", "35세 남성 · 기혼 · 자영업(분식집) · 인천 부평구",
         "남성", 35, "기혼", "부부+자녀", "전세(빌라)", "고등학교 졸업", "자영업",
         "부평구", "인천광역시",
         0.55, "중간소득", 0.35, ["상인회 단톡방", "동네 학부모 모임"],
         "분식집을 운영하는 35세 자영업자. 장사하느라 시간이 없어 복잡한 서류는 질색이다. "
         "정부 지원은 '나 같은 사람은 늘 대상에서 빠진다'는 불신이 있다."),

        ("p04", "정미영", "42세 여성 · 기혼 · 워킹맘(간호사) · 경기 수원시",
         "여성", 42, "기혼", "부부+자녀(2)", "자가(아파트)", "대학교 졸업", "보건의료(간호사)",
         "수원시", "경기도",
         0.78, "중간소득", 0.50, ["맘카페", "직장 단톡방", "아파트 입주민 카페"],
         "두 아이를 키우며 일하는 42세 간호사. 육아·교육·출산 관련 정책에 민감하다. "
         "맘카페에서 정보를 빠르게 공유하고 퍼뜨리는 허브 역할을 한다."),

        ("p05", "최유진", "19세 여성 · 미혼 · 대학생 · 부산 (기숙사)",
         "여성", 19, "미혼", "부모와 별거(기숙사)", "기숙사", "대학교 재학", "학생",
         "금정구", "부산광역시",
         0.95, "저소득", 0.40, ["과 동기 단톡방", "틱톡", "에브리타임"],
         "타지에서 대학을 다니는 19세 새내기. 부모와 떨어져 산다. 용돈이 빠듯하다. "
         "정책 정보는 친구나 학교 커뮤니티에서 듣고, 도움 되면 바로 공유한다."),

        ("p06", "한영수", "60세 남성 · 기혼 · 농업 · 전남 해남군",
         "남성", 60, "기혼", "부부", "자가(단독)", "중학교 졸업", "농업",
         "해남군", "전라남도",
         0.25, "저소득", 0.60, ["마을 이장", "농협 모임", "친척"],
         "벼농사를 짓는 60세 농업인. 읍내까지 차로 30분이라 행정 처리가 번거롭다. "
         "온라인 신청은 거의 못하고, 마을 이장이나 면사무소에 의존한다."),

        ("p07", "송경자", "54세 여성 · 기혼 · 전업주부 · 대구 수성구",
         "여성", 54, "기혼", "부부+자녀(성인)", "자가(아파트)", "고등학교 졸업", "전업주부",
         "수성구", "대구광역시",
         0.60, "중간소득", 0.48, ["동네 친구 모임", "교회 권사회", "카톡 가족방"],
         "성인 자녀를 둔 54세 주부. 자녀(청년)나 친정 어머니(고령) 관련 정책이면 "
         "대신 알아보고 챙겨준다. 카톡으로 가족·지인에게 정보를 자주 나른다."),

        ("p08", "오태경", "33세 남성 · 미혼 · IT 개발자 · 성남 판교 (1인 가구)",
         "남성", 33, "미혼", "1인 가구", "전세(오피스텔)", "대학원 졸업", "IT 개발",
         "분당구", "경기도",
         0.98, "고소득", 0.42, ["개발자 슬랙", "GitHub", "트위터(X)"],
         "판교에서 일하는 33세 IT 개발자. 소득이 높아 대부분의 소득 기준 지원에서 제외된다. "
         "정책의 허점과 형평성을 따지길 좋아하고, 온라인에서 의견을 적극적으로 낸다."),

        ("p09", "윤말순", "68세 여성 · 기혼 · 무직 · 강원 춘천시",
         "여성", 68, "기혼", "부부", "자가(단독)", "초등학교 졸업", "무직",
         "춘천시", "강원특별자치도",
         0.15, "저소득", 0.65, ["경로당", "이웃", "교회"],
         "남편과 둘이 사는 68세 어르신. 스마트폰 글씨가 작아 잘 안 보인다. "
         "키오스크 앞에선 늘 당황한다. 디지털 교육이 있다면 받고 싶지만 어렵다고 느낀다."),

        ("p10", "강도현", "31세 남성 · 기혼 · 회사원(제조) · 울산 (신혼부부)",
         "남성", 31, "기혼", "신혼부부(무자녀)", "월세(아파트)", "전문대 졸업", "제조업 생산직",
         "남구", "울산광역시",
         0.70, "중간소득", 0.47, ["회사 동기 모임", "신혼 카페", "고향 친구들"],
         "결혼한 지 1년 된 31세 회사원. 곧 출산을 계획 중이라 주거·출산 지원에 관심이 많다. "
         "조건이 맞으면 적극적으로 신청하는 실속파다."),

        ("p11", "임수빈", "26세 여성 · 미혼 · 취업준비생 · 광주 (부모와 동거)",
         "여성", 26, "미혼", "부모와 동거", "부모 자가", "대학교 졸업", "무직(취준생)",
         "북구", "광주광역시",
         0.90, "저소득", 0.38, ["취준 스터디", "링크드인", "인스타"],
         "부모 집에 사는 26세 취업준비생. 소득이 없어 청년 지원이 절실하지만 "
         "'부모와 동거' 같은 조건 때문에 막히는 경우가 많아 좌절한 경험이 있다."),

        ("p12", "조병국", "49세 남성 · 이혼 · 일용직 · 대전 (고시원)",
         "남성", 49, "이혼", "1인 가구", "고시원", "고등학교 중퇴", "일용직",
         "동구", "대전광역시",
         0.40, "저소득", 0.30, ["인력사무소 사람들"],
         "고시원에 사는 49세 일용직 노동자. 소득이 불안정하고 사회 연결망이 거의 없다. "
         "복지 정보를 접할 기회 자체가 적고, 신청 절차가 복잡하면 금방 포기한다."),
    ]

    personas = []
    for (pid, name, desc, sex, age, marital, family, housing, edu, occ,
         district, province, dl, income, trust, network, ptext) in raw:
        personas.append({
            "id": pid,
            "name": name,
            "description": desc,
            "sources": [],  # MVP: RAG 미사용 → 빈 리스트(계약 준수)
            "demographics": {
                "sex": sex,
                "age": age,
                "marital_status": marital,
                "family_type": family,
                "housing_type": housing,
                "education_level": edu,
                "occupation": occ,
                "district": district,
                "province": province,
            },
            "persona_text": ptext,
            "signals": {
                "digital_literacy": dl,           # 0~1 float
                "income_level": income,           # str: 저/중간/고소득
                "government_trust": trust,         # 0~1 float
                "social_network": list(network),  # list[str]
            },
            "meta": {
                "source": "mock",                 # 목 데이터 표식
                "household_size": 1 if "1인" in family or "고시원" in housing else 2,
            },
        })
    return personas


# ---------------------------------------------------------------------------
# 각 페르소나의 반응(Reaction). stance/scores 를 페르소나 특성과 상관되게 손으로 설정.
# - 고령·저 digital_literacy → understanding 낮음
# - 정책 대상자 → benefit·intent 높음, 비대상자 → 낮음+불만↑
# - social_network 큼 → shareability 높음
# ---------------------------------------------------------------------------
def _reactions() -> list:
    """12인 반응. 기본 정책(청년 월세 한시 특별지원) 맥락에 맞춰 작성."""
    R = []

    # p01 김복순(76, 독거 어르신) — 청년 월세와 무관. mixed(이해 어렵고 나와 무관).
    R.append({
        "persona_id": "p01",
        "stance": "mixed",
        "text": "월세 지원이라는데 내가 받는 건지 아닌지 도통 모르겠어요. 글씨도 작고 어려워요. "
                "젊은 사람들한테는 도움 되겠지만 나 같은 늙은이는 해당이 안 되는 것 같네.",
        "evidence": [],
        "scores": _scores(understanding=22, benefit=8, intent=5, dissatisfaction=35, shareability=18),
        "actions": ["주민센터 문의", "포기"],
        "grounded": True,
    })

    # p02 이준호(28, 자취 직장인) — 핵심 대상자. support, intent 매우 높음.
    R.append({
        "persona_id": "p02",
        "stance": "support",
        "text": "딱 제 얘기네요. 무주택 자취 청년이고 월세가 제일 부담이었는데 월 20만 원이면 큽니다. "
                "소득 기준만 통과되면 바로 복지로에서 신청할 생각이에요.",
        "evidence": [],
        "scores": _scores(understanding=88, benefit=85, intent=90, dissatisfaction=12, shareability=72),
        "actions": ["신청 시도", "친구 공유", "복지로 검색"],
        "grounded": True,
    })

    # p03 박상철(35, 자영업) — 나이 초과·자가 아님이지만 본인 비대상. oppose(형평성 불만).
    R.append({
        "persona_id": "p03",
        "stance": "oppose",
        "text": "또 청년만 챙기네요. 우리 같은 30대 중반 자영업자는 매출 줄어 죽겠는데 늘 대상에서 빠집니다. "
                "서류 떼러 갈 시간도 없고요.",
        "evidence": [],
        "scores": _scores(understanding=58, benefit=15, intent=10, dissatisfaction=78, shareability=40),
        "actions": ["불만 토로", "상인회 공유"],
        "grounded": True,
    })

    # p04 정미영(42, 워킹맘) — 본인 비대상이나 정보 허브. mixed, shareability 매우 높음.
    R.append({
        "persona_id": "p04",
        "stance": "mixed",
        "text": "저는 대상이 아니지만 회사 후배나 조카가 딱 해당되겠어요. 좋은 정책 같아서 맘카페랑 단톡방에 "
                "공유해야겠어요. 다만 소득 기준 계산이 좀 헷갈리네요.",
        "evidence": [],
        "scores": _scores(understanding=80, benefit=20, intent=15, dissatisfaction=22, shareability=92),
        "actions": ["맘카페 공유", "단톡방 공유", "조카에게 알림"],
        "grounded": True,
    })

    # p05 최유진(19, 대학생 기숙사) — 부모와 별거·무주택. support지만 소득·계약 조건 불확실.
    R.append({
        "persona_id": "p05",
        "stance": "support",
        "text": "기숙사에 살아서 임대차계약서가 있어야 한다는 게 걸리지만, 자취 시작하면 받고 싶어요! "
                "친구들 단톡방에 바로 올렸어요. 용돈 빠듯한데 도움 되겠죠.",
        "evidence": [],
        "scores": _scores(understanding=70, benefit=55, intent=60, dissatisfaction=30, shareability=85),
        "actions": ["친구 공유", "조건 확인", "추후 신청 고려"],
        "grounded": True,
    })

    # p06 한영수(60, 농업) — 비대상·온라인 약함. oppose/mixed. understanding 낮음.
    R.append({
        "persona_id": "p06",
        "stance": "mixed",
        "text": "청년 지원이라니 우리 손주한테나 해당되겠구먼. 근데 복지로 누리집이 뭔지도 모르고, "
                "면사무소까지 가야 하나? 시골 사람한텐 신청이 영 어렵소.",
        "evidence": [],
        "scores": _scores(understanding=33, benefit=12, intent=8, dissatisfaction=48, shareability=25),
        "actions": ["이장에게 문의", "손주에게 알림"],
        "grounded": True,
    })

    # p07 송경자(54, 주부) — 자녀(청년) 대신 챙김. mixed→support 경향, 공유 활발.
    R.append({
        "persona_id": "p07",
        "stance": "support",
        "text": "우리 아들이 서울서 자취하는데 딱 맞겠어요. 제가 대신 서류 챙겨주려고요. "
                "가족 카톡방에 공유했어요. 좋은 정책이네요.",
        "evidence": [],
        "scores": _scores(understanding=68, benefit=58, intent=65, dissatisfaction=18, shareability=80),
        "actions": ["자녀 대신 신청 준비", "가족방 공유", "서류 확인"],
        "grounded": True,
    })

    # p08 오태경(33, 고소득 IT) — 소득 초과로 비대상. oppose(형평성·세금 논리), 의견 적극.
    R.append({
        "persona_id": "p08",
        "stance": "oppose",
        "text": "취지는 알겠는데 소득 기준 중위 60%면 정작 빠듯한 사람도 애매하게 걸립니다. "
                "예산 소진 시 조기 마감이면 선착순 줄서기일 뿐이죠. 설계가 허술해요.",
        "evidence": [],
        "scores": _scores(understanding=90, benefit=10, intent=5, dissatisfaction=70, shareability=65),
        "actions": ["온라인 비판 댓글", "지인 토론"],
        "grounded": True,
    })

    # p09 윤말순(68, 어르신) — 청년 정책 비대상. mixed, 이해도 매우 낮음.
    R.append({
        "persona_id": "p09",
        "stance": "mixed",
        "text": "월세 지원이라는데 우리 같은 노인은 안 되는 거지요? 글씨도 안 보이고 어려워서… "
                "젊은 사람들한테나 좋은 거 같네요.",
        "evidence": [],
        "scores": _scores(understanding=25, benefit=8, intent=5, dissatisfaction=32, shareability=20),
        "actions": ["경로당에서 물어봄", "포기"],
        "grounded": True,
    })

    # p10 강도현(31, 신혼·월세) — 무주택 부부지만 '부모와 별도 거주 청년' 요건 애매. mixed/support.
    R.append({
        "persona_id": "p10",
        "stance": "mixed",
        "text": "결혼해서 부부가 월세로 사는데 이게 1인 청년만 되는 건지 부부도 되는 건지 헷갈리네요. "
                "조건만 맞으면 당연히 신청해야죠. 행정복지센터에 한번 물어볼게요.",
        "evidence": [],
        "scores": _scores(understanding=62, benefit=50, intent=58, dissatisfaction=35, shareability=55),
        "actions": ["행정복지센터 문의", "조건 확인", "아내와 상의"],
        "grounded": True,
    })

    # p11 임수빈(26, 취준생·부모 동거) — 소득 없지만 '부모와 별도 거주' 요건에 막힘. oppose(좌절).
    R.append({
        "persona_id": "p11",
        "stance": "oppose",
        "text": "소득이 없는 저야말로 절실한데, 부모님이랑 같이 살면 또 안 된다고요? 매번 이런 식이에요. "
                "정작 돈 없는 청년은 자취할 보증금도 없는데 말이죠.",
        "evidence": [],
        "scores": _scores(understanding=82, benefit=18, intent=20, dissatisfaction=75, shareability=58),
        "actions": ["커뮤니티에 불만 글", "다른 청년 지원 검색"],
        "grounded": True,
    })

    # p12 조병국(49, 일용직·고시원) — 비대상·정보 소외·연결망 빈약. mixed, 금방 포기 경향.
    R.append({
        "persona_id": "p12",
        "stance": "mixed",
        "text": "나이도 넘었고 고시원은 임대차계약서가 되는지도 모르겠네. 이런 거 알아보다 일당 못 벌면 "
                "손해라… 그냥 안 하고 말지 뭐.",
        "evidence": [],
        "scores": _scores(understanding=38, benefit=15, intent=10, dissatisfaction=55, shareability=12),
        "actions": ["포기"],
        "grounded": True,
    })

    return R


# ---------------------------------------------------------------------------
# 전파(Interaction) 2라운드 + 동일 내용의 edges.
# 정보 허브(p04 맘카페, p07 가족방, p02 친구공유)가 퍼뜨리고,
# 비판자(p08, p11)가 반론을 던지는 구조 → 채팅방/네트워크 그래프가 살아 보인다.
# ---------------------------------------------------------------------------
def _interactions_and_edges():
    """라운드 1·2 전파 메시지와 대응 엣지를 함께 만든다."""
    interactions = [
        # ---- 라운드 1: 대상자/허브가 정보를 던진다 ----
        {"round": 1, "from_id": "p02", "to_id": None,
         "text": "이거 자취 청년 월세 20만 원 지원이래요. 무주택이면 신청해보세요!",
         "stance_shift": None},
        {"round": 1, "from_id": "p04", "to_id": "p05",
         "text": "유진아, 너 나중에 자취하면 이거 꼭 챙겨. 조건 보니 청년한테 좋더라.",
         "stance_shift": None},
        {"round": 1, "from_id": "p07", "to_id": "p02",
         "text": "우리 아들도 신청하려는데 서류가 어떻게 되나요? 같이 정보 좀 나눠요.",
         "stance_shift": None},
        {"round": 1, "from_id": "p08", "to_id": None,
         "text": "근데 소득 기준이 애매해서 정작 필요한 사람이 빠지는 구조 아닌가요?",
         "stance_shift": None},
        {"round": 1, "from_id": "p11", "to_id": "p08",
         "text": "맞아요. 저는 부모랑 산다고 아예 대상에서 빠졌어요. 너무 답답합니다.",
         "stance_shift": None},

        # ---- 라운드 2: 반론에 흔들리거나, 설득되어 입장이 이동한다 ----
        {"round": 2, "from_id": "p10", "to_id": "p02",
         "text": "부부도 되는지 헷갈렸는데 설명 보니 일단 센터에 물어봐야겠네요. 도움 됐어요.",
         "stance_shift": "mixed→support"},
        {"round": 2, "from_id": "p05", "to_id": "p04",
         "text": "언니 덕분에 알았어요! 친구들한테도 다 공유했어요. 자취하면 바로 신청할게요.",
         "stance_shift": None},
        {"round": 2, "from_id": "p03", "to_id": "p08",
         "text": "그쵸, 자영업자나 나이 좀 있는 사람은 늘 빠져요. 청년만 챙기는 느낌이라 좀 그래요.",
         "stance_shift": "mixed→oppose"},
        {"round": 2, "from_id": "p06", "to_id": "p07",
         "text": "우리 손주한테 알려주려는데 시골은 신청이 어렵네요. 면사무소도 가능하답니까?",
         "stance_shift": None},
        {"round": 2, "from_id": "p02", "to_id": "p11",
         "text": "부모랑 살면 안 되는 건 좀 아쉽네요. 그래도 자취 시작하면 다시 신청 가능할 거예요.",
         "stance_shift": None},
    ]

    # 동일 전파를 그래프 엣지로 변환(broadcast=to None 도 그대로 보존).
    edges = [
        {"from": it["from_id"], "to": it["to_id"], "round": it["round"]}
        for it in interactions
    ]
    return interactions, edges


# ---------------------------------------------------------------------------
# 집계(metrics) — aggregate_node 가 만들 키와 동일 형태.
# reactions 의 점수들을 실제로 평균내어 결정론적으로 산출(손값이 아니라 계산값).
# ---------------------------------------------------------------------------
def _metrics(reactions: list, personas: list) -> dict:
    """반응 집계: 정책수용도/사회혼란도/신청의향지수/축평균/세그먼트/분포."""
    n = len(reactions)

    # 축별 평균
    axes = ["understanding", "benefit", "intent", "dissatisfaction", "shareability"]
    axis_means = {
        a: round(sum(r["scores"][a] for r in reactions) / n, 1) for a in axes
    }

    # stance 분포
    stance_dist = {"support": 0, "oppose": 0, "mixed": 0}
    for r in reactions:
        stance_dist[r["stance"]] += 1

    # 핵심 지수(0~100)
    # - 정책수용도: 지지 비율 + (이해도/수혜/의향) 가중, 불만은 감점
    support_ratio = stance_dist["support"] / n
    accept = (
        support_ratio * 40
        + axis_means["benefit"] * 0.25
        + axis_means["intent"] * 0.25
        + axis_means["understanding"] * 0.10
        - axis_means["dissatisfaction"] * 0.15
    )
    # - 사회혼란도: 불만 + 공유(전파력) + 입장 양극화
    polarization = (stance_dist["oppose"] + stance_dist["support"]) / n  # mixed 적을수록↑
    confusion = (
        axis_means["dissatisfaction"] * 0.5
        + axis_means["shareability"] * 0.2
        + polarization * 30
    )
    # - 신청의향지수: 의향 평균을 그대로(대표 지표)
    apply_index = axis_means["intent"]

    def clamp100(v):
        return int(max(0, min(100, round(v))))

    # 세그먼트별 수용/의향(연령·디지털 리터러시 기준)
    def seg_avg(pred, key):
        ids = [p["id"] for p in personas if pred(p)]
        vals = [r["scores"][key] for r in reactions if r["persona_id"] in ids]
        return round(sum(vals) / len(vals), 1) if vals else 0.0

    segments = {
        "청년(19~34)": {
            "n": sum(1 for p in personas if 19 <= p["demographics"]["age"] <= 34),
            "intent": seg_avg(lambda p: 19 <= p["demographics"]["age"] <= 34, "intent"),
            "understanding": seg_avg(lambda p: 19 <= p["demographics"]["age"] <= 34, "understanding"),
        },
        "중장년(35~64)": {
            "n": sum(1 for p in personas if 35 <= p["demographics"]["age"] <= 64),
            "intent": seg_avg(lambda p: 35 <= p["demographics"]["age"] <= 64, "intent"),
            "understanding": seg_avg(lambda p: 35 <= p["demographics"]["age"] <= 64, "understanding"),
        },
        "고령(65+)": {
            "n": sum(1 for p in personas if p["demographics"]["age"] >= 65),
            "intent": seg_avg(lambda p: p["demographics"]["age"] >= 65, "intent"),
            "understanding": seg_avg(lambda p: p["demographics"]["age"] >= 65, "understanding"),
        },
        "디지털 취약(literacy<0.4)": {
            "n": sum(1 for p in personas if p["signals"]["digital_literacy"] < 0.4),
            "intent": seg_avg(lambda p: p["signals"]["digital_literacy"] < 0.4, "intent"),
            "understanding": seg_avg(lambda p: p["signals"]["digital_literacy"] < 0.4, "understanding"),
        },
    }

    return {
        # 한글 대표 지표 3종(개요 요구 키)
        "정책수용도": clamp100(accept),
        "사회혼란도": clamp100(confusion),
        "신청의향지수": clamp100(apply_index),
        # 축별 평균(영문 키)
        "axis_means": axis_means,
        # stance 분포
        "stance_dist": stance_dist,
        # 세그먼트 분석
        "segments": segments,
        # 부가 메타
        "n": n,
        "polarization": round(polarization, 2),
    }


# ---------------------------------------------------------------------------
# 개선안(improvements) — aggregate_node 가 만들 {'easy_text', 'policy_fixes'} 형태.
# ---------------------------------------------------------------------------
def _improvements() -> dict:
    """쉬운 글 버전 + 정책 개선 제안."""
    easy_text = (
        "[쉽게 읽는 청년 월세 지원 안내]\n\n"
        "● 누가 받나요?\n"
        "  - 만 19세부터 34세까지의 청년\n"
        "  - 집이 없고, 부모님과 따로 사는 사람\n"
        "  - 본인 월급이 많지 않은 사람(소득 기준 있음)\n\n"
        "● 얼마를 받나요?\n"
        "  - 매달 최대 20만 원, 최대 1년(12개월) 동안\n\n"
        "● 어떻게 신청하나요?\n"
        "  - 인터넷: '복지로' 누리집에서 신청\n"
        "  - 직접 방문: 사는 동네 행정복지센터(주민센터)\n"
        "  - 필요한 서류: 월세 계약서, 소득 증빙, 통장 사본\n\n"
        "● 도움이 필요하면?\n"
        "  - 어르신·인터넷이 어려운 분은 주민센터에 가면 직원이 도와드려요.\n"
        "  - 가족이 대신 알아봐 줄 수도 있어요."
    )
    policy_fixes = [
        "소득 기준 자동 계산기 제공: 신청 전 '나도 대상인지'를 한 번에 확인하도록 복지로에 "
        "간단 입력 도구를 붙인다(불확실성으로 인한 포기 감소).",
        "부모 동거 청년 예외 통로 마련: 소득이 없는 취준생 등은 '독립 준비 단계'로 일부 인정해 "
        "완전 배제를 줄인다(임수빈 같은 사각지대 해소).",
        "고령자·디지털 취약층 안내 분리: 청년 정책이라도 '대상 아님'을 명확히 표시하고, "
        "어르신에게는 별도 디지털 교육·대리 신청 안내를 연결한다(혼란·불만 완화).",
        "비수도권·농촌 신청 채널 확대: 면사무소/이장 대리 접수, 찾아가는 신청 지원으로 "
        "지역 격차를 줄인다(한영수·조병국 같은 접근성 문제 보완).",
    ]
    return {"easy_text": easy_text, "policy_fixes": policy_fixes}


# ---------------------------------------------------------------------------
# 요약(summary) — 갈등/합의 한 문단.
# ---------------------------------------------------------------------------
def _summary() -> str:
    """갈등과 합의를 함께 담은 한 문단 요약."""
    return (
        "핵심 대상인 자취 청년(이준호·최유진)과 그들을 챙기는 정보 허브(워킹맘 정미영·주부 송경자)는 "
        "정책을 적극 환영하며 신청 의향과 공유가 매우 높았다. 반면 소득이 높아 제외되는 IT 종사자(오태경)와 "
        "나이가 초과되는 자영업자(박상철)는 형평성에 불만을 드러냈고, 특히 소득이 없음에도 '부모 동거' 요건에 "
        "막힌 취준생(임수빈)의 좌절이 두드러졌다. 고령층(김복순·윤말순)과 농촌·취약 계층(한영수·조병국)은 "
        "정책 자체를 이해하기 어렵거나 신청 접근성이 떨어져 사실상 배제되는 양상을 보였다. "
        "공통된 합의점은 '취지에는 공감하나 대상 선정 기준이 헷갈리고, 신청 절차가 일부 계층에게 진입 장벽이 된다'는 것이며, "
        "정보가 단톡방·맘카페·가족방을 타고 빠르게 전파되는 만큼 안내의 명확성이 수용도를 크게 좌우할 것으로 보인다."
    )


# ---------------------------------------------------------------------------
# 공개 API: sample_simstate
# ---------------------------------------------------------------------------
def sample_simstate(policy: str | None = None, n: int = 12) -> dict:
    """외부 호출 0개의 완전한 SimState dict 를 만든다.

    Args:
        policy: 시뮬레이션 정책 원문. None 이면 기본 정책(청년 월세) 사용.
        n: 페르소나 수. 손으로 만든 12명 풀에서 앞에서부터 n명을 사용(최대 12).

    Returns:
        state.py 의 SimState 와 키 형태가 완전히 동일한 dict.
        탭/뷰모델은 mock 인지 실데이터인지 구분 없이 그대로 쓸 수 있다.
    """
    # 결정론성 보장: 혹시 모를 난수 사용 대비 seed 고정.
    random.seed(42)

    policy = policy or DEFAULT_POLICY

    # n 명만 사용(최대 12). 페르소나/반응을 id 기준으로 일관되게 잘라낸다.
    all_personas = _personas()
    n = max(1, min(int(n), len(all_personas)))
    personas = all_personas[:n]
    keep_ids = {p["id"] for p in personas}

    all_reactions = _reactions()
    reactions = [r for r in all_reactions if r["persona_id"] in keep_ids]

    # 전파/엣지는 양끝 노드가 모두 살아남은 경우만 포함(broadcast: to_id None 은 from 만 확인).
    all_inter, all_edges = _interactions_and_edges()

    def edge_ok(frm, to):
        if frm not in keep_ids:
            return False
        if to is None:
            return True
        return to in keep_ids

    interactions = [it for it in all_inter if edge_ok(it["from_id"], it["to_id"])]
    edges = [e for e in all_edges if edge_ok(e["from"], e["to"])]

    metrics = _metrics(reactions, personas)
    improvements = _improvements()
    summary = _summary()

    return {
        "policy": policy,
        "personas": personas,
        "reactions": reactions,
        "interactions": interactions,
        "summary": summary,
        "grounded": True,
        "rounds": 2,
        "metrics": metrics,
        "improvements": improvements,
        "edges": edges,
    }
