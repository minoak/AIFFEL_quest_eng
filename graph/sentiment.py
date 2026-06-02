"""감성 점수 계산 모듈.

score_sentiment(text, scores=None) -> float in [-1, 1]
- scores(dict)가 주어지면: 점수 기반 극성(polarity) 계산.
- scores가 없으면: 한글 긍/부정 키워드 사전 기반 간단 휴리스틱.
- 선택적 KoBERT 훅: 환경변수 USE_KOBERT=='1' 이면 첫 호출 때 lazy 로드 시도,
  실패하면 조용히 휴리스틱으로 폴백.

주의: import 시점에는 무거운 로드를 절대 하지 않는다(키/모델 없어도 import 가능해야 함).
"""

from __future__ import annotations

import os
import re

# ---------------------------------------------------------------------------
# 한글 긍/부정 키워드 사전 (간단 휴리스틱용)
# ---------------------------------------------------------------------------
# 정책 반응 도메인에 맞춰 자주 등장하는 표현 위주로 구성.
_POSITIVE_WORDS = [
    "좋다", "좋은", "좋아", "좋네", "좋겠", "훌륭", "찬성", "지지", "환영",
    "도움", "유익", "이득", "혜택", "이익", "공정", "공평", "합리", "필요",
    "기대", "희망", "긍정", "만족", "감사", "고맙", "다행", "안심", "편리",
    "효과", "개선", "발전", "성공", "응원", "기쁘", "기쁨", "반갑", "든든",
    "고무적", "바람직", "현명", "적절", "적합", "신뢰", "믿", "최고", "추천",
    "공감", "동의", "환영하", "잘됐", "잘되", "기여", "도움이", "보탬",
]

_NEGATIVE_WORDS = [
    "나쁘", "나쁜", "별로", "싫", "반대", "거부", "우려", "걱정", "불안",
    "불만", "불공정", "불공평", "불합리", "부당", "차별", "손해", "피해",
    "낭비", "비효율", "실패", "문제", "엉터리", "황당", "어이없", "분노",
    "화나", "짜증", "답답", "한심", "실망", "후퇴", "위험", "부족", "미흡",
    "졸속", "탁상", "혼란", "부담", "비현실", "회의적", "의심", "불신",
    "반발", "비판", "지적", "역효과", "악영향", "절망", "막막", "포퓰리즘",
    "퍼주기", "세금낭비", "부정적", "의구심", "글쎄", "과연", "허점",
]

# 부정 표현(앞 토큰의 극성을 뒤집는 어미/부사) — 간단 처리용.
_NEGATORS = ["안", "못", "없", "아니", "않", "말", "글쎄"]


# ---------------------------------------------------------------------------
# KoBERT(또는 임의 한국어 text-classification) 파이프라인 lazy 캐시
# ---------------------------------------------------------------------------
_KOBERT_PIPE = None          # 로드된 파이프라인 객체(성공 시)
_KOBERT_TRIED = False        # 로드 시도 여부(중복 시도 방지)


def _get_kobert_pipe():
    """USE_KOBERT=='1' 일 때만 transformers 파이프라인을 lazy 로드.

    - 첫 호출 때 1회만 시도하고 결과를 모듈 전역에 캐시.
    - 어떤 이유로든 실패하면 None을 캐시하고 조용히 폴백되도록 한다.
    """
    global _KOBERT_PIPE, _KOBERT_TRIED

    if os.getenv("USE_KOBERT") != "1":
        return None
    if _KOBERT_TRIED:
        return _KOBERT_PIPE

    _KOBERT_TRIED = True
    try:
        # 무거운 임포트는 이 시점(첫 호출)에만 수행.
        from transformers import pipeline  # type: ignore

        # 모델명은 환경변수로 덮어쓸 수 있게 한다(기본은 다국어 감성 모델).
        model_name = os.getenv(
            "KOBERT_MODEL",
            "nlptown/bert-base-multilingual-uncased-sentiment",
        )
        _KOBERT_PIPE = pipeline("text-classification", model=model_name)
    except Exception:
        # transformers 미설치/모델 다운로드 실패/네트워크 등 모든 예외 → 조용히 폴백.
        _KOBERT_PIPE = None

    return _KOBERT_PIPE


