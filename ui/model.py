"""ViewModel 빌더.

build_view(sim) -> dict(ViewModel)
SimState(혹은 그와 비슷한 dict)를 받아 UI 탭들이 바로 그려쓸 수 있는
평탄화된 ViewModel dict 로 변환한다.

설계 원칙
- 누락 필드에 관대하다. sim 이 부분적으로만 채워져 있어도(예: metrics 없음,
  scores 일부 결손) 절대 KeyError/TypeError 로 죽지 않는다.
- 외부 호출(OpenAI/HF/네트워크) 전혀 없음. 순수 파이썬 + 표준 라이브러리만.
- streamlit 불필요(import 안 함). 어떤 UI 프레임워크와도 독립.

반환 키
    policy            : str   정책 원문
    personas          : list  Persona dict 목록(원본 그대로 통과)
    reactions         : list  Reaction dict 목록(scores 보정 적용본)
    reactions_by_id   : dict  persona_id -> reaction(보정본)
    interactions      : list  Interaction dict 목록
    edges             : list  전파 엣지 목록
    summary           : str   갈등/합의 요약
    metrics           : dict  집계 지표(없으면 reactions 로부터 계산)
    improvements      : dict  {'easy_text':str, 'policy_fixes':[...]}
    node_status       : dict  persona_id -> '정상'|'고립'|'오해'|'포기'|'미도달'
"""
from __future__ import annotations

# 5축 점수 키(순서 고정). state.Scores 와 일치.
SCORE_KEYS = ("understanding", "benefit", "intent", "dissatisfaction", "shareability")

# scores 누락 시 채울 기본값(0~100 중앙값). 게이지/카드가 깨지지 않도록.
DEFAULT_SCORE = 50

# node_status 상태 문자열(한글). UI 범례와 1:1.
ST_NORMAL = "정상"        # 메시지를 주고받고, 반대-불만 휴리스틱에 안 걸림
ST_ISOLATED = "고립"      # 전파 네트워크에 엣지가 하나도 없음(주지도 받지도 못함)
ST_MISUNDERSTAND = "오해"  # 반대 입장 + 이해도 낮음(정책을 잘못 알아들음)
ST_GIVEUP = "포기"        # 반대/불만 강함 + 신청의향 매우 낮음(아예 손 뗌)
ST_UNREACHED = "미도달"    # 반응 자체가 없음(반응 생성 대상에서 빠짐)


# ----------------------------------------------------------------------
# 작은 유틸: 안전한 형 변환/접근
# ----------------------------------------------------------------------
def _as_dict(x) -> dict:
    """x 가 dict 면 그대로, 아니면 빈 dict. (None/리스트/객체 방어)"""
    return x if isinstance(x, dict) else {}


def _as_list(x) -> list:
    """x 가 list 면 그대로, 아니면 빈 list."""
    return x if isinstance(x, list) else []


def _to_int_score(v, default: int = DEFAULT_SCORE) -> int:
    """점수 1개를 0~100 정수로 보정. 변환 실패/범위초과 모두 흡수."""
    try:
        n = int(round(float(v)))
    except (TypeError, ValueError):
        return default
    # 0~100 클램프
    return max(0, min(100, n))


def _clean_scores(raw) -> dict:
    """Reaction.scores 를 5축 전부 채운 정수 dict 로 보정.

    - 누락 축은 DEFAULT_SCORE(50) 로 채움.
    - 알 수 없는 값은 무시(SCORE_KEYS 만 추림).
    """
    src = _as_dict(raw)
    return {k: _to_int_score(src.get(k, DEFAULT_SCORE)) for k in SCORE_KEYS}


def _persona_id(p) -> str:
    """Persona dict 에서 id 추출(없으면 '')."""
    return str(_as_dict(p).get("id", "") or "")


