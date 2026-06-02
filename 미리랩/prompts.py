# -*- coding: utf-8 -*-
"""
prompts.py — 한글 프롬프트 빌더 모음

미리랩(정책 반응 시뮬레이터)에서 OpenAI 구조화 출력을 호출하기 위한
chat messages 를 조립한다. 세 가지 단계가 있다.

- build_react_messages   : 한 시민(페르소나)이 정책에 1차 반응
- build_interact_messages : 다른 시민들의 반응 요약(digest)을 보고 2차 상호작용
- build_aggregate_messages: 분석가가 전체 반응을 집계해 요약/쉬운글/개선안 작성

각 함수는 [{'role':'system','content':..},{'role':'user','content':..}] 형태의
리스트를 반환한다. 네트워크 호출/로직 없이 순수 문자열 조립만 수행한다.
"""

from typing import Optional


# ---------------------------------------------------------------------------
# 내부 헬퍼: 페르소나 dict 에서 사람이 읽기 좋은 텍스트 조각을 만든다.
# (state.py 의 Persona 계약을 그대로 따르되, 키가 없어도 죽지 않게 .get 사용)
# ---------------------------------------------------------------------------

# 인구통계 항목의 한글 라벨 매핑
_DEMO_LABELS = {
    "sex": "성별",
    "age": "나이",
    "marital_status": "결혼 상태",
    "family_type": "가구 형태",
    "housing_type": "주거 형태",
    "education_level": "학력",
    "occupation": "직업",
    "district": "거주 시군구",
    "province": "거주 광역시·도",
}

# 인구통계를 출력할 순서 (계약상 주요 항목)
_DEMO_ORDER = [
    "sex", "age", "marital_status", "family_type", "housing_type",
    "education_level", "occupation", "district", "province",
]


def _demographics_text(persona: dict) -> str:
    """인구통계 dict 를 '항목: 값' 줄 목록 문자열로 변환한다."""
    demo = persona.get("demographics") or {}
    lines = []
    for key in _DEMO_ORDER:
        value = demo.get(key)
        if value is None or value == "":
            continue
        label = _DEMO_LABELS.get(key, key)
        lines.append(f"- {label}: {value}")
    # 정의되지 않은 추가 항목이 있으면 뒤에 덧붙인다.
    for key, value in demo.items():
        if key in _DEMO_ORDER:
            continue
        if value is None or value == "":
            continue
        lines.append(f"- {key}: {value}")
    if not lines:
        return "- (제공된 인구통계 정보 없음)"
    return "\n".join(lines)


def _signals_text(persona: dict) -> str:
    """상황 신호(signals) dict 를 부드러운 서술 문장으로 바꾼다."""
    signals = persona.get("signals") or {}
    parts = []

    # 디지털 활용 능력 (0~1)
    dl = signals.get("digital_literacy")
    if isinstance(dl, (int, float)):
        if dl >= 0.75:
            parts.append("스마트폰이나 인터넷 같은 디지털 기기를 아주 능숙하게 다루는 편입니다.")
        elif dl >= 0.45:
            parts.append("디지털 기기를 무리 없이 쓰는 보통 수준입니다.")
        elif dl >= 0.2:
            parts.append("디지털 기기에 다소 서툴러 익숙하지 않은 편입니다.")
        else:
            parts.append("디지털 기기 사용을 매우 어려워하고 거의 익숙하지 않습니다.")

    # 소득 수준 (문자열)
    income = signals.get("income_level")
    if income:
        parts.append(f"소득 수준은 대체로 '{income}'에 해당합니다.")

    # 정부 신뢰도 (0~1)
    trust = signals.get("government_trust")
    if isinstance(trust, (int, float)):
        if trust >= 0.7:
            parts.append("정부 정책과 행정에 대한 신뢰가 높은 편입니다.")
        elif trust >= 0.4:
            parts.append("정부에 대해 반신반의하는 중립적인 태도를 보입니다.")
        else:
            parts.append("정부 정책에 대한 불신이 강하고 회의적인 편입니다.")

    # 사회 연결망 (목록)
    network = signals.get("social_network")
    if isinstance(network, (list, tuple)) and len(network) > 0:
        joined = ", ".join(str(x) for x in network)
        parts.append(f"평소 가깝게 교류하는 사람들은 {joined} 등입니다.")

    if not parts:
        return "- (특기할 만한 상황 신호 정보 없음)"
    return " ".join(parts)


