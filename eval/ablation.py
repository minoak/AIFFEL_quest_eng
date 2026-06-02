"""Ablation eval: grounding ON vs OFF.  Owner: eval.

데모의 신뢰성 논증(credibility argument):
retrieve()/페르소나 grounding 을 끄면, 가상 시민들이 고정관념(stereotype)으로
'붕괴(collapse)'한다는 것을 정량적으로 보여준다.
Park et al. 스타일의 컴포넌트 ablation 검증이지, 미래-정확도 평가가 아니다.

핵심 가설:
- grounded=True  -> 페르소나마다 다른 입장/점수 -> 다양성(entropy/std) 높음.
- grounded=False -> 일반 시민으로 수렴 -> 동질화(homogenization) -> 다양성 낮음.
collapse_score = (ungrounded 동질성) - (grounded 동질성) > 0 이면 가설 성립.
"""
import math


# 점수에서 비교하는 5축 (state.py Scores 계약과 동일 순서)
_SCORE_AXES = ('understanding', 'benefit', 'intent', 'dissatisfaction', 'shareability')

# 입장 분류 (state.py Reaction.stance 계약)
_STANCES = ('support', 'oppose', 'mixed')


def _shannon_entropy(counts: list) -> float:
    """주어진 빈도 분포의 섀넌 엔트로피(bit 단위)를 계산한다.

    값이 한쪽으로 쏠릴수록(동질) 0 에 가깝고,
    고르게 퍼질수록(다양) log2(범주 수) 에 가까워진다.
    """
    total = sum(counts)
    if total <= 0:
        return 0.0
    ent = 0.0
    for c in counts:
        if c <= 0:
            continue
        p = c / total
        ent -= p * math.log2(p)
    return ent


def _mean(xs: list) -> float:
    """단순 산술 평균. 빈 리스트는 0.0."""
    return sum(xs) / len(xs) if xs else 0.0


def _std(xs: list) -> float:
    """모표준편차(population std). 표본 1개 이하는 0.0.

    동질화될수록 0 에 수렴한다 -> '붕괴' 신호로 사용.
    """
    n = len(xs)
    if n <= 1:
        return 0.0
    mu = _mean(xs)
    var = sum((x - mu) ** 2 for x in xs) / n
    return math.sqrt(var)


def _stance_distribution(reactions: list) -> dict:
    """반응 집합에서 support/oppose/mixed 빈도를 센다."""
    dist = {s: 0 for s in _STANCES}
    for r in reactions:
        st = (r.get('stance') or '').strip().lower()
        if st in dist:
            dist[st] += 1
        else:
            # 알 수 없는 입장은 mixed 로 보수적 처리 (집계 누락 방지)
            dist['mixed'] += 1
    return dist


def _axis_values(reactions: list, axis: str) -> list:
    """특정 축의 점수만 뽑아 리스트로 반환 (점수 누락 시 건너뜀)."""
    vals = []
    for r in reactions:
        scores = r.get('scores') or {}
        v = scores.get(axis)
        if isinstance(v, (int, float)):
            vals.append(float(v))
    return vals


def _analyze(reactions: list) -> dict:
    """반응 한 집합에 대한 다양성/동질성 지표를 계산한다.

    반환 키:
      n                    : 반응 개수
      stance_dist          : {'support','oppose','mixed'} 빈도
      stance_entropy       : 입장 분포의 섀넌 엔트로피 (높을수록 다양)
      score_std            : 5축 표준편차의 평균 (높을수록 다양)
      score_std_by_axis    : 축별 표준편차
      understanding_spread : 이해도 축의 {min, mean, max}
      homogeneity          : 동질성 점수 (높을수록 붕괴/수렴)
    """
    n = len(reactions)

    # 1) 입장 엔트로피: grounded 가 더 높게(다양) 나와야 함
    dist = _stance_distribution(reactions)
    stance_entropy = _shannon_entropy([dist[s] for s in _STANCES])

    # 2) 5축 표준편차: grounded 가 더 높게 나와야 함
    std_by_axis = {axis: _std(_axis_values(reactions, axis)) for axis in _SCORE_AXES}
    score_std = _mean(list(std_by_axis.values()))

    # 3) 이해도 축의 분포 폭 (min/mean/max)
    und_vals = _axis_values(reactions, 'understanding')
    understanding_spread = {
        'min': min(und_vals) if und_vals else 0.0,
        'mean': _mean(und_vals),
        'max': max(und_vals) if und_vals else 0.0,
    }

    # 4) 동질성(homogeneity) = '얼마나 똑같아졌나'.
    #    다양성 지표(엔트로피·표준편차)를 0~1 로 정규화한 뒤 1 에서 뺀다.
    #    - 엔트로피는 최대 log2(3) 로 나눠 정규화.
    #    - 표준편차는 점수 범위(0~100)의 표준편차 이론상 최대치(50)로 정규화.
    norm_entropy = stance_entropy / math.log2(len(_STANCES)) if n > 0 else 0.0
    norm_std = min(score_std / 50.0, 1.0)
    diversity = (norm_entropy + norm_std) / 2.0   # 0(완전수렴)~1(완전분산)
    homogeneity = 1.0 - diversity                 # 높을수록 붕괴

    return {
        'n': n,
        'stance_dist': dist,
        'stance_entropy': round(stance_entropy, 4),
        'score_std': round(score_std, 4),
        'score_std_by_axis': {k: round(v, 4) for k, v in std_by_axis.items()},
        'understanding_spread': {k: round(v, 4) for k, v in understanding_spread.items()},
        'homogeneity': round(homogeneity, 4),
    }


