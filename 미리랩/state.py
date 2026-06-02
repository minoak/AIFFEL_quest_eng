"""공유 State 스키마 = 팀 약속 (the team contract).

이 파일은 rag/, graph/, eval/, app.py, ui/ 사이의 인터페이스다.
기존 필드 이름은 절대 바꾸지 말 것. 새 필드는 추가만(additive) 한다.
모든 모듈은 정확히 이 키들을 읽고 쓴다.
"""
from typing import TypedDict, Annotated, Optional
from operator import add


class Scores(TypedDict):
    """시민 1명의 5축 점수 (0~100). 개요의 핵심 점수 체계."""
    understanding: int     # 이해도
    benefit: int           # 수혜 가능성
    intent: int            # 신청 의향
    dissatisfaction: int   # 불만도
    shareability: int      # 공유 가능성


class Persona(TypedDict):
    """가상 시민 1명. nvidia/Nemotron-Personas-Korea 한 행에서 매핑된다."""
    id: str            # uuid
    name: str          # UI 표시용 이름
    description: str   # 한 줄 요약 (예: "76세 여성 · 독거 · 무직 · 서울 서초구")
    sources: list      # grounding 근거 (RAG 사용 시 채워짐, MVP=[])
    # --- 확장 (옵션, 기본 {} / "") ---
    demographics: dict # sex/age/marital_status/family_type/housing_type/education_level/occupation/district/province
    persona_text: str  # HF 페르소나 텍스트 1~2개 필드를 합친 것 (프롬프트 주입용)
    signals: dict      # digital_literacy(float) / income_level(str) / government_trust(float) / social_network(list)
    meta: dict         # 프롬프트엔 안 넣는 나머지 HF 컬럼 (확장/툴팁용)


class Reaction(TypedDict):
    """시민 1명의 정책 반응."""
    persona_id: str
    stance: str        # 'support' | 'oppose' | 'mixed'
    text: str          # 생성된 반응 텍스트
    evidence: list     # grounding 스니펫 (RAG 사용 시)
    # --- 확장 ---
    scores: Scores     # 5축 점수
    actions: list      # 예상 행동: ['신청 시도','가족 공유','주민센터 문의','포기' ...]
    grounded: bool     # True=페르소나 grounding / False=ablation(일반 시민)


class Interaction(TypedDict):
    """전파(채팅) 1건. SNS 채팅방 + 네트워크 그래프의 원천."""
    round: int
    from_id: str
    to_id: Optional[str]        # None = 채팅방 전체 broadcast
    text: str
    stance_shift: Optional[str] # 다른 의견을 보고 입장이 바뀌었는지 (옵션)


class SimState(TypedDict):
    """그래프 전체를 흐르는 상태."""
    policy: str                          # 시뮬레이션 대상 정책 원문
    personas: list                       # list[Persona]
    reactions: Annotated[list, add]      # list[Reaction] - 노드가 append
    interactions: Annotated[list, add]   # list[Interaction] - 전파 라운드
    summary: str                         # 갈등/합의 요약
    # --- 확장 ---
    grounded: bool                       # ablation 전역 토글 (기본 True)
    rounds: int                          # 전파 라운드 수 (기본 1, 최대 2)
    metrics: dict                        # 집계: 사회혼란도/정책수용도/신청의향지수 + 축별 평균
    improvements: dict                   # {'easy_text': str, 'policy_fixes': [str, ...]}
    edges: Annotated[list, add]          # 전파 엣지: {'from':id,'to':id,'round':int}