def _persona_brief(persona: dict) -> str:
    """인물 요약(description + persona_text)을 합쳐 한 덩어리로 만든다."""
    description = (persona.get("description") or "").strip()
    persona_text = (persona.get("persona_text") or "").strip()
    chunks = []
    if description:
        chunks.append(description)
    if persona_text:
        chunks.append(persona_text)
    if not chunks:
        return "(인물 배경 설명 없음)"
    return "\n\n".join(chunks)


def _short_intro(persona: dict) -> str:
    """상호작용 단계에서 쓸 한 줄짜리 간단 인물 소개."""
    name = persona.get("name") or persona.get("id") or "한 시민"
    demo = persona.get("demographics") or {}
    bits = []
    if demo.get("age"):
        bits.append(f"{demo.get('age')}")
    if demo.get("occupation"):
        bits.append(f"{demo.get('occupation')}")
    if demo.get("district"):
        bits.append(f"{demo.get('district')} 거주")
    desc = (persona.get("description") or "").strip()
    head = f"{name}"
    if bits:
        head += "(" + ", ".join(str(b) for b in bits) + ")"
    if desc:
        # 설명이 너무 길면 앞부분만 사용
        snippet = desc.replace("\n", " ")
        if len(snippet) > 120:
            snippet = snippet[:120] + "…"
        head += " — " + snippet
    return head