# ----------------------------------------------------------------------
# metrics 계산: sim 에 metrics 가 없으면 reactions 의 scores 로 직접 집계
# ----------------------------------------------------------------------
def _compute_metrics(reactions: list) -> dict:
    """reactions(보정된 scores 포함)에서 집계 지표를 계산.

    반환 키
        understanding/benefit/intent/dissatisfaction/shareability : 축별 평균(0~100)
        정책수용도   : (이해도 + 수혜 + 신청의향)/3 - 불만도 보정 → 대략 0~100
        사회혼란도   : (불만도 + 공유가능성)/2 를 기반(불만이 잘 퍼질수록 ↑)
        신청의향지수 : 신청의향 평균
        n            : 집계에 쓰인 반응 수
    """
    n = len(reactions)
    if n == 0:
        # 빈 경우에도 키는 다 채워 UI 가 깨지지 않게.
        base = {k: 0 for k in SCORE_KEYS}
        base.update({
            "정책수용도": 0,
            "사회혼란도": 0,
            "신청의향지수": 0,
            "n": 0,
        })
        return base

    # 축별 합산 → 평균
    sums = {k: 0 for k in SCORE_KEYS}
    for r in reactions:
        sc = _as_dict(r).get("scores", {})
        for k in SCORE_KEYS:
            sums[k] += _to_int_score(sc.get(k, DEFAULT_SCORE))
    avg = {k: round(sums[k] / n, 1) for k in SCORE_KEYS}

    # 정책수용도: 긍정 3축 평균에서 불만도를 일부 차감(0~100 클램프).
    accept = (avg["understanding"] + avg["benefit"] + avg["intent"]) / 3.0
    accept = accept - 0.3 * avg["dissatisfaction"]
    accept = max(0.0, min(100.0, accept))

    # 사회혼란도: 불만이 강하고 잘 공유될수록 ↑.
    chaos = 0.6 * avg["dissatisfaction"] + 0.4 * avg["shareability"]
    chaos = max(0.0, min(100.0, chaos))

    metrics = dict(avg)
    metrics.update({
        "정책수용도": round(accept, 1),
        "사회혼란도": round(chaos, 1),
        "신청의향지수": round(avg["intent"], 1),
        "n": n,
    })
    return metrics


def _merge_metrics(sim_metrics, reactions: list) -> dict:
    """sim 에 들어온 metrics 를 존중하되, 빠진 표준 키는 계산값으로 보강."""
    computed = _compute_metrics(reactions)
    given = _as_dict(sim_metrics)
    # 계산값을 바닥에 깔고, 주어진 값으로 덮어쓴다(주어진 값 우선).
    merged = dict(computed)
    for k, v in given.items():
        merged[k] = v
    # 핵심 3지표가 주어진 metrics 에 없으면 계산값이 남아 있도록 보장(위 merge 로 이미 충족).
    return merged


# ----------------------------------------------------------------------
# node_status 판정: 전파 네트워크 도달 + 반응 휴리스틱
# ----------------------------------------------------------------------
def _build_edge_index(interactions: list, edges: list):
    """전파 엣지에서 '받은/준' 적 있는 persona_id 집합을 만든다.

    interactions(Interaction)과 edges(가벼운 엣지 dict) 둘 다 훑는다.
    to_id 가 None(전체 broadcast)인 경우는 '준' 쪽만 카운트하고,
    받은 쪽 카운트는 broadcast 플래그로 따로 표시한다.
    """
    senders: set = set()      # 메시지를 보낸 적 있는 id
    receivers: set = set()    # 특정 대상으로 메시지를 받은 적 있는 id
    has_broadcast = False     # 전체 broadcast 가 한 번이라도 있었는지

    for it in _as_list(interactions):
        d = _as_dict(it)
        frm = d.get("from_id")
        to = d.get("to_id", None)
        if frm:
            senders.add(str(frm))
        if to is None:
            has_broadcast = True
        elif to:
            receivers.add(str(to))

    for e in _as_list(edges):
        d = _as_dict(e)
        frm = d.get("from")
        to = d.get("to")
        if frm:
            senders.add(str(frm))
        if to:
            receivers.add(str(to))

    return senders, receivers, has_broadcast