def _run_once(app, policy: str, personas: list, grounded: bool) -> list:
    """그래프를 1회 invoke 하고 reactions 리스트만 돌려준다.

    state.py SimState 계약대로 초기 상태를 구성한다.
    reactions/interactions/edges 는 Annotated[list, add] 라 빈 리스트로 시작.
    """
    init_state = {
        'policy': policy,
        'personas': personas,
        'reactions': [],
        'interactions': [],
        'summary': '',
        'grounded': grounded,
        'rounds': 1,
        'edges': [],
    }
    result = app.invoke(init_state)
    return result.get('reactions', []) or []


def run_ablation(policy: str, personas: list, app=None) -> dict:
    """grounding ON/OFF 를 각각 1회 실행하고 비교지표를 반환한다.

    Args:
        policy: 시뮬레이션 대상 정책 원문.
        personas: list[Persona] (data/personas.load_personas 결과).
        app: 컴파일된 LangGraph. None 이면 여기서 build_graph() 로 만든다.

    Returns:
        {
          'grounded':   {... 지표 ...},   # grounding ON
          'ungrounded': {... 지표 ...},   # grounding OFF
          'delta':      {                 # 두 조건의 차이 (양수=grounded가 더 다양)
              'stance_entropy': float,
              'score_std': float,
              'understanding_spread_range': float,
              'collapse_score': float,    # ungrounded 동질성 - grounded 동질성
          },
        }
    """
    # app 미제공 시 지연 import (모듈 import 시점에 그래프를 만들지 않기 위함)
    if app is None:
        from graph.build import build_graph
        app = build_graph()

    # 1) 두 조건 각각 1회 실행
    grounded_reactions = _run_once(app, policy, personas, grounded=True)
    ungrounded_reactions = _run_once(app, policy, personas, grounded=False)

    # 2) 각 집합 분석
    grounded_metrics = _analyze(grounded_reactions)
    ungrounded_metrics = _analyze(ungrounded_reactions)

    # 3) 비교(델타) 계산.
    #    이해도 분포 폭 = max - min (grounded 가 더 넓을 것으로 기대).
    g_und = grounded_metrics['understanding_spread']
    u_und = ungrounded_metrics['understanding_spread']
    grounded_und_range = g_und['max'] - g_und['min']
    ungrounded_und_range = u_und['max'] - u_und['min']

    # collapse_score: ungrounded 가 grounded 보다 얼마나 더 동질화(붕괴)됐나.
    # 양수면 "grounding 을 끄면 페르소나가 고정관념으로 붕괴한다"는 가설 성립.
    collapse_score = ungrounded_metrics['homogeneity'] - grounded_metrics['homogeneity']

    delta = {
        'stance_entropy': round(
            grounded_metrics['stance_entropy'] - ungrounded_metrics['stance_entropy'], 4
        ),
        'score_std': round(
            grounded_metrics['score_std'] - ungrounded_metrics['score_std'], 4
        ),
        'understanding_spread_range': round(grounded_und_range - ungrounded_und_range, 4),
        'collapse_score': round(collapse_score, 4),
    }

    return {
        'grounded': grounded_metrics,
        'ungrounded': ungrounded_metrics,
        'delta': delta,
    }