def _kobert_polarity(text: str):
    """KoBERT 파이프라인으로 극성 추정. 실패하면 None 반환.

    라벨 형식이 모델마다 다르므로 휴리스틱하게 [-1, 1]로 변환한다.
    - '1 star'~'5 stars' 형식: (별점-3)/2
    - 'POSITIVE'/'NEGATIVE' 형식: score 부호 적용
    - 'LABEL_x' 형식: 인덱스를 -1..1 선형 매핑
    """
    pipe = _get_kobert_pipe()
    if pipe is None:
        return None

    try:
        out = pipe(text[:512])  # 길이 제한(토큰 폭주 방지)
        if isinstance(out, list):
            out = out[0]
        label = str(out.get("label", "")).strip().lower()
        score = float(out.get("score", 0.5))

        # (1) "N star(s)" 형식
        m = re.search(r"([1-5])\s*star", label)
        if m:
            stars = int(m.group(1))
            return _clamp((stars - 3) / 2.0)

        # (2) positive / negative
        if "pos" in label:
            return _clamp(score)
        if "neg" in label:
            return _clamp(-score)
        if "neu" in label:
            return 0.0

        # (3) "label_x" 형식 → 인덱스 추출 후 선형 매핑
        m = re.search(r"label[_\-]?(\d+)", label)
        if m:
            idx = int(m.group(1))
            # 0 → 부정, 1 → (이진이면)긍정. 보수적으로 0:-, 1:+ 로 처리.
            return _clamp(score if idx >= 1 else -score)

        # 알 수 없는 라벨 → 추정 불가
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 유틸
# ---------------------------------------------------------------------------
def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    """값을 [lo, hi] 범위로 자른다."""
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def _polarity_from_scores(scores: dict) -> float:
    """Scores(dict)로부터 극성을 계산해 [-1, 1]로 매핑.

    polarity_raw = intent + understanding - 1.2*dissatisfaction + 0.3*benefit
    각 점수는 0~100 가정. 가중합의 이론적 범위를 이용해 [-1, 1]로 정규화한다.

    가중치: intent(+1), understanding(+1), benefit(+0.3), dissatisfaction(-1.2)
      - 최댓값(모두 우호): 100*(1 + 1 + 0.3) = 230  (dissatisfaction=0)
      - 최솟값(모두 비우호): 100*(-1.2) = -120        (나머지=0)
    이 비대칭 범위를 0점 기준으로 [-1,1]에 맞도록,
    양수 측은 230, 음수 측은 120 으로 각각 나눠 매핑한다.
    """
    def g(key: str) -> float:
        try:
            return float(scores.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    intent = g("intent")
    understanding = g("understanding")
    benefit = g("benefit")
    dissatisfaction = g("dissatisfaction")

    raw = intent + understanding - 1.2 * dissatisfaction + 0.3 * benefit

    # 0을 기준으로 양/음 측을 각자의 최대 절댓값으로 정규화(부호별 스케일링).
    if raw >= 0:
        pol = raw / 230.0
    else:
        pol = raw / 120.0

    return _clamp(pol)


def _polarity_from_keywords(text: str) -> float:
    """키워드 사전 기반 간단 극성 점수.

    - 긍정/부정 키워드 출현 횟수를 센다.
    - 부정어(안/못/없 등)가 키워드 바로 앞 윈도우에 있으면 극성을 약하게 뒤집는다.
    - 최종적으로 (pos - neg) / (pos + neg) 로 [-1, 1] 정규화.
    """
    if not text:
        return 0.0

    pos = 0.0
    neg = 0.0

    for w in _POSITIVE_WORDS:
        cnt = text.count(w)
        if cnt:
            pos += cnt

    for w in _NEGATIVE_WORDS:
        cnt = text.count(w)
        if cnt:
            neg += cnt

    # 부정어 처리: "좋지 않다", "도움 안 된다" 같은 패턴을 거칠게 보정.
    # 긍정 키워드 주변에 부정어가 있으면 긍정→부정으로 일부 이동.
    for neg_word in _NEGATORS:
        for pw in _POSITIVE_WORDS:
            # 긍정어 + (0~3자) + 부정어 패턴
            pattern = re.escape(pw) + r".{0,4}?" + re.escape(neg_word)
            flips = len(re.findall(pattern, text))
            if flips:
                shift = min(flips, pos)
                pos -= shift
                neg += shift

    total = pos + neg
    if total <= 0:
        return 0.0

    return _clamp((pos - neg) / total)


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------
def score_sentiment(text, scores=None) -> float:
    """텍스트(및 선택적 점수)로부터 감성 극성을 [-1, 1]로 반환.

    우선순위:
      1) scores(dict)가 주어지면 점수 기반 극성을 사용(가장 신뢰).
      2) scores가 없으면:
         - USE_KOBERT=='1' 이면 KoBERT 파이프라인 시도(실패 시 폴백).
         - 그 외(또는 폴백)에는 한글 키워드 휴리스틱 사용.

    Args:
        text: 분석 대상 문자열(None 허용 — 빈 텍스트로 취급).
        scores: Scores dict(understanding/benefit/intent/dissatisfaction/shareability).

    Returns:
        float: [-1, 1] 범위의 감성 극성(양수=긍정).
    """
    # 1) 점수 기반(가장 우선)
    if scores:
        return _polarity_from_scores(scores)

    text = (text or "").strip()
    if not text:
        return 0.0

    # 2) KoBERT 훅(옵션) — 실패 시 조용히 폴백
    pol = _kobert_polarity(text)
    if pol is not None:
        return _clamp(pol)

    # 3) 키워드 휴리스틱
    return _polarity_from_keywords(text)