def _status_one(pid: str, reaction, senders: set, receivers: set, has_broadcast: bool) -> str:
    """시민 1명의 상태를 판정.

    우선순위
      1) 반응 없음                     -> 미도달
      2) 네트워크 엣지 전무            -> 고립
         (단 broadcast 가 있었다면 '받음'으로 간주해 고립 제외)
      3) 반대 + 신청의향 매우 낮음     -> 포기
      4) 반대 + 이해도 낮음            -> 오해
      5) 그 외                         -> 정상
    """
    # 1) 반응 자체가 없으면 미도달
    if reaction is None:
        return ST_UNREACHED

    r = _as_dict(reaction)
    stance = str(r.get("stance", "") or "").lower()
    scores = _clean_scores(r.get("scores"))

    # 2) 고립: 보낸 적도 받은 적도 없고, broadcast 수신도 없음
    sent = pid in senders
    got = pid in receivers or has_broadcast
    if not sent and not got:
        return ST_ISOLATED

    # 반대 성향일 때의 세부 분기
    is_oppose = stance == "oppose"
    if is_oppose:
        # 3) 포기: 불만 강하고 신청의향이 바닥
        if scores["intent"] <= 25 and scores["dissatisfaction"] >= 60:
            return ST_GIVEUP
        # 4) 오해: 이해도가 낮은 채로 반대
        if scores["understanding"] <= 40:
            return ST_MISUNDERSTAND

    # mixed/지지 라도 신청의향이 거의 0 이고 불만이 매우 높으면 포기로 본다.
    if scores["intent"] <= 15 and scores["dissatisfaction"] >= 70:
        return ST_GIVEUP

    # 5) 그 외 정상
    return ST_NORMAL


def _build_node_status(personas: list, reactions_by_id: dict,
                       interactions: list, edges: list) -> dict:
    """모든 페르소나에 대해 node_status dict 생성."""
    senders, receivers, has_broadcast = _build_edge_index(interactions, edges)
    status: dict = {}
    for p in _as_list(personas):
        pid = _persona_id(p)
        if not pid:
            continue
        reaction = reactions_by_id.get(pid)  # 없으면 None -> 미도달
        status[pid] = _status_one(pid, reaction, senders, receivers, has_broadcast)
    return status


# ----------------------------------------------------------------------
# 공개 API
# ----------------------------------------------------------------------
def build_view(sim) -> dict:
    """SimState(dict)를 UI ViewModel(dict)로 변환한다.

    sim 이 dict 가 아니거나 None 이어도(방어적으로) 빈 ViewModel 을 돌려준다.
    """
    s = _as_dict(sim)

    # --- 원본 필드 추출(전부 관대하게) ---
    policy = str(s.get("policy", "") or "")
    personas = _as_list(s.get("personas"))
    raw_reactions = _as_list(s.get("reactions"))
    interactions = _as_list(s.get("interactions"))
    edges = _as_list(s.get("edges"))
    summary = str(s.get("summary", "") or "")
    improvements = _as_dict(s.get("improvements"))

    # --- reactions 정규화: scores 5축을 항상 채운 사본을 만든다 ---
    reactions: list = []
    reactions_by_id: dict = {}
    for r in raw_reactions:
        rd = _as_dict(r)
        if not rd:
            continue
        fixed = dict(rd)                      # 원본 훼손 없이 얕은 복사
        fixed["scores"] = _clean_scores(rd.get("scores"))
        # 누락 필드 최소 보정(카드 렌더 안전)
        fixed.setdefault("stance", "mixed")
        fixed.setdefault("text", "")
        fixed.setdefault("evidence", _as_list(rd.get("evidence")))
        fixed.setdefault("actions", _as_list(rd.get("actions")))
        fixed.setdefault("grounded", bool(rd.get("grounded", True)))
        pid = str(rd.get("persona_id", "") or "")
        fixed["persona_id"] = pid
        reactions.append(fixed)
        if pid:
            reactions_by_id[pid] = fixed

    # --- improvements 표준 키 보정 ---
    norm_improvements = {
        "easy_text": str(improvements.get("easy_text", "") or ""),
        "policy_fixes": _as_list(improvements.get("policy_fixes")),
    }
    # 혹시 다른 키가 더 있으면 보존(추가 정보 손실 방지)
    for k, v in improvements.items():
        if k not in norm_improvements:
            norm_improvements[k] = v

    # --- metrics: 있으면 존중 + 빠진 표준키 보강, 없으면 reactions 로 계산 ---
    metrics = _merge_metrics(s.get("metrics"), reactions)

    # --- node_status: 전파 도달 + 반응 휴리스틱 ---
    node_status = _build_node_status(personas, reactions_by_id, interactions, edges)

    return {
        "policy": policy,
        "personas": personas,
        "reactions": reactions,
        "reactions_by_id": reactions_by_id,
        "interactions": interactions,
        "edges": edges,
        "summary": summary,
        "metrics": metrics,
        "improvements": norm_improvements,
        "node_status": node_status,
    }