def _metrics_text(metrics: dict) -> str:
    """집계 단계에서 metrics dict 를 '항목: 값' 줄 목록으로 변환한다."""
    if not metrics:
        return "- (집계 수치 없음)"
    lines = []
    for key, value in metrics.items():
        lines.append(f"- {key}: {value}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 1단계: 정책에 대한 1차 반응
# ---------------------------------------------------------------------------

def build_react_messages(persona: dict, policy: str, grounded: bool = True) -> list:
    """
    한 시민(페르소나)이 정책 원문을 읽고 보이는 1차 반응을 요청하는 messages.

    grounded=True  : 인물 정보(요약/인구통계/상황신호)를 모두 주입한 실험군
    grounded=False : 배경 정보를 제거한 ablation 대조군
    """
    system = (
        "당신은 대한민국의 한 시민입니다. 인물 정보에 완전히 몰입해 그 사람의 "
        "말투·지식수준·관심사로 정책에 반응하세요. 점수는 그 사람 입장에서 "
        "0~100으로. 반드시 지정된 구조화 형식으로만 답하세요."
    )

    policy_text = (policy or "").strip()

    if grounded:
        brief = _persona_brief(persona)
        demo = _demographics_text(persona)
        sig = _signals_text(persona)
        user = (
            "■ 인물 요약\n"
            f"{brief}\n\n"
            "■ 인구통계\n"
            f"{demo}\n\n"
            "■ 상황 신호\n"
            f"{sig}\n\n"
            "■ 정책 원문\n"
            f"{policy_text}\n\n"
            "■ 요청\n"
            "위 인물의 입장에서 이 정책에 대해 다음을 작성하세요.\n"
            "1) 입장: 찬성(support) / 반대(oppose) / 혼합(mixed) 중 하나를 고르세요.\n"
            "2) 반응: 그 사람의 말투로 한두 문단의 솔직한 반응을 쓰세요.\n"
            "3) 점수(각 0~100, 그 사람 기준): "
            "이해도(understanding, 정책을 얼마나 이해했는가), "
            "수혜 가능성(benefit, 본인이 혜택을 받을 가능성), "
            "신청 의향(intent, 실제로 신청·참여할 의향), "
            "불만도(dissatisfaction, 정책에 대한 불만 정도), "
            "공유 가능성(shareability, 주변에 알리고 공유할 가능성).\n"
            "4) 예상 행동(actions): 이 사람이 실제로 취할 법한 구체적 행동을 목록으로."
        )
    else:
        # ablation 대조군: 인물 정보를 제거하고 평범한 시민으로 가정
        user = (
            "당신은 특별한 배경 정보가 없는 평범한 대한민국 시민입니다.\n\n"
            "■ 정책 원문\n"
            f"{policy_text}\n\n"
            "■ 요청\n"
            "평범한 시민의 입장에서 이 정책에 대해 다음을 작성하세요.\n"
            "1) 입장: 찬성(support) / 반대(oppose) / 혼합(mixed) 중 하나를 고르세요.\n"
            "2) 반응: 솔직한 반응을 한두 문단으로 쓰세요.\n"
            "3) 점수(각 0~100): "
            "이해도(understanding), 수혜 가능성(benefit), 신청 의향(intent), "
            "불만도(dissatisfaction), 공유 가능성(shareability).\n"
            "4) 예상 행동(actions): 실제로 취할 법한 구체적 행동을 목록으로."
        )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


# ---------------------------------------------------------------------------
# 2단계: 다른 시민들 반응을 보고 상호작용
# ---------------------------------------------------------------------------

def build_interact_messages(persona: dict, policy: str, digest: str) -> list:
    """
    한 시민이 다른 시민들의 반응 요약(digest)을 보고, 자신의 사회 연결망을
    고려해 짧게 반응하고 (있다면) 입장 변화를 표시하도록 요청하는 messages.
    """
    system = (
        "당신은 대한민국의 한 시민입니다. 같은 정책에 대한 다른 시민들의 반응 "
        "요약을 보았습니다. 당신의 사회 연결망(평소 영향을 주고받는 사람들)을 "
        "고려해 한두 문장으로 반응하세요. 만약 다른 사람의 말 때문에 생각이나 "
        "입장이 바뀌었다면 그 변화를 분명히 표시하세요. 반드시 지정된 구조화 "
        "형식으로만 답하세요."
    )

    intro = _short_intro(persona)
    policy_line = (policy or "").strip().replace("\n", " ")
    # 정책 한 줄: 너무 길면 앞부분만
    if len(policy_line) > 160:
        policy_line = policy_line[:160] + "…"

    digest_text = (digest or "").strip() or "(다른 시민들의 반응 요약 없음)"

    user = (
        "■ 당신(인물)\n"
        f"{intro}\n\n"
        "■ 다른 시민들의 반응 요약\n"
        f"{digest_text}\n\n"
        "■ 정책 한 줄 소개\n"
        f"{policy_line}\n\n"
        "■ 요청\n"
        "1) 위 반응들을 보고 당신이 보일 한두 문장의 반응을 쓰세요.\n"
        "2) 입장이 바뀌었다면 바뀐 입장(support/oppose/mixed)을, 그대로면 변화 없음을 표시하세요.\n"
        "3) 누구(어떤 사람)의 말을 참고했는지 밝히세요."
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


# ---------------------------------------------------------------------------
# 3단계: 전체 집계 → 분석가 요약/쉬운글/개선안
# ---------------------------------------------------------------------------

def build_aggregate_messages(policy: str, metrics: dict, digest: str) -> list:
    """
    정책 분석가가 시민 반응 집계(metrics)와 반응 요약(digest)을 보고
    갈등/합의 요약, 쉬운글 변환, 구체적 개선안을 작성하도록 요청하는 messages.
    """
    system = (
        "당신은 숙련된 정책 분석가입니다. 시민 반응 집계 결과를 바탕으로 "
        "(1) 어디서 갈등이 생기고 어디서 합의가 이루어지는지 요약하고, "
        "(2) 정책 원문을 누구나 이해할 수 있는 쉬운 글로 다시 풀어 쓰고, "
        "(3) 시민 반응에 근거한 구체적이고 실행 가능한 개선안을 제시합니다. "
        "반드시 지정된 구조화 형식으로만 답하세요."
    )

    policy_text = (policy or "").strip()
    metrics_text = _metrics_text(metrics or {})
    digest_text = (digest or "").strip() or "(시민 반응 요약 없음)"

    user = (
        "■ 정책 원문\n"
        f"{policy_text}\n\n"
        "■ 반응 집계 수치(metrics)\n"
        f"{metrics_text}\n\n"
        "■ 시민 반응 요약(digest)\n"
        f"{digest_text}\n\n"
        "■ 요청\n"
        "1) 요약: 시민들 사이의 갈등 지점과 합의 지점을 균형 있게 정리하세요.\n"
        "2) 쉬운 글: 정책 원문을 어려운 용어 없이 누구나 이해할 수 있는 쉬운 글로 바꾸세요.\n"
        "3) 개선안: 시민 반응에 근거한 구체적이고 실행 가능한 정책 개선안을 목록으로 제시하세요."
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
